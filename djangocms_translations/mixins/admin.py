import json

from django import forms
from django.contrib.admin import ModelAdmin
from django.db.models import ManyToOneRel
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.contrib import admin
from djangocms_translations.utils import pretty_json

from django.forms import widgets
from django.conf import settings

from . import models, views

__all__ = [
    'TranslateAppMixin',
]


from .models import AppTranslationRequest, AppTranslationRequestItem, TranslationDirective, TranslationDirectiveInline


class AllReadOnlyFieldsMixin(object):
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return [
            field.name for field in self.model._meta.get_fields()
            if not isinstance(field, ManyToOneRel)
        ] + list(self.readonly_fields)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return True


class AppTranslationRequestItemInline(AllReadOnlyFieldsMixin, admin.TabularInline):
    model = models.AppTranslationRequestItem
    extra = 0
    classes = ['collapse']


class AppTranslationQuoteInline(AllReadOnlyFieldsMixin, admin.TabularInline):
    model = models.AppTranslationQuote
    extra = 0
    classes = ['collapse']


class AppTranslationOrderInline(AllReadOnlyFieldsMixin, admin.StackedInline):
    model = models.AppTranslationOrder
    extra = 0
    classes = ['collapse']

    fields = (
        'provider_order_id',
        (
            'date_created',
            'date_translated',
        ),
        'state',
        'pretty_provider_options',
        'pretty_request_content',
        'pretty_response_content',
        'price',
    )

    readonly_fields = (
        'provider_order_id',
        'pretty_provider_options',
        'pretty_request_content',
        'pretty_response_content',
        'price',
    )

    def provider_order_id(self, obj):
        return obj.provider_details.get('Id') or obj.response_content.get('Id')

    provider_order_id.short_description = _('Provider order ID')

    def pretty_provider_options(self, obj):
        return pretty_json(json.dumps(obj.provider_options))

    pretty_provider_options.short_description = _('Provider options')

    def pretty_request_content(self, obj):
        return pretty_json(json.dumps(obj.request_content))

    pretty_request_content.short_description = _('Request content')

    def pretty_response_content(self, obj):
        if isinstance(obj.response_content, dict):
            data = json.dumps(obj.response_content)
        else:
            data = obj.response_content
        return pretty_json(data)

    pretty_response_content.short_description = _('Response content')

    def price(self, obj):
        return obj.price_with_currency

    price.short_description = _('Price')


class TranslationDirectiveAdminInlineForm(forms.ModelForm):
    class Meta:
        model = TranslationDirectiveInline
        fields = '__all__'
        # widgets = {
        #     'directive_item': widgets.Textarea(attrs={'rows': 4, 'cols': 40}),
        # }

    def __init__(self, *args, **kwargs):
        super(TranslationDirectiveAdminInlineForm, self).__init__(*args, **kwargs)
        self.fields['language'] = forms.CharField(
            label='language',
            widget=forms.Select(choices=settings.LANGUAGES),
            required=False,
        )


class TranslationDirectiveAdminForm(forms.ModelForm):
    class Meta:
        model = TranslationDirective
        fields = '__all__'
        # widgets = {
        #     'directive_item': widgets.Textarea(attrs={'rows': 4, 'cols': 40}),
        # }

    def __init__(self, *args, **kwargs):
        super(TranslationDirectiveAdminForm, self).__init__(*args, **kwargs)
        self.fields['master_language'] = forms.CharField(
            label='master language',
            widget=forms.Select(choices=settings.LANGUAGES),
            required=False,
        )


class TranslationDirectiveAdminInline(admin.TabularInline):
    model = TranslationDirectiveInline
    extra = 0
    classes = ['collapse']
    form = TranslationDirectiveAdminInlineForm
    can_delete = False
    max_num = len(settings.LANGUAGES)


