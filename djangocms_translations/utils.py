import json
from collections import defaultdict, OrderedDict
from functools import lru_cache
from itertools import chain

from cms import api
from cms.extensions import extension_pool
from cms.models import Page, CMSPlugin, PageContent, Placeholder
from cms.plugin_pool import plugin_pool
from cms.utils.placeholder import get_declared_placeholders_for_obj
from cms.utils.plugins import copy_plugins_to_placeholder, get_bound_plugins
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import BooleanField, IntegerField
from django.forms import modelform_factory
from django.utils.safestring import mark_safe
from django.utils.translation import get_language_info
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import JsonLexer
from yurl import URL
from .conf import TRANSLATIONS_CONF

try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin

USE_HTTPS = getattr(settings, 'URLS_USE_HTTPS', False)


@lru_cache()
def get_plugin_class(plugin_type):
    return plugin_pool.get_plugin(plugin_type)


@lru_cache()
def get_plugin_model(plugin_type):
    return get_plugin_class(plugin_type).model


def get_plugin_form_class(plugin_type, fields):
    plugin_class = get_plugin_class(plugin_type)
    plugin_fields = chain(
        plugin_class.model._meta.concrete_fields,
        plugin_class.model._meta.private_fields,
        plugin_class.model._meta.many_to_many,
    )
    plugin_fields_disabled = [
        field.name for field in plugin_fields
        if not getattr(field, 'editable', False)
    ]
    plugin_form_class = modelform_factory(
        plugin_class.model,
        fields=fields,
        exclude=plugin_fields_disabled,
    )
    return plugin_form_class


def get_plugin_form(plugin_type, data):
    _data = data.copy()
    plugin_form_class = get_plugin_form_class(plugin_type, fields=data.keys())
    multi_value_fields = [
        (name, field) for name, field in plugin_form_class.base_fields.items()
        if hasattr(field.widget, 'decompress') and name in data
    ]

    for name, field in multi_value_fields:
        # The value used on the form data is compressed,
        # and the form contains multi-value fields which expect
        # a decompressed value.
        compressed = data[name]

        try:
            decompressed = field.widget.decompress(compressed)
        except ObjectDoesNotExist:
            break

        for pos, value in enumerate(decompressed):
            _data['{}_{}'.format(name, pos)] = value
    return plugin_form_class(_data)


def add_domain(url, domain=None):
    # add the domain to this url.
    if domain is None:
        domain = Site.objects.get_current().domain

    url = URL(url)

    if USE_HTTPS:
        url = url.replace(scheme='https')
    else:
        url = url.replace(scheme='http')
    return str(url.replace(host=domain))


def pretty_data(data, LexerClass):
    formatter = HtmlFormatter(style='colorful')
    data = highlight(data, LexerClass(), formatter)
    style = '<style>' + formatter.get_style_defs() + '</style><br>'
    return mark_safe(style + data)


def pretty_json(data):
    data = json.dumps(json.loads(data), sort_keys=True, indent=2)
    return pretty_data(data, JsonLexer)


@lru_cache(maxsize=None)
def get_translatable_fields(plugin_type):
    conf = TRANSLATIONS_CONF.get(plugin_type, {})

    if 'fields' in conf:
        fields = conf['fields']
    else:
        model = get_plugin_model(plugin_type)

        opts = model._meta.concrete_model._meta
        fields = opts.local_fields
        fields = [
            field.name
            for field in fields
            if (
                not field.is_relation and
                not field.primary_key and
                not field.choices and
                not isinstance(field, BooleanField) and
                not isinstance(field, IntegerField)
            )
        ]

    excluded = conf.get('excluded_fields', [])
    return set(fields).difference(set(excluded))


@lru_cache(maxsize=None)
def get_text_field_child_label(plugin_type):
    return settings.DJANGOCMS_TRANSLATIONS_CONF.get(plugin_type, {}).get('text_field_child_label')


def get_language_name(lang_code):
    info = get_language_info(lang_code)
    if info['code'] == lang_code:
        return info['name']
    try:
        return dict(settings.LANGUAGES)[lang_code]
    except KeyError:
        # fallback to known name
        return info['name']


def get_page_url(page, language, is_https=False):
    return urljoin(
        'http{}://{}'.format(
            's' if is_https else '',
            page.node.site.domain,
        ),
        page.get_absolute_url(language=language),
    )


# TODO: For debugging
def create_translation(page: Page, language):
    title_kwargs = {
        "page": page,
        "language": language,
        "slug": 'test',
        "path": 'test',
        "title": 'test',
        "template": page.template,
        "created_by": User.objects.first()
    }
    # content_defaults = {
    #     "in_navigation": True,
    # }
    # title_kwargs.update(self.content_defaults)

    # if "menu_title" in data:
    #     title_kwargs["menu_title"] = data["menu_title"]
    #
    # if "page_title" in data:
    #     title_kwargs["page_title"] = data["page_title"]
    #
    # if "meta_description" in data:
    #     title_kwargs["meta_description"] = data["meta_description"]
    return api.create_page_content(**title_kwargs)


