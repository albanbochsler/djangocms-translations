from __future__ import unicode_literals

import json
import logging

from cms.models import CMSPlugin, Placeholder, PageContent, EmptyPageContent
from cms.models.fields import PageField, PlaceholderField
from cms.utils.plugins import copy_plugins_to_placeholder
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from djangocms_text_ckeditor.fields import HTMLField
from djangocms_versioning.constants import PUBLISHED, DRAFT
from extended_choices import Choices
from slugify import slugify

from .conf import TRANSLATIONS_TITLE_EXTENSION, TRANSLATIONS_INLINE_CONF
from .providers import TRANSLATION_PROVIDERS, TRANSLATION_PROVIDER_CHOICES
from .utils import get_plugin_form, get_page_export_data, get_plugin_class, \
    import_plugins_to_content, create_page_content_translation, get_app_export_fields, get_app_export_data, \
    import_plugins_to_app, import_fields_to_model, import_fields_to_app_model

logger = logging.getLogger('djangocms_translations')


def _get_placeholder_slot(archived_placeholder):
    return archived_placeholder.slot


class BytesEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        return json.JSONEncoder.default(self, obj)


class TranslationRequest(models.Model):
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

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    state = models.CharField(choices=STATES, default=STATES.DRAFT, max_length=100)
    date_created = models.DateTimeField(auto_now_add=True)
    date_submitted = models.DateTimeField(blank=True, null=True)
    date_received = models.DateTimeField(blank=True, null=True)
    date_imported = models.DateTimeField(blank=True, null=True)
    source_language = models.CharField(max_length=10, choices=settings.LANGUAGES)
    target_language = models.CharField(max_length=10, choices=settings.LANGUAGES)
    provider_backend = models.CharField(max_length=100, choices=TRANSLATION_PROVIDER_CHOICES)
    provider_order_name = models.CharField(max_length=255, blank=True)
    provider_options = models.JSONField(default=dict, blank=True)
    export_content = models.JSONField(default=dict, blank=True)
    export_fields = models.JSONField(default=dict, blank=True)
    request_content = models.JSONField(default=dict, blank=True)
    selected_quote = models.ForeignKey('TranslationQuote', blank=True, null=True, on_delete=models.CASCADE)
    translate_content = models.BooleanField(default=True)
    translate_title = models.BooleanField(default=True)
    translate_seo = models.BooleanField(default=True)

    @property
    def status(self):
        return self.STATES.for_value(self.state).display

    @property
    def provider(self):
        if not self._provider and self.provider_backend:
            self._provider = TRANSLATION_PROVIDERS.get(self.provider_backend)(self)
        return self._provider

    _provider = None

    def set_status(self, status, commit=True):
        assert status in self.STATES.values, _('Invalid status')
        self.state = status

        if commit:
            self.save(update_fields=('state',))
        return not status == self.STATES.IMPORT_FAILED

    def set_provider_order_name(self, source_page):
        initial_page_title = source_page.get_page_title(self.source_language)
        request_item_count = self.items.count()

        if request_item_count > 1:
            bulk_text = _(' - {} pages').format(request_item_count)
        else:
            bulk_text = ''
        self.provider_order_name = _('Order #{} - {}{}').format(self.pk, initial_page_title, bulk_text)
        self.save(update_fields=('provider_order_name',))

    def set_content_from_cms(self, translate_content=True, translate_title=True, translate_seo=True):
        export_content = []
        export_fields = []

        for item in self.items.all():
            if translate_content:
                export_content.extend(item.get_export_data(self.source_language))
            if translate_title or translate_seo:
                export_fields.extend(item.get_export_fields(self.source_language, translate_title, translate_seo))

        self.export_content = json.dumps(export_content, cls=DjangoJSONEncoder)
        self.export_fields = json.dumps(export_fields, cls=DjangoJSONEncoder)
        self.save(update_fields=('export_content', 'export_fields'))
        self.set_status(self.STATES.OPEN)

    def set_provider_options(self, **kwargs):
        self.provider_options = self.provider.get_provider_options(**kwargs)
        self.save(update_fields=('provider_options',))

    def get_quote_from_provider(self):
        self.set_status(self.STATES.PENDING_QUOTE)

        provider_quote = self.provider.get_quote()
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

    def set_request_content(self):
        self.request_content = self.provider.get_export_data()
        self.save(update_fields=('request_content',))

    def submit_request(self):
        response = self.provider.send_request()
        self.set_status(self.STATES.IN_TRANSLATION)
        return response

    def check_status(self):
        assert hasattr(self, 'order'), _('Cannot check status if there is no order.')
        status = self.provider.check_status()
        self.order.state = status['Status'].lower()
        # TODO: which states are available?
        # on success, update the requests status as well
        self.order.save(update_fields=('state',))

    def get_new_version(self, page, source_language, target_language):
        from djangocms_versioning.models import Version

        # Try to get the published page contents or if not existing the drafts. object.filter automatically gets
        # only the draft objects.
        pagecontent_set = PageContent.objects.filter(page=page, language=target_language)
        if not pagecontent_set.exists():
            pagecontent_set = PageContent.admin_manager.filter(page=page, language=target_language)

        # If no page content exists. Create the first page content with first version.
        if not pagecontent_set.exists():
            page_content = page.pagecontent_set.filter(language=source_language).last()
            if page_content:
                # creates page content and automatically a version
                if not create_page_content_translation(page_content, target_language):
                    return None
            content = PageContent.admin_manager.get(page=page, language=target_language)
            version = Version.objects.get(
                content_type__model='pagecontent',
                object_id=content.id,
                state=DRAFT,
            )
        else:
            version = Version.objects.filter(
                content_type__model='pagecontent',
                object_id__in=pagecontent_set.values_list('id', flat=True),
            ).first()

        new_version = version.copy(version.created_by)
        content = new_version.content
        placeholders = Placeholder.objects.filter(
            object_id=content.id,
        )
        for placeholder in placeholders:
            placeholder.clear(target_language)

        return new_version

    def import_response(self, raw_data):
        import_state = TranslationImport.objects.create(request=self)
        self.set_status(self.STATES.IMPORT_STARTED)
        self.order.response_content = raw_data
        self.order.save(update_fields=('response_content',))

        try:
            import_data, return_fields = self.provider.get_import_data()
        except ValueError:
            message = _('Received invalid data from {}.').format(self.provider_backend)
            logger.exception(message)
            import_state.set_error_message(message)
            return self.set_status(self.STATES.IMPORT_FAILED)

        id_item_mapping = self.items.in_bulk()
        import_error = False

        for translation_request_item_pk, placeholders in import_data.items():
            translation_request_item = id_item_mapping[translation_request_item_pk]
            version = self.get_new_version(
                translation_request_item.target_cms_page, self.source_language, self.target_language
            )
            if not version:
                message = _("Page content couldn't be created")
                logger.exception(message)
                import_state.set_error_message(message)
                import_error = True

                break
            try:
                import_plugins_to_content(
                    placeholders=placeholders,
                    language=self.target_language,
                    content=version.content
                )
            except (IntegrityError, ObjectDoesNotExist):
                self._set_import_archive()
                message = _('Failed to import plugins from {}.').format(self.provider_backend)
                logger.exception(message)
                import_state.set_error_message(message)
                import_error = True

        if return_fields:
            import_fields_to_model(return_fields, self.target_language)

        if import_error:
            # FIXME: this or all-or-nothing (atomic)?
            return self.set_status(self.STATES.IMPORT_FAILED)

        self.set_status(self.STATES.IMPORTED, commit=False)
        self.date_imported = timezone.now()
        self.save(update_fields=('date_imported', 'state'))
        import_state.state = import_state.STATES.IMPORTED
        import_state.save(update_fields=('state',))
        return True

    def can_import_from_archive(self):
        if self.state == self.STATES.IMPORT_FAILED:
            return self.archived_placeholders.exists()
        return False

    @transaction.atomic
    def _import_from_archive(self):
        plugins_by_placeholder = {
            pl.slot: pl.get_plugins()
            for pl in self.archived_placeholders.all()
        }
        for translation_request_item in self.items.select_related('target_cms_page'):
            page_placeholders = (
                translation_request_item
                .target_cms_page
                .placeholders
                .filter(slot__in=plugins_by_placeholder)
            )

            for placeholder in page_placeholders:
                plugins = plugins_by_placeholder[placeholder.slot]
                copy_plugins_to_placeholder(
                    plugins=plugins,
                    placeholder=placeholder,
                    language=self.target_language,
                )

        self.set_status(self.STATES.IMPORTED, commit=False)
        self.date_imported = timezone.now()
        self.save(update_fields=('date_imported', 'state'))

    @transaction.atomic
    def _set_import_archive(self):
        import_data, return_fields = self.provider.get_import_data()
        id_item_mapping = self.items.in_bulk()

        for translation_request_item_pk, placeholders in import_data:
            translation_request_item = id_item_mapping[translation_request_item_pk]
            page_placeholders = translation_request_item.source_cms_page.get_declared_placeholders()

            plugins_by_placeholder = {
                pl.slot: pl.plugins
                for pl in placeholders if pl.plugins
            }

            for pos, placeholder in enumerate(page_placeholders, start=1):
                if placeholder.slot not in plugins_by_placeholder:
                    continue

                plugins = plugins_by_placeholder[placeholder.slot]
                bound_plugins = (plugin for plugin in plugins if plugin.data)
                ar_placeholder = (
                    self
                    .archived_placeholders
                    .create(slot=placeholder.slot, position=pos)
                )

                try:
                    ar_placeholder._import_plugins(bound_plugins)
                except (IntegrityError, ObjectDoesNotExist):
                    return False

    def clean(self, exclude=None):
        if self.source_language == self.target_language:
            raise ValidationError(_('Source and target languages must be different.'))

        return super(TranslationRequest, self).clean()


