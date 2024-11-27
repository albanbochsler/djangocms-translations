import json
from collections import OrderedDict, defaultdict

import requests
from django.conf import settings
from django.contrib.sites.models import Site
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from djangocms_text_ckeditor.utils import plugin_to_tag, _plugin_tags_to_html, plugin_tags_to_id_list
from extended_choices import Choices
from yurl import URL

from .base import BaseTranslationProvider, ProviderException
from .. import __version__ as djangocms_translations_version
from ..conf import TRANSLATIONS_USE_STAGING, LANGUAGE_MAPPING
from ..utils import get_plugin_class, _object_version_data_hook
from ..utils import (
    get_text_field_child_label, get_translatable_fields,
)


#TODO: Hardcoded url, is this still needed?
def add_domain(url, domain=None):
    # add the domain to this url.
    if domain is None:
        domain = Site.objects.get_current().domain

    url = URL(url)
    if not settings.DEBUG:
        url = url.replace(scheme='https')
        return str(url.replace(host=domain))
    else:
        if TRANSLATIONS_USE_STAGING:
            localhost_url = f'http://host.docker.internal:8000{url}'
        else:
            localhost_url = f'http://localhost:8000{url}'
        return localhost_url


def export_content(field, plugin_data):
    def _render_plugin_with_content(obj, match):
        field = get_text_field_child_label(obj.plugin_type)
        content = getattr(obj, field) if field else ''
        return plugin_to_tag(obj, content)

    content = _plugin_tags_to_html(plugin_data[field], output_func=_render_plugin_with_content)
    subplugins_within_this_content = plugin_tags_to_id_list(content)
    return content, subplugins_within_this_content


def _get_translation_export_content(field, raw_plugin):
    plugin_class = get_plugin_class(raw_plugin['plugin_type'])
    try:
        result = plugin_class.export_content(field, raw_plugin['data'])
    except AttributeError:
        result = (raw_plugin['data'][field], [])
    return result


def _set_translation_import_content(enriched_content, plugin):
    plugin_class = get_plugin_class(plugin['plugin_type'])
    try:
        result = plugin_class.set_translation_import_content(enriched_content, plugin['data'])
    except AttributeError:
        result = {}
    return result


class DeeplException(ProviderException):
    pass


