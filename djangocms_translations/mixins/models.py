import json
import logging

from cms.utils.copy_plugins import copy_plugins_to
from django import forms
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from djangocms_transfer.exporter import get_placeholder_export_data
from djangocms_transfer.importer import import_plugins
from extended_choices import Choices
from django.conf import settings
from django.utils import timezone

from django.db import models, IntegrityError
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField
from djangocms_transfer.utils import get_plugin_class, get_plugin_model

from allink_core.core.utils import get_model
from ..providers import TRANSLATION_PROVIDERS, SupertextTranslationProvider, GptTranslationProvider

__all__ = ['AppTranslationRequest']
logger = logging.getLogger('djangocms_translations')


def get_app_export_data(obj, language):
    data = []
    placeholders = {}
    # TODO also add fields

    for field in obj._meta.get_fields():
        if field.get_internal_type() == 'PlaceholderField':
            placeholders[field.name] = getattr(obj, field.name)

    for placeholder_name, placeholder in placeholders.items():
        plugins = get_placeholder_export_data(placeholder, language)
        data.append({'placeholder': placeholder_name, 'plugins': plugins})
        # data.append({'placeholder': placeholder.slot, 'plugins': plugins})

    return data


def import_plugins_to_app(placeholders, obj, language):
    old_placeholders = {}

    for field in obj._meta.get_fields():
        if field.get_internal_type() == 'PlaceholderField':
            old_placeholders[field.name] = getattr(obj, field.name)
    print("old_placeholders", old_placeholders, old_placeholders["header_placeholder"])

    for archived_placeholder in placeholders:
        plugins = archived_placeholder.plugins
        print("plugins", plugins)
        placeholder = old_placeholders[archived_placeholder.slot]
        # placeholder = old_placeholders.get(archived_placeholder.slot)
        print("placeholder", placeholder)
        if placeholder and plugins:
            import_plugins(plugins, placeholder, language)
            print("import_plugins(plugins, placeholder, language)")