# TODO: For debugging
# @transaction.atomic
# def duplicate_page_content(source_page, target_page, source_language, target_language):
#         translation = create_translation(target_page, target_language)
#         target_page.page_content_cache[translation.language] = translation
#
#         extension_pool.copy_extensions(
#             source_page=source_page,
#             target_page=target_page,
#             languages=[translation.language],
#         )
#         placeholders = source_page.get_placeholders(source_language)
#
#         for source_placeholder in placeholders:
#             target_placeholder, is_created = translation.placeholders.get_or_create(
#                 slot=source_placeholder.slot,
#                 default_width=source_placeholder.default_width,
#             )
#             copy_plugins(source_placeholder, source_language, target_placeholder, target_language)
#         return translation


# TODO: For debugging
# def copy_plugins(source_placeholder, source_language, target_placeholder, target_language):
#     old_plugins = source_placeholder.get_plugins_list(language=source_language)
#
#     copied_plugins = copy_plugins_to_placeholder(old_plugins, target_placeholder, language=target_language)
#     new_plugin_ids = (new.pk for new in copied_plugins)
#
#     target_placeholder.clear_cache(target_language)
#
#     new_plugins = CMSPlugin.objects.filter(pk__in=new_plugin_ids)
#     new_plugins = list(new_plugins)
#     return new_plugins


@transaction.atomic
def import_plugins(plugins, placeholder, language, root_plugin_id=None):
    source_map = {}
    new_plugins = []

    if root_plugin_id:
        root_plugin = CMSPlugin.objects.get(pk=root_plugin_id)
        source_map[root_plugin_id] = root_plugin
    else:
        root_plugin = None

    for archived_plugin in plugins:
        # custom handling via "get_plugin_data" can lead to "null"-values
        # instead of plugin-dictionaries. We skip those here.
        if archived_plugin is None:
            continue

        if archived_plugin.parent_id:
            parent = source_map[archived_plugin.parent_id]
        else:
            parent = root_plugin

        if parent and parent.__class__ != CMSPlugin:
            parent = parent.cmsplugin_ptr
        plugin = archived_plugin.restore(
            placeholder=placeholder,
            language=language,
            parent=parent,
        )
        source_map[archived_plugin.pk] = plugin

        new_plugins.append(plugin)

    for new_plugin in new_plugins:
        plugin_class = get_plugin_class(new_plugin.plugin_type)

        if getattr(plugin_class, "_has_do_post_copy", False):
            # getattr is used for django CMS 3.4 compatibility
            # apps on 3.4 wishing to leverage this callback will need
            # to manually set the _has_do_post_copy attribute.
            plugin_class.do_post_copy(new_plugin, source_map)


@transaction.atomic
def import_plugins_to_content(placeholders, language, content):
    placeholder_obj_list = Placeholder.objects.filter(
        object_id=content.id,
    )

    page_placeholders = OrderedDict()
    for placeholder in placeholder_obj_list:
        page_placeholders[placeholder.slot] = placeholder

    for archived_placeholder in placeholders:
        plugins = archived_placeholder.plugins
        placeholder = page_placeholders.get(archived_placeholder.slot)
        if placeholder and plugins:
            import_plugins(plugins, placeholder, language)


@lru_cache()
def get_plugin_fields(plugin_type):
    klass = get_plugin_class(plugin_type)
    if klass.model is CMSPlugin:
        return []
    opts = klass.model._meta.concrete_model._meta
    fields = opts.local_fields + opts.local_many_to_many
    return [field.name for field in fields]


def get_placeholder_export_data(placeholder, language):
    from . import helpers
    get_data = helpers.get_plugin_data
    plugins = placeholder.get_plugins(language)
    # The following results in two queries;
    # First all the root plugins are fetched, then all child plugins.
    # This is needed to account for plugin path corruptions.

    return [get_data(plugin) for plugin in get_bound_plugins(list(plugins))]


def get_page_export_data(cms_page, language):
    data = []
    placeholders = cms_page.rescan_placeholders(language).values()

    for placeholder in list(placeholders):
        plugins = get_placeholder_export_data(placeholder, language)
        data.append({"placeholder": placeholder.slot, "plugins": plugins})
    return data


def _object_version_data_hook(data, for_page=False):
    from .datastructures import ArchivedPlaceholder, ArchivedPlugin
    if not data:
        return data

    if "plugins" in data:
        return ArchivedPlaceholder(
            slot=data["placeholder"],
            plugins=data["plugins"],
        )

    if "plugin_type" in data:
        return ArchivedPlugin(**data)
    return data


def create_page_content_translation(page_content, language):
    page = page_content.page
    try:
        print(page_content.created_by)
        user = User.objects.get(username=page_content.created_by)
    except User.DoesNotExist:
        # Just pick any admin user
        user = User.objects.filter(is_superuser=True).first()
    title_kwargs = {
        "page": page,
        "language": language,
        "title": page_content.title,
        "template": page_content.template,
        "created_by": user,
        "menu_title": page_content.menu_title,
        "page_title": page_content.page_title,
        "meta_description": page_content.meta_description,
    }

    return api.create_page_content(**title_kwargs)