class DeeplProvider(BaseTranslationProvider):
    API_LIVE_URL = 'https://ai-utils-allink.us.aldryn.io'
    API_STAGE_URL = 'http://host.docker.internal:8001'
    ORDER_TYPE_CHOICES = Choices(
        ('TRANSLATION', 6, _('Translation')),
        ('SPECIALIST_TRANSLATION', 8, _('Specialist translation')),
        ('TRANSCREATION', 9, _('Transcreation')),
    )
    DELIVERY_TIME_CHOICES = Choices(
        ('EXPRESS', 1, _('Express (6h)')),
        ('24H', 2, _('24 hours')),
        ('48H', 3, _('48 hours')),
        ('3D', 4, _('3 days')),
        ('1W', 5, _('1 week')),
    )
    CURRENCY_KEY = 'Currency'
    PRICE_KEY = 'Price'
    has_quote_selection = False

    def get_headers(self):
        return {
            'Content-type': 'application/json; charset=UTF-8',
            'Accept': 'application/json',
        }

    def make_request(self, method, section, **kwargs):
        response = requests.request(
            method=method,
            url=self.get_url(section),
            headers=self.get_headers(),
            **kwargs
        )

        if not response.ok:
            raise DeeplException(response.text)
        return response

    def get_export_data(self):
        from ..models import TranslationDirective

        directives_dict = {}
        for directive in TranslationDirective.objects.all():
            directives_dict.setdefault(directive.pk, {})
            directives_dict[directive.pk]['masterLanguage'] = LANGUAGE_MAPPING.get(directive.master_language)
            for translation in directive.translations.all():
                directives_dict[directive.pk][LANGUAGE_MAPPING.get(translation.language)] = {
                    'directive_item': translation.directive_item,
                }

        x_data = {
            'ContentType': 'text/html',
            'SourceLang': LANGUAGE_MAPPING.get(self.request.source_language, self.request.source_language),
            'TargetLanguages': [LANGUAGE_MAPPING.get(self.request.target_language, self.request.target_language)],
            "Currency": "CHF",
            "Directives": directives_dict,
        }
        groups = []
        fields_by_plugin = {}

        for placeholder in json.loads(self.request.export_content):
            subplugins_already_processed = set()

            for raw_plugin in placeholder['plugins']:
                plugin_type = raw_plugin['plugin_type']
                if raw_plugin['pk'] in subplugins_already_processed:
                    continue

                if plugin_type not in fields_by_plugin:
                    fields_by_plugin[plugin_type] = get_translatable_fields(plugin_type)

                items = []
                for field in fields_by_plugin[plugin_type]:
                    content, children_included_in_this_content = _get_translation_export_content(field, raw_plugin)
                    subplugins_already_processed.update(children_included_in_this_content)
                    if content and not field == "_width_alias":
                        items.append({
                            'Id': field,
                            'Content': content,
                        })

                if items:
                    groups.append({
                        'GroupId': '{}:{}:{}'.format(
                            placeholder['translation_request_item_pk'], placeholder['placeholder'], raw_plugin['pk']
                        ),
                        'Items': items
                    })

        x_data['Groups'] = groups
        try:
            if self.request.export_fields:
                _fields = []
                for fields in json.loads(self.request.export_fields):
                    for key, value in fields['fields'].items():

                        items = []
                        if value:
                            items.append({
                                'Id': "field",
                                'Content': value,
                            })
                        if items:
                            _fields.append({
                                'GroupId': '{}:{}:{}'.format(
                                    fields['translation_request_item_pk'],
                                    key, fields['pk']
                                ),
                                'Items': items
                            })
                x_data['Groups'] += _fields
        except Exception as e:
            pass
        try:
            if self.request.export_fields:
                _fields = []
                for fields in json.loads(self.request.export_fields):
                    for k, v in fields['inlines'].items():
                        for value in v:
                            value_without_id = dict(
                                value)  # Make a copy of value to avoid modifying the original dictionary
                            id_value = value_without_id.pop(
                                'id')  # Remove 'id' from the copied dictionary and store its value
                            items = []
                            for key, item in value_without_id.items():  # Use the copied dictionary without 'id'
                                if item:
                                    items.append({
                                        'Id': "field",
                                        'Content': item,
                                    })
                                if items:
                                    _fields += [{
                                        'GroupId': '{}:{}:{}'.format(
                                            fields['translation_request_item_pk'],
                                            key, k  # Use stored 'id' value here
                                        ),
                                        'Items': items
                                    }]
                                    items = []
                x_data['Groups'] += _fields
        except Exception as e:
            pass

        try:
            if self.request.export_fields:
                _fields = []
                for fields in json.loads(self.request.export_fields):
                    for k, v in fields['cms_title'].items():
                        items = []
                        if v:
                            items.append({
                                'Id': "field",
                                'Content': v,
                            })
                        if items:
                            _fields.append({
                                'GroupId': '{}:{}:{}'.format(
                                    fields['translation_request_item_pk'],
                                    k, fields['pk']
                                ),
                                'Items': items
                            })
                x_data['Groups'] += _fields
        except Exception as e:
            pass

        return x_data

    def get_import_data(self):
        request = self.request
        export_content = json.loads(request.export_content)
        import_content = request.order.response_content
        subplugins_already_processed = set()
        _fields = []
        # TLRD: data is like {translation_request_item_pk: {placeholder_name: {plugin_pk: plugin_dict}}}
        data = defaultdict(dict)
        for x in export_content:
            translation_request_item_pk = x['translation_request_item_pk']
            plugin_dict = OrderedDict((plugin['pk'], plugin) for plugin in x['plugins'])
            data[translation_request_item_pk][x['placeholder']] = plugin_dict

        for group in import_content['Groups']:
            translation_request_item_pk, placeholder, plugin_id = group['GroupId'].split(':')
            translation_request_item_pk = int(translation_request_item_pk)
            plugin_id = int(plugin_id)
            # if plugin_id in subplugins_already_processed:
            #     continue

            for item in group['Items']:
                if not item['Id'] == 'field':
                    plugin_dict = data[translation_request_item_pk][placeholder]
                    plugin = plugin_dict[plugin_id]
                    plugin['data'][item['Id']] = item['Content'].replace('&amp;', '&').replace('&nbsp;', ' ')
                    subplugins = _set_translation_import_content(item['Content'], plugin)
                    subplugins_already_processed.update(list(subplugins.keys()))
                    for subplugin_id, subplugin_content in subplugins.items():
                        try:
                            field = get_text_field_child_label(plugin_dict[subplugin_id]['plugin_type'])
                            if field:
                                plugin_dict[subplugin_id]['data'][field] = subplugin_content
                        except KeyError as e:
                            pass
                else:
                    _fields.append({
                        "translation_request_item_pk": translation_request_item_pk,
                        "link_object_id": plugin_id,
                        "field_name": placeholder,
                        "content": item['Content'].replace('&amp;', '&').replace('&nbsp;', ' ')
                    })

        # TLRD: return_data is like {translation_request_item_pk: [<djangocms_transfer.ArchivedPlaceholder>, ]}
        return_data = {}
        return_fields = _fields
        for translation_request_item_pk, placeholders_dict in data.items():
            data = json.dumps([{
                'placeholder': p,
                'plugins': list(plugins.values()),
            } for p, plugins in placeholders_dict.items()])
            archived_placeholders = json.loads(data, object_hook=_object_version_data_hook)
            return_data[translation_request_item_pk] = archived_placeholders

        return return_data, return_fields

    def save_export_data(self):
        self.request.request_content = self.get_export_data()
        self.request.save(update_fields=('request_content',))

    def get_quote(self):
        self.request.request_content = self.get_export_data()
        self.request.save(update_fields=('request_content',))
        response = self.make_request(
            method='post',
            section='/quote',
            json=self.request.request_content,
        )

        return response.json()

    def get_translation_from_gpt(self, order):
        data = order

        response = self.make_request(
            method='post',
            section='/order',
            json=data,
        )

        return response

    def send_request(self, is_app=False):
        from ..models import TranslationOrder, AppTranslationOrder

        request = self.request
        if is_app:
            callback_url = add_domain(
                reverse('admin:app-translation-request-provider-callback', kwargs={'pk': request.pk}))
        else:
            callback_url = add_domain(reverse('admin:translation-request-provider-callback', kwargs={'pk': request.pk}))

        data = self.request.request_content
        data.update({
            'OrderName': request.provider_order_name,
            'ReferenceData': request.pk,  # TODO: we should add a secret token here and then recheck when importing.
            'ComponentName': 'djangocms-translations',
            'Provider': 'deepl',
            'ComponentVersion': djangocms_translations_version,
            'CallbackUrl': callback_url,
        })

        data.update(request.provider_options)
        if request.selected_quote:
            data.update(request.selected_quote.provider_options)

        if is_app:
            order, created = AppTranslationOrder.objects.get_or_create(
                request=request,
                defaults={'request_content': data}
            )
        else:
            order, created = TranslationOrder.objects.get_or_create(
                request=request,
                defaults={'request_content': data}
            )

        response = self.get_translation_from_gpt(order.request_content)
        order.provider_details = response.json()
        order.save(update_fields=('provider_details',))
        return response

    def check_status(self):
        order = self.request.order
        response = self.make_request(
            method='get',
            section='v1/translation/order/{}'.format(order.provider_details['Id']),
            json=order.request_content,
        )
        return response.json()

    def get_order_type_choices(self):
        return self.ORDER_TYPE_CHOICES

    def get_delivery_time_choices(self):
        return self.DELIVERY_TIME_CHOICES

    def get_provider_options(self, **kwargs):
        option_map = {
            'order_type': 'OrderTypeId',
            'delivery_time': 'DeliveryId',
            'additional_info': 'AdditionalInformation',
        }
        return {
            v: kwargs[k]
            for k, v in option_map.items()
            if kwargs.get(k) is not None
        }