def get_page_export_fields(page, language, translate_title, translate_seo):
    data = []
    fields = {}
    title_obj = page.get_content_obj(language)
    title_conf = TRANSLATIONS_TITLE_EXTENSION
    try:
        title_ext = getattr(title_obj, title_conf["model_name"])
        for field in title_ext._meta.get_fields():
            if field.auto_created or not field.editable or field.many_to_many:
                continue
            fields[field.name] = getattr(title_ext, field.name)
    except Exception as e:
        pass

    if translate_seo and translate_title:
        data.append({'fields': fields, 'inlines': [], 'cms_title': {'title': title_obj.title}})
    elif translate_seo:
        data.append({'fields': fields, 'inlines': [], 'cms_title': {}})
    elif translate_title:
        data.append({'fields': {}, 'inlines': [], 'cms_title': {'title': title_obj.title}})

    return data


class TranslationRequestItem(models.Model):
    translation_request = models.ForeignKey(TranslationRequest, related_name='items', on_delete=models.CASCADE)
    source_cms_page = PageField(related_name='translation_requests_as_source', on_delete=models.PROTECT)
    target_cms_page = PageField(related_name='translation_requests_as_target', on_delete=models.PROTECT)

    @cached_property
    def source_cms_page_title(self):
        return self.source_cms_page.get_title(self.translation_request.source_language)

    def clean(self, exclude=None):
        page_languages = self.source_cms_page.get_languages()
        if self.translation_request.source_language not in page_languages:
            raise ValidationError({
                'source_cms_page':
                    _('Invalid choice. Page must contain {} translation.').format(
                        self.translation_request.source_language)
            })
        # Validation if page content does not exists is not needed anymore
        # page_languages = self.target_cms_page.get_languages()
        # if self.translation_request.target_language not in page_languages:
        #     raise ValidationError({
        #         'target_cms_page':
        #             _('Invalid choice. Page must contain {} translation.').format(
        #                 self.translation_request.target_language)
        #     })

        return super(TranslationRequestItem, self).clean()

    def get_export_data(self, language):
        data = get_page_export_data(self.source_cms_page, language)
        for d in data:
            d['translation_request_item_pk'] = self.pk
        return data

    def get_export_fields(self, language, translate_title, translate_seo):
        data = get_page_export_fields(self.source_cms_page, language, translate_title, translate_seo)
        target_lang = self.translation_request.target_language
        title = self.source_cms_page.get_content_obj(target_lang)
        title_conf = TRANSLATIONS_TITLE_EXTENSION
        title_extension_model = apps.get_model(title_conf["app_label"], title_conf["model_name"])
        if not isinstance(title, EmptyPageContent):
            title_extension = title_extension_model.objects.get_or_create(extended_object_id=title.pk)
            for d in data:
                d['translation_request_item_pk'] = self.pk
                d['pk'] = title_extension[0].pk
                d['title_pk'] = title.pk
        return data


