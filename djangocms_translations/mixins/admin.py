import json

from django.conf.urls import url
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.contrib import admin
from djangocms_translations.admin import AllReadOnlyFieldsMixin
from djangocms_translations.utils import pretty_json

from . import models, views

__all__ = [
    'TranslateAppMixin',
    'AppTranslationRequestAdmin',
]

from .models import AppTranslationRequest


class AppTranslationRequestItemInline(AllReadOnlyFieldsMixin, admin.TabularInline):
    model = models.AppTranslationRequestItem
    extra = 0
    classes = ['collapse']


class AppTranslationQuoteInline(AllReadOnlyFieldsMixin, admin.TabularInline):
    model = models.AppTranslationQuote
    extra = 0
    classes = ['collapse']


@admin.register(AppTranslationRequest)
class AppTranslationRequestAdmin(AllReadOnlyFieldsMixin, admin.ModelAdmin):
    inlines = [
        AppTranslationQuoteInline,
        AppTranslationRequestItemInline,
    ]

    list_filter = ('state',)
    list_display = (
        'provider_order_name',
        'date_created',
        # 'pages_sent',
        # 'pretty_source_language',
        # 'pretty_target_language',
        # 'pretty_status',
    )

    fieldsets = (
        (None, {
            'fields': (
                'provider_order_name',
                'user',
                'state',
                (
                    'date_created',
                    'date_submitted',
                    'date_received',
                    'date_imported',
                ),
                (
                    # 'pretty_source_language',
                    # 'pretty_target_language',
                ),
                'provider_backend',
            ),
        }),
        (_('Additional info'), {
            'fields': (
                'pretty_provider_options',
                'pretty_export_content',
                # 'pretty_request_content',
                # 'selected_quote',
            ),
            'classes': ('collapse',),
        }),
    )

    #
    readonly_fields = (
        #     'provider_order_name',
        #     'date_created',
        #     'date_submitted',
        #     'date_received',
        #     'date_imported',
        #     'pretty_source_language',
        #     'pretty_target_language',
        'pretty_provider_options',
        'pretty_export_content',
        #     'pretty_request_content',
        #     'selected_quote',
    )

    def pretty_provider_options(self, obj):
        return pretty_json(json.dumps(obj.provider_options))

    pretty_provider_options.short_description = _('Provider options')

    def pretty_export_content(self, obj):
        if isinstance(obj.export_content, dict):
            data = json.dumps(obj.export_content)
        else:
            data = obj.export_content
        return pretty_json(data)

    pretty_export_content.short_description = _('Export content')

    def get_urls(self):
        return [
            url(
                r'add/$',
                views.CreateTranslationRequestView.as_view(),
                name='create-app-translation-request',
            ),
            url(
                r'(?P<pk>\w+)/choose-quote/$',
                views.ChooseTranslationQuoteView.as_view(),
                name='choose-translation-quote',
            ),
        ] + super(AppTranslationRequestAdmin, self).get_urls()


class TranslateAppMixin(object):
    """
    ModelAdmin mixin used to add translate content with gpt provider
    """
    action = ""

    def send_translation_request(self, obj):
        print("send_translation_request", obj._meta.app_label)

        def render_action(url, title):
            return mark_safe(
                '<a class="button" href="{url}">{title}</a>'
                .format(url=url, title=title)
            )

        action = render_action(
            (
                '{url}?link_model={link_model}&app_label={app_label}&link_object_id={app_id}&source_language={source_language}'
                .format(url=reverse('admin:create-app-translation-request'), app_label=obj._meta.app_label,
                        link_model=obj._meta.model_name, app_id=obj.pk,
                        source_language="de")),
            # TODO read language from request
            _('Translate app'),
        )

        print("action", obj.pk)

        return format_html(
            '{status} {action}',
            status="Translate",
            action=action,
        )

    send_translation_request.short_description = 'Translate'
    send_translation_request.allow_tags = True

    def get_list_display(self, request):
        list_display = super(TranslateAppMixin, self).get_list_display(request)
        print(list_display)
        list_display = list(list_display) + ('send_translation_request',)

        return list_display