class TranslateAppBulkMixin(ModelAdmin):
    """
    ModelAdmin mixin used to add bulk translation of objects
    """

    def __init__(self, *args, **kwargs):
        super(TranslateAppBulkMixin, self).__init__(*args, **kwargs)

    def get_actions(self, request):
        actions = super(TranslateAppBulkMixin, self).get_actions(request)
        languages = getattr(settings, 'LANGUAGES', [])
        for lang_code, lang_name in languages:
            if lang_code == 'de':
                continue
            action_name = f"translate_in_bulk_{lang_code}"
            actions[action_name] = (
                self.make_translate_in_bulk_action(lang_code, lang_name),
                action_name,
                f"Translate to {lang_name}",

            )
        return actions

    def make_translate_in_bulk_action(self, lang_code, lang_name):

        def translate_in_bulk(modeladmin, request, queryset):
            """
            Action to translate the selected objects in bulk
            """
            app_label = self.model._meta.app_label
            model_name = self.model._meta.model_name
            user = request.user
            source_lang = request.GET.get('source_language', 'de')
            target_lang = lang_code
            provider_backend = request.GET.get('provider_backend', 'GptTranslationProvider')

            if request.method == 'POST':
                translation_request = AppTranslationRequest.objects.create(
                    user=user,
                    source_language=source_lang,
                    target_language=target_lang,
                    provider_backend=provider_backend,
                )
                translation_request_items = [
                    models.AppTranslationRequestItem(
                        translation_request=translation_request,
                        link_object_id=obj.pk,
                        app_label=app_label,
                        link_model=model_name,
                    )
                    for obj in queryset
                ]
                models.AppTranslationRequestItem.objects.bulk_create(translation_request_items)
                translation_request.set_provider_order_name(app_label)
                translation_request.set_content_from_app()
                translation_request.get_quote_from_provider()
                return redirect('admin:djangocms_translations_apptranslationrequest_changelist')

        def action_wrapper(modeladmin, request, queryset):
            return translate_in_bulk(modeladmin, request, queryset)

        return action_wrapper


class TranslateAppMixin(object):
    """
    ModelAdmin mixin used to add translate content with gpt provider
    """
    action = ""

    # actions = ["translate_in_bulk"]

    @property
    def media(self):
        return super().media + widgets.Media(
            css={"all": ["https://fonts.googleapis.com/icon?family=Material+Icons", ]}
        )

    def get_translation_request_items(self, obj):
        items = AppTranslationRequestItem.objects.all()
        request_items = items.filter(link_object_id=obj.pk, link_model=obj._meta.model_name,
                                     app_label=obj._meta.app_label)
        if request_items:
            translation_request = request_items.order_by("-id").first().translation_request
            return translation_request
        return None

    def send_translation_request(self, obj):

        def render_action(url, title):
            return mark_safe(
                '<a class="lang-code current active djangocms_translations" href="{url}"><i class="material-icons">translate</i></a>'
                .format(url=url, title=title)
            )

        action = render_action(
            (
                '{url}?link_model={link_model}&app_label={app_label}&link_object_id={app_id}&source_language={source_language}'
                .format(url=reverse('admin:create-app-translation-request'), app_label=obj._meta.app_label,
                        link_model=obj._meta.model_name, app_id=obj.pk,
                        source_language="de")),
            # TODO read language from request
            f"{_('Translate')}",
        )

        return format_html(
            '{action}',
            status="",
            action=action,
        )

    def translation_request_status(self, obj):
        action = ''

        # print(self.get_translation_request_items(obj), models.AppTranslationRequest.STATES.PENDING_APPROVAL)

        def render_action(url, title):
            return mark_safe(
                '<a class="button" href="{url}">{title}</a>'
                .format(url=url, title=title)
            )

        if self.get_translation_request_items(obj).state == \
           models.AppTranslationRequest.STATES.PENDING_APPROVAL if self.get_translation_request_items(obj) else "":
            action = render_action(
                reverse('admin:choose-app-translation-quote', args=(self.get_translation_request_items(obj).pk,)),
                _('Choose quote'),
            )

        return format_html(
            '{status} {action}',
            status=self.get_translation_request_items(obj).get_state_display() if self.get_translation_request_items(
                obj) else "",
            action=action,
        )

    send_translation_request.short_description = 'Translate'
    translation_request_status.short_description = 'Translation Status'
    send_translation_request.allow_tags = True

    def get_list_display(self, request):
        list_display = super().get_list_display(request)
        list_display = list(list_display) + ['translation_request_status', 'send_translation_request']

        return list_display