class TranslationQuote(models.Model):
    request = models.ForeignKey(TranslationRequest, related_name='quotes', on_delete=models.CASCADE)
    date_received = models.DateTimeField()

    name = models.CharField(max_length=1000)
    description = models.TextField(blank=True, default='')
    delivery_date = models.DateTimeField(blank=True, null=True)
    delivery_date_name = models.CharField(max_length=10, blank=True, null=True)

    price_currency = models.CharField(max_length=10)
    price_amount = models.DecimalField(max_digits=10, decimal_places=2)
    provider_options = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return '{} {} {}'.format(self.name, self.description, self.price_amount)


class TranslationOrder(models.Model):
    STATES = Choices(
        ('OPEN', 'open', _('Open')),
        ('PENDING', 'pending_quote', _('Pending')),
        ('FAILED', 'failed', _('Failed/cancelled')),
        ('DONE', 'done', _('Done')),
    )

    request = models.OneToOneField(TranslationRequest, related_name='order', on_delete=models.CASCADE)

    date_created = models.DateTimeField(auto_now_add=True)
    date_translated = models.DateTimeField(blank=True, null=True)

    state = models.CharField(choices=STATES, default=STATES.OPEN, max_length=100)

    request_content = models.JSONField(default=dict, blank=True)
    response_content = models.JSONField(default=dict, blank=True)

    provider_details = models.JSONField(default=dict, blank=True)

    @property
    def price_with_currency(self):
        price = self.provider_details.get(self.request.provider.PRICE_KEY)
        if not price:
            return '-'
        currency = self.provider_details.get(self.request.provider.CURRENCY_KEY)
        return '{} {}'.format(price, currency)


