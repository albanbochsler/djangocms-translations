import json
from collections import OrderedDict
from functools import lru_cache
from itertools import chain

from cms import api
from cms.models import Page, CMSPlugin, Placeholder, PlaceholderRelationField
from cms.plugin_pool import plugin_pool
from cms.utils.plugins import get_bound_plugins
from django.apps import apps
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
from slugify import slugify
from yurl import URL

from .conf import TRANSLATIONS_CONF
from .conf import TRANSLATIONS_INLINE_CONF
from .exporter import get_placeholder_export_data

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
    try:
        placeholders = cms_page.rescan_placeholders(language).values()
    except AttributeError:
        return data

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



def get_app_export_data(obj, language):
    data = []
    placeholders = {}

    for field in obj._meta.get_fields():
        if type(field) == PlaceholderRelationField:
            for placeholder in getattr(obj, field.name).all():
                placeholders[placeholder.slot] = placeholder

    for placeholder_name, placeholder in placeholders.items():
        plugins = get_placeholder_export_data(placeholder, language)
        data.append({'placeholder': placeholder_name, 'plugins': plugins})

    return data


def get_app_export_fields(obj, app_label, language):
    data = []
    fields = {}

    inlines = get_app_inline_fields(obj, app_label, language)

    for field in obj._meta.get_fields():
        if field.auto_created or not field.editable or field.many_to_many:
            continue

    for field in obj.get_translation(language)._meta.get_fields():
        if not isinstance(getattr(obj.get_translation(language), field.name), str):
            continue

        if field.auto_created or not field.editable or field.many_to_many:
            continue
        fields[field.name] = getattr(obj.get_translation(language), field.name)

    if 'slug' in fields:
        fields.pop('slug')
    if 'language_code' in fields:
        fields.pop('language_code')
    if 'master' in fields:
        fields.pop('master')
    data.append({'fields': fields, 'inlines': inlines})

    return data


def get_app_inline_fields(obj, app_label, language):
    inline_fields = {}
    for key, value in TRANSLATIONS_INLINE_CONF.items():
        try:
            for field in getattr(obj, value["related_name"]).all():
                inline_fields.setdefault(field.pk, {})

                inline_fields[field.pk] = [{
                    object.name: getattr(field.get_translation(language), object.name)
                    for object in field.get_translation(language)._meta.get_fields() if
                    object.name != 'language_code' and object.name != 'master'
                }]
        except Exception as e:
            pass

    return inline_fields


def import_plugins_to_app(placeholders, obj, language):
    old_placeholders = {}

    for field in obj._meta.get_fields():
        if type(field) == PlaceholderRelationField:
            for placeholder in getattr(obj, field.name).all():
                old_placeholders[placeholder.slot] = placeholder

    for archived_placeholder in placeholders:
        plugins = archived_placeholder.plugins
        placeholder = old_placeholders[archived_placeholder.slot]
        if placeholder and plugins:
            import_plugins(plugins, placeholder, language)


def import_fields_to_app_model(return_fields, target_language):
    conf = TRANSLATIONS_INLINE_CONF.items()
    from djangocms_translations.models import AppTranslationRequestItem

    for item in return_fields:
        translation_request_item_pk = item["translation_request_item_pk"]
        link_object_id = item["link_object_id"]
        request_item = AppTranslationRequestItem.objects.get(pk=translation_request_item_pk)
        obj_model = apps.get_model(request_item.app_label, request_item.link_model)

        try:
            obj = obj_model.objects.get(id=request_item.link_object_id)
            if not obj.has_translation(target_language):
                obj.create_translation(target_language)
            field_name = item["field_name"]
            content = item["content"]
            # convert &amp; to & and &nbsp; to space in content
            content = content.replace('&amp;', '&').replace('&nbsp;', ' ')
            if conf:
                for key, value in TRANSLATIONS_INLINE_CONF.items():
                    try:
                        if not field_name in value["fields"]:
                            setattr(obj.get_translation(target_language), field_name, content)
                            if hasattr(obj, "slug") and field_name == obj.slug_source_field_name:
                                obj.get_translation(target_language).slug = slugify(content)
                            obj.get_translation(target_language).save()
                        else:
                            # save to inline model
                            inline_model = apps.get_model(request_item.app_label, key)
                            inline_obj = inline_model.objects.get(pk=item["link_object_id"])
                            if not inline_obj.has_translation(target_language):
                                inline_obj.create_translation(target_language)
                            setattr(inline_obj.get_translation(target_language), item["field_name"], content)
                            inline_obj.get_translation(target_language).save()
                    except Exception as e:
                        pass
            else:
                setattr(obj.get_translation(target_language), field_name, content)
                if hasattr(obj, "slug") and field_name == obj.slug_source_field_name:
                    obj.get_translation(target_language).slug = slugify(content)
                obj.get_translation(target_language).save()
        except Exception as e:
            print("Error: ", e)
            print("request_item: ", (request_item.app_label, request_item.link_model))
            continue


def import_fields_to_model(return_fields, language):
    title_conf = TRANSLATIONS_TITLE_EXTENSION
    title_extension_model = apps.get_model(title_conf["app_label"], title_conf["model_name"])
    for item in return_fields:
        link_object_id = item["link_object_id"]
        field_name = item["field_name"]
        content = item["content"]
        content = content.replace('&amp;', '&').replace('&nbsp;', ' ')
        title_extension = title_extension_model.objects.get(pk=link_object_id)
        if field_name == "title":
            extended_obj = title_extension.extended_object
            extended_obj.title = content
            extended_obj.slug = slugify(content)
            extended_obj.path = extended_obj.page.get_path_for_slug(slugify(content), language)
            extended_obj.save()
            extended_obj.page.save()
        for key, value in item.items():
            setattr(title_extension, field_name, content)
        title_extension.save()
