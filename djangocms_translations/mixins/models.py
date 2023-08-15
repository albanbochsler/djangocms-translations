from django import forms
from django.core.serializers.json import DjangoJSONEncoder
from djangocms_transfer.exporter import get_placeholder_export_data
from extended_choices import Choices
from django.conf import settings
import json
from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField
from djangocms_transfer.utils import get_plugin_class, get_plugin_model

from allink_core.core.utils import get_model
from ..providers import TRANSLATION_PROVIDERS, SupertextTranslationProvider, GptTranslationProvider

__all__ = ['AppTranslationRequest']


def get_app_export_data(obj, language):
    data = []
    placeholders = {}
    # TODO also add fields

    for field in obj._meta.get_fields():
        if field.get_internal_type() == 'PlaceholderField':
            placeholders[field.name] = getattr(obj, field.name)

    for placeholder_name, placeholder in placeholders.items():
        plugins = get_placeholder_export_data(placeholder, language)
        data.append({'placeholder': placeholder.slot, 'plugins': plugins})
    return data


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
    selected_quote = models.ForeignKey('TranslationQuote', blank=True, null=True, on_delete=models.CASCADE)

    class Meta:
        verbose_name = _('App Translation request')
        verbose_name_plural = _('App Translation requests')

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