class ArchivedPlaceholder(models.Model):
    slot = models.CharField(max_length=255)
    request = models.ForeignKey(
        TranslationRequest,
        on_delete=models.CASCADE,
        related_name='archived_placeholders',
    )
    placeholder = PlaceholderField(
        _get_placeholder_slot,
        related_name='archived_placeholders',
    )
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ('position',)
        default_permissions = ''

    def get_plugins(self):
        return self.placeholder.get_plugins()

    def _import_plugins(self, plugins):
        source_map = {}
        new_plugins = []

        for archived_plugin in plugins:
            if archived_plugin.parent_id:
                parent = source_map[archived_plugin.parent_id]
            else:
                parent = None

            if parent and parent.__class__ != CMSPlugin:
                parent = parent.cmsplugin_ptr

            plugin_form = get_plugin_form(
                archived_plugin.plugin_type,
                data=archived_plugin.data,
            )
            data_is_valid = plugin_form.is_valid()

            plugin = archived_plugin.restore(
                placeholder=self.placeholder,
                language=self.request.target_language,
                parent=parent,
                with_data=data_is_valid,
            )

            if data_is_valid:
                new_plugins.append(plugin)
            else:
                self.archived_plugins.create(
                    data=archived_plugin.data,
                    cms_plugin=plugin,
                    old_plugin_id=archived_plugin.pk,
                )
            source_map[archived_plugin.pk] = plugin

        for new_plugin in new_plugins:
            plugin_class = get_plugin_class(new_plugin.plugin_type)

            if getattr(plugin_class, '_has_do_post_copy', False):
                # getattr is used for django CMS 3.4 compatibility
                # apps on 3.4 wishing to leverage this callback will need
                # to manually set the _has_do_post_copy attribute.
                plugin_class.do_post_copy(new_plugin, source_map)


class ArchivedPlugin(models.Model):
    data = models.JSONField(default=dict, blank=True)
    placeholder = models.ForeignKey(
        ArchivedPlaceholder,
        on_delete=models.CASCADE,
        related_name='archived_plugins',
    )
    cms_plugin = models.OneToOneField(
        CMSPlugin,
        on_delete=models.CASCADE,
        related_name='trans_archived_plugin',
    )
    old_plugin_id = models.IntegerField()

    class Meta:
        default_permissions = ''


class TranslationImport(models.Model):
    STATES = Choices(
        ('STARTED', 'started', _('Import started')),
        ('FAILED', 'failed', _('Import failed')),
        ('IMPORTED', 'imported', _('Imported')),
    )

    request = models.ForeignKey(TranslationRequest, on_delete=models.CASCADE, related_name='imports')
    date_created = models.DateTimeField(auto_now_add=True)
    message = models.CharField(max_length=1000, blank=True)
    state = models.CharField(choices=STATES, default=STATES.STARTED, max_length=100)

    def set_error_message(self, message):
        self.state = self.STATES.FAILED
        self.message = message
        self.save(update_fields=('state', 'message'))


class TranslationDirective(models.Model):
    title = models.CharField(max_length=255)
    master_language = models.CharField(
        _("master language"),
        max_length=10,
        # choices=settings.LANGUAGES,
        # default=settings.LANGUAGES[0][0],
    )

    class Meta:
        verbose_name = "translation directive"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # add TranslationDirectiveInline for each language, starting with master language
        super().save(*args, **kwargs)
        for language, _ in settings.LANGUAGES:
            if language == self.master_language:
                TranslationDirectiveInline.objects.get_or_create(
                    title="{} - {}".format(self.title, language),
                    master=self,
                    language=language
                )
            else:
                TranslationDirectiveInline.objects.get_or_create(
                    title="{} - {}".format(self.title, language),
                    master=self,
                    language=language
                )