class AppTranslationRequest(models.Model):
    STATES = Choices(
        ('DRAFT', 'draft', _('Draft')),
        ('OPEN', 'open', _('Open')),
        ('PENDING_QUOTE', 'pending_quote', _('Pending quote from provider')),
        ('PENDING_APPROVAL', 'pending_approval', _('Pending approval of quote')),
        ('READY_FOR_SUBMISSION', 'ready_for_submission', _('Pending submission to translation provider')),
        ('IN_TRANSLATION', 'in_translation', _('In translation')),
        ('IMPORT_STARTED', 'import_started', _('Import started')),
        ('IMPORT_FAILED', 'import_failed', _('Import failed')),
        ('IMPORTED', 'imported', _('Imported')),
        ('CANCELLED', 'cancelled', _('Cancelled')),
    )

    PROVIDERS = [
        (SupertextTranslationProvider.__name__, _('Supertext')),
        (GptTranslationProvider.__name__, _('GPT'))
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    state = models.CharField(choices=STATES, default=STATES.DRAFT, max_length=100)
    date_created = models.DateTimeField(auto_now_add=True)
    date_submitted = models.DateTimeField(blank=True, null=True)
    date_received = models.DateTimeField(blank=True, null=True)
    date_imported = models.DateTimeField(blank=True, null=True)
    source_language = models.CharField(max_length=10, choices=settings.LANGUAGES)
    target_language = models.CharField(max_length=10, choices=settings.LANGUAGES)
    provider_backend = models.CharField(max_length=100, choices=PROVIDERS)
    provider_order_name = models.CharField(max_length=255, blank=True)
    provider_options = JSONField(default=dict, blank=True)
    export_content = JSONField(default=dict, blank=True)
    request_content = JSONField(default=dict, blank=True)
    selected_quote = models.ForeignKey('AppTranslationQuote', blank=True, null=True, on_delete=models.CASCADE)

    class Meta:
        verbose_name = _('App Translation request')
        verbose_name_plural = _('App Translation requests')

    @property
    def status(self):
        return self.STATES.for_value(self.state).display

    @property
    def provider(self):
        if not self._provider and self.provider_backend:
            self._provider = TRANSLATION_PROVIDERS.get(self.provider_backend)(self)
        return self._provider

    _provider = None

    def set_provider_order_name(self, app_label):
        initial_page_title = app_label
        request_item_count = self.items.count()

        if request_item_count > 1:
            bulk_text = _(' - {} pages').format(request_item_count)
        else:
            bulk_text = ''
        self.provider_order_name = _('Order #{} - {}{}').format(self.pk, initial_page_title, bulk_text)
        self.save(update_fields=('provider_order_name',))

    def set_content_from_app(self):
        export_content = []

        for item in self.items.all():
            export_content.extend(item.get_export_data(self.source_language))

        self.export_content = json.dumps(export_content, cls=DjangoJSONEncoder)
        self.save(update_fields=('export_content',))
        self.set_status(self.STATES.OPEN)

    def set_status(self, status, commit=True):
        assert status in self.STATES.values, _('Invalid status')
        self.state = status

        if commit:
            self.save(update_fields=('state',))
        return not status == self.STATES.IMPORT_FAILED

    def submit_request(self):
        response = self.provider.send_request(is_app=True)
        self.set_status(self.STATES.IN_TRANSLATION)
        return response

    def get_quote_from_provider(self):
        self.set_status(self.STATES.PENDING_QUOTE)

        provider_quote = self.provider.get_quote()
        print("provider_quote", provider_quote)
        currency = provider_quote['Currency']
        date_received = timezone.now()
        quotes = []

        for option in provider_quote['Options']:
            order_type_id = option['OrderTypeId']
            name = '{} ({})'.format(option['Name'], option['ShortDescription'])
            description = option['Description']

            for delivery_option in option['DeliveryOptions']:
                quote = self.quotes.create(
                    provider_options={
                        'OrderTypeId': order_type_id,
                        'DeliveryId': delivery_option['DeliveryId'],
                    },
                    name=name,
                    description=description,
                    delivery_date=delivery_option['DeliveryDate'],
                    delivery_date_name=delivery_option['Name'],
                    price_currency=currency,
                    price_amount=delivery_option['Price'] or 0,
                    date_received=date_received,
                )
                quotes.append(quote)

        self.set_status(self.STATES.PENDING_APPROVAL)

    def import_response(self, raw_data):
        import_state = AppTranslationImport.objects.create(request=self)
        self.set_status(self.STATES.IMPORT_STARTED)
        self.order.response_content = raw_data
        self.order.save(update_fields=('response_content',))

        try:
            import_data = self.provider.get_import_data()
            print("import_data", import_data)
        except ValueError:
            message = _('Received invalid data from {}.').format(self.provider_backend)
            logger.exception(message)
            import_state.set_error_message(message)
            return self.set_status(self.STATES.IMPORT_FAILED)

        id_item_mapping = self.items.in_bulk()
        import_error = False
        for translation_request_item_pk, placeholders in import_data.items():
            translation_request_item = id_item_mapping[translation_request_item_pk]
            print("translation_request_item", translation_request_item, placeholders)
            app_label = translation_request_item.app_label
            model_label = translation_request_item.link_model
            link_object_id = translation_request_item.link_object_id
            obj_model = get_model(app_label, model_label)
            obj = obj_model.objects.get(id=link_object_id)

            try:
                import_plugins_to_app(
                    placeholders=placeholders,
                    obj=obj,
                    language=self.target_language
                )
            except (IntegrityError, ObjectDoesNotExist):
                # self._set_import_archive()
                message = _('Failed to import plugins from {}.').format(self.provider_backend)
                logger.exception(message)
                import_state.set_error_message(message)
                import_error = True

        if import_error:
            # FIXME: this or all-or-nothing (atomic)?
            return self.set_status(self.STATES.IMPORT_FAILED)

        self.set_status(self.STATES.IMPORTED, commit=False)
        self.date_imported = timezone.now()
        self.save(update_fields=('date_imported', 'state'))
        import_state.state = import_state.STATES.IMPORTED
        import_state.save(update_fields=('state',))
        return True


class AppTranslationOrder(models.Model):
    STATES = Choices(
        ('OPEN', 'open', _('Open')),
        ('PENDING', 'pending_quote', _('Pending')),
        ('FAILED', 'failed', _('Failed/cancelled')),
        ('DONE', 'done', _('Done')),
    )

    request = models.OneToOneField(AppTranslationRequest, related_name='order', on_delete=models.CASCADE)

    date_created = models.DateTimeField(auto_now_add=True)
    date_translated = models.DateTimeField(blank=True, null=True)

    state = models.CharField(choices=STATES, default=STATES.OPEN, max_length=100)

    request_content = JSONField(default=dict, blank=True)
    response_content = JSONField(default=dict, blank=True)

    provider_details = JSONField(default=dict, blank=True)

    @property
    def price_with_currency(self):
        price = self.provider_details.get(self.request.provider.PRICE_KEY)
        if not price:
            return '-'
        currency = self.provider_details.get(self.request.provider.CURRENCY_KEY)
        return '{} {}'.format(price, currency)


class AppTranslationRequestItem(models.Model):
    translation_request = models.ForeignKey(AppTranslationRequest, related_name='items', on_delete=models.CASCADE)
    app_label = models.CharField("App label", max_length=100)
    link_model = models.CharField("Link model", max_length=100)
    link_object_id = models.PositiveIntegerField("Link object id")

    def get_export_data(self, language):
        app_label = self.app_label
        model_label = self.link_model
        link_object_id = self.link_object_id
        obj_model = get_model(app_label, model_label)
        obj = obj_model.objects.get(id=link_object_id)
        print("request item", obj)

        data = get_app_export_data(obj, language)
        print("data", data)
        for d in data:
            d['translation_request_item_pk'] = self.pk
        return data


class AppTranslationQuote(models.Model):
    request = models.ForeignKey(AppTranslationRequest, related_name='quotes', on_delete=models.CASCADE)
    date_received = models.DateTimeField()

    name = models.CharField(max_length=1000)
    description = models.TextField(blank=True, default='')
    delivery_date = models.DateTimeField(blank=True, null=True)
    delivery_date_name = models.CharField(max_length=10, blank=True, null=True)

    price_currency = models.CharField(max_length=10)
    price_amount = models.DecimalField(max_digits=10, decimal_places=2)
    provider_options = JSONField(default=dict, blank=True)

    def __str__(self):
        return '{} {} {}'.format(self.name, self.description, self.price_amount)


class AppTranslationImport(models.Model):
    STATES = Choices(
        ('STARTED', 'started', _('Import started')),
        ('FAILED', 'failed', _('Import failed')),
        ('IMPORTED', 'imported', _('Imported')),
    )

    request = models.ForeignKey(AppTranslationRequest, on_delete=models.CASCADE, related_name='imports')
    date_created = models.DateTimeField(auto_now_add=True)
    message = models.CharField(max_length=1000, blank=True)
    state = models.CharField(choices=STATES, default=STATES.STARTED, max_length=100)

    def set_error_message(self, message):
        self.state = self.STATES.FAILED
        self.message = message
        self.save(update_fields=('state', 'message'))