class TranslationDirectiveInline(models.Model):
    title = models.CharField(max_length=255, editable=False, null=True)
    master = models.ForeignKey(
        TranslationDirective,
        on_delete=models.CASCADE,
        related_name='translations',
        null=True
    )
    language = models.CharField(
        _("language"),
        max_length=10,
        editable=False,
        # choices=settings.LANGUAGES,
        # default=settings.LANGUAGES[0][0],
    )
    directive_item = HTMLField("directive item", blank=True, null=True)

    def __str__(self):
        return self.title if self.title else self.master.title

    class Meta:
        ordering = ['master__master_language']


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

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    state = models.CharField(choices=STATES, default=STATES.DRAFT, max_length=100)
    date_created = models.DateTimeField(auto_now_add=True)
    date_submitted = models.DateTimeField(blank=True, null=True)
    date_received = models.DateTimeField(blank=True, null=True)
    date_imported = models.DateTimeField(blank=True, null=True)
    source_language = models.CharField(max_length=10, choices=settings.LANGUAGES)
    target_language = models.CharField(max_length=10, choices=settings.LANGUAGES)
    provider_backend = models.CharField(max_length=100, choices=TRANSLATION_PROVIDER_CHOICES)
    provider_order_name = models.CharField(max_length=255, blank=True)
    provider_options = models.JSONField(default=dict, blank=True)
    export_content = models.JSONField(default=dict, blank=True)
    export_fields = models.JSONField(default=dict, blank=True)
    request_content = models.JSONField(default=dict, blank=True)
    request_fields = models.JSONField(default=dict, blank=True)
    selected_quote = models.ForeignKey('AppTranslationQuote', blank=True, null=True, on_delete=models.CASCADE)

    class Meta:
        verbose_name = _('App Translation request')
        verbose_name_plural = _('App Translation requests')

    @property
    def status(self):
        return self.STATES.for_value(self.state).display

    def get_app_from_export_content(self):
        try:
            content = json.loads(self.export_fields)
            return content[0]['app_label']
        except Exception as e:
            return None

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
            bulk_text = _(' - {} objects').format(request_item_count)
        else:
            bulk_text = ''
        self.provider_order_name = _('Order #{} - {}{}').format(self.pk, initial_page_title, bulk_text)
        self.save(update_fields=('provider_order_name',))

    def set_content_from_app(self):
        export_content = []
        export_fields = []

        for item in self.items.all():
            export_content.extend(item.get_export_data(self.source_language))
            export_fields.extend(item.get_export_fields(self.source_language))

        self.export_content = json.dumps(export_content, cls=DjangoJSONEncoder)
        self.export_fields = json.dumps(export_fields, cls=DjangoJSONEncoder)
        self.save(update_fields=('export_content', 'export_fields'))
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
            import_data, return_fields = self.provider.get_import_data()
        except ValueError:
            message = _('Received invalid data from {}.').format(self.provider_backend)
            logger.exception(message)
            import_state.set_error_message(message)
            return self.set_status(self.STATES.IMPORT_FAILED)

        id_item_mapping = self.items.in_bulk()
        import_error = False

        if return_fields:
            import_fields_to_app_model(return_fields, self.target_language)

        for translation_request_item_pk, placeholders in import_data.items():
            translation_request_item = id_item_mapping[translation_request_item_pk]
            app_label = translation_request_item.app_label
            model_label = translation_request_item.link_model
            link_object_id = translation_request_item.link_object_id
            obj_model = apps.get_model(app_label, model_label)
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

    request_content = models.JSONField(default=dict, blank=True)
    response_content = models.JSONField(default=dict, blank=True)

    provider_details = models.JSONField(default=dict, blank=True)

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
        obj_model = apps.get_model(app_label, model_label)
        obj = obj_model.objects.get(id=link_object_id)

        data = get_app_export_data(obj, language)
        for d in data:
            d['translation_request_item_pk'] = self.pk

        return data

    def get_export_fields(self, language):
        app_label = self.app_label
        model_label = self.link_model
        link_object_id = self.link_object_id
        obj_model = apps.get_model(app_label, model_label)
        obj = obj_model.objects.get(id=link_object_id)
        data = get_app_export_fields(obj, app_label, language)
        for d in data:
            d['translation_request_item_pk'] = self.pk
            d['app_label'] = self.app_label
            d['pk'] = self.link_object_id
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
    provider_options = models.JSONField(default=dict, blank=True)

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
