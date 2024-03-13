import json

from django import forms
from django.conf.urls import url
from django.contrib.admin import ModelAdmin
from django.http import Http404
from django.shortcuts import redirect, render, get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.contrib import admin
from djangocms_translations.admin import AllReadOnlyFieldsMixin
from djangocms_translations.utils import pretty_json

from django.forms import widgets
from django.conf import settings

from allink_core.core.utils import get_model
from . import models, views

__all__ = [
    'TranslateAppMixin',
    'AppTranslationRequestAdmin',
]

from .models import AppTranslationRequest, AppTranslationRequestItem, TranslationDirective, TranslationDirectiveInline


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


@admin.register(TranslationDirective)
class TranslationDirectiveAdmin(admin.ModelAdmin):
    list_display = ("title", "master_language")
    form = TranslationDirectiveAdminForm
    inlines = [
        TranslationDirectiveAdminInline,
    ]


class TranslateAppInBulkStep1Form(forms.ModelForm):
    class Meta:
        model = AppTranslationRequest
        fields = ('source_language', 'target_language', 'provider_backend')

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super(TranslateAppInBulkStep1Form, self).__init__(*args, **kwargs)

    def clean(self, *args, **kwargs):
        super(TranslateAppInBulkStep1Form, self).clean(*args, **kwargs)
        if not self.is_valid():
            return

        return self.cleaned_data

    def save(self, *args, **kwargs):
        self.instance.user = self.user
        return super(TranslateAppInBulkStep1Form, self).save(*args, **kwargs)


class AppModelTreeMultipleChoiceField(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple
    INDENT = 8

    def label_from_instance(self, obj):
        target_language = self.target_language
        # disable models with already existing translation
        if obj.has_translation(target_language):
            return format_html(
                '<span style="color: #12BB06;">{title}</span>',
                title=obj.__str__(),
            )
        else:
            return format_html(
                '<span>{title}</span>',
                title=obj.__str__(),
            )


class TranslateAppInBulkStep2Form(forms.Form):
    app_models = AppModelTreeMultipleChoiceField(
        queryset=None,
        label=_('App models'),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        self.app_translation_request = kwargs.pop('translation_request')
        self.app_label = kwargs.pop('app_label')
        self.model_name = kwargs.pop('model_name')
        print("self.app_translation_request", self.app_translation_request,
              get_model(self.app_label, self.model_name).objects.all())
        super(TranslateAppInBulkStep2Form, self).__init__(*args, **kwargs)
        self.fields['app_models'] = AppModelTreeMultipleChoiceField(
            queryset=get_model(self.app_label, self.model_name).objects.all(),
            label=_('App models'),
            required=False,
        )
        self.fields['app_models'].target_language = self.app_translation_request.target_language
        self.fields['app_models'].source_language = self.app_translation_request.source_language

    def save(self, *args, **kwargs):
        translation_request_items = [
            models.AppTranslationRequestItem(
                translation_request=self.app_translation_request,
                link_object_id=obj.pk,
                app_label=self.app_label,
                link_model=self.model_name,
            )
            for obj in self.cleaned_data['app_models']
        ]

        self.app_translation_request.items.all().delete()
        models.AppTranslationRequestItem.objects.bulk_create(translation_request_items)
        self.app_translation_request.set_provider_order_name(self.app_label)


class TranslateAppBulkAdmin(ModelAdmin):
    """
    ModelAdmin used for bulk translation of objects
    """
    change_list_template = 'admin/djangocms_translations/translationrequest/bulk_change_form.html'

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super(TranslateAppBulkAdmin, self).__init__(*args, **kwargs)

    def _get_template_context(self, title, form=None, **kwargs):
        context = {
            'has_change_permission': True,
            'media': self.media,
            'opts': self.opts,
            'root_path': reverse('admin:index'),
            'current_app': self.admin_site.name,
            'app_label': self.opts.app_label,
            'model_name': self.opts.model_name,
            'title': title,
            'original': title,
        }
        if form is not None:
            context.update({
                'adminform': form,
                'media': self.media + form.media,
                'errors': form.errors,
            })
        context.update(kwargs)
        return context

    # def changelist_view(self, request, extra_context=None):
    #     extra_context = extra_context or {}
    #     extra_context.update(
    #         {
    #             # 'change_list_template_extends': self.change_list_template_extends,
    #             # 'bulk_translate_url': reverse('admin:{}-{}-translate-app-in-bulk'.format(
    #             #     self.model._meta.app_label, self.model._meta.model_name)
    #             # ),
    #         }
    #     )
    #     return super(TranslateAppBulkAdmin, self).changelist_view(request, extra_context)

    def do_bulk_translate(self, request):
        """
        View to translate the selected objects in bulk
        """
        session = request.session
        # bulk_translation_step = session.get('bulk_app_translation_step')
        # if bulk_translation_step == 2:
        #     return redirect('admin:translate-app-in-bulk-step-{}'.format(bulk_translation_step))
        # session['bulk_app_translation_step'] = 1

        form = TranslateAppInBulkStep1Form(data=request.POST or None, user=request.user)
        if form.is_valid():
            translation_request = form.save()
            if session.get('app_translation_request_pk'):
                session.pop('app_translation_request_pk')
            session['app_translation_request_pk'] = translation_request.pk
            return redirect('admin:translate-app-in-bulk-step-2')

        title = _('Create bulk translations')
        context = self._get_template_context(title, form)
        return render(request, 'admin/djangocms_translations/translationrequest/bulk_app_create_step_1.html', context)

    def translate_app_in_bulk_step_2(self, request):
        session = request.session

        # if session.get('bulk_app_translation_step') not in range(1, 4) or not (
        #     session.get('app_translation_request_pk')):
        #     raise Http404()

        trans_pk = session.get('app_translation_request_pk')
        translation_request = get_object_or_404(AppTranslationRequest.objects, pk=trans_pk)
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        form = TranslateAppInBulkStep2Form(data=request.POST or None, translation_request=translation_request,
                                           app_label=app_label, model_name=model_name)
        if form.is_valid():
            form.save()
            session.pop('app_translation_request_pk')
            translation_request = AppTranslationRequest.objects.get(id=translation_request.pk)
            translation_request.set_content_from_app()
            translation_request.get_quote_from_provider()
            return redirect('admin:djangocms_translations_apptranslationrequest_changelist')
        title = _('Create bulk 2 translations')

        context = self._get_template_context(title, form, translation_request=translation_request)

        return render(request, 'admin/djangocms_translations/translationrequest/bulk_app_create_step_2.html', context)

    def get_urls(self):
        urls = super(TranslateAppBulkAdmin, self).get_urls()
        info = self.model._meta.app_label, self.model._meta.model_name

        admin_do_bulk_translate = self.admin_site.admin_view(self.do_bulk_translate)
        translate_app_in_bulk_step_2 = self.admin_site.admin_view(self.translate_app_in_bulk_step_2)

        bulk_urls = [
            url(
                r'^translate-app-in-bulk/$',
                admin_do_bulk_translate,
                name='%s_%s_translate-app-in-bulk' % info,
            ),
            url(
                r'^translate-app-in-bulk-step-2/$',
                translate_app_in_bulk_step_2,
                name="%s_%s_translate-app-in-bulk-step-2" % info,
            ),
        ]
        return bulk_urls + urls


@admin.register(AppTranslationRequest)
class AppTranslationRequestAdmin(AllReadOnlyFieldsMixin, admin.ModelAdmin):
    inlines = [
        AppTranslationQuoteInline,
        AppTranslationRequestItemInline,
        AppTranslationOrderInline,
    ]

    list_filter = ('state',)
    list_display = (
        'provider_order_name',
        'date_created',
        # 'pages_sent',
        # 'pretty_source_language',
        # 'pretty_target_language',
        'pretty_status',
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
                'pretty_export_fields',
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
        'pretty_export_fields',
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

    def pretty_export_fields(self, obj):
        if isinstance(obj.export_fields, dict):
            data = json.dumps(obj.export_fields)
        else:
            data = obj.export_fields
        return pretty_json(data)

    pretty_export_content.short_description = _('Export content')
    pretty_export_fields.short_description = _('Export fields')

    def get_urls(self):
        return [
            # url(
            #     r'translate-app-in-bulk-step-1/$',
            #     self.translate_app_in_bulk_step_1,
            #     name='translate-in-bulk-step-1',
            # ),
            # url(
            #     r'translate-app-in-bulk-step-2/$',
            #     self.translate_app_in_bulk_step_2,
            #     name='translate-in-bulk-step-2',
            # ),
            # url(
            #     r'translate-app-in-bulk-back/$',
            #     self.translate_app_in_bulk_back,
            #     name='translate-app-in-bulk-back',
            # ),
            url(
                r'add/$',
                views.CreateTranslationRequestView.as_view(),
                name='create-app-translation-request',
            ),
            url(
                r'(?P<pk>\w+)/get-app-quote-from-provider/$',
                views.get_quote_from_provider_view,
                name='get-app-quote-from-provider',
            ),
            url(
                r'(?P<pk>\w+)/choose-app-quote/$',
                views.ChooseTranslationQuoteView.as_view(),
                name='choose-app-translation-quote',
            ),
            url(
                r'(?P<pk>\w+)/callback/$',
                views.process_provider_callback_view,
                name='app-translation-request-provider-callback',
            ),

        ] + super(AppTranslationRequestAdmin, self).get_urls()

    def pretty_status(self, obj):
        action = ''

        def render_action(url, title):
            return mark_safe(
                '<a class="button" href="{url}">{title}</a>'
                .format(url=url, title=title)
            )

        if obj.state == models.AppTranslationRequest.STATES.PENDING_QUOTE:
            action = mark_safe(
                '<a class="button" '
                'onclick="window.django.jQuery.ajax({{'  # noqa
                'method: \'POST\', headers: {headers}, url: \'{url}\', success: {refresh_window_callback}'
                '}});" href="#">{title}</a>'.format(
                    url=reverse('admin:get-app-quote-from-provider', args=(obj.pk,)),
                    title=_('Refresh'),
                    headers='{\'X-CSRFToken\': document.cookie.match(/csrftoken=(\w+)(;|$)/)[1]}',
                    refresh_window_callback='function () {window.location.reload()}',
                )
            )
        elif obj.state == models.AppTranslationRequest.STATES.PENDING_APPROVAL:
            action = render_action(
                reverse('admin:choose-app-translation-quote', args=(obj.pk,)),
                _('Choose quote'),
            )

        # elif obj.state == models.AppTranslationRequest.STATES.IMPORT_FAILED:
        #     action = render_action(
        #         reverse('admin:translation-request-show-log', args=(obj.pk,)),
        #         _('Log'),
        #     )
        def render_task_status(obj):
            title = _('Task status')
            location = obj.order.provider_details["Location"] if obj.order.provider_details.__contains__(
                "Location") else ""
            url = '{}{}'.format(obj.provider.api_url, location)

            return mark_safe(
                '<a class="button" href="{url}" target="_blank">{title}</a>'
                .format(url=url, title=title)
            )

        return format_html(
            '{status} {action} {task}',
            status=obj.get_state_display(),
            action=action,
            task=render_task_status(obj) if obj.state == models.AppTranslationRequest.STATES.IN_TRANSLATION else "",
        )

    pretty_status.short_description = _('Status')


class TranslateAppInBulkForm(forms.ModelForm):
    class Meta:
        model = AppTranslationRequest
        fields = ('source_language', 'target_language', 'provider_backend')

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        self.app_label = kwargs.pop('app_label')
        self.model_name = kwargs.pop('model_name')
        self.queryset = kwargs.pop('queryset')
        super(TranslateAppInBulkForm, self).__init__(*args, **kwargs)

    def clean(self, *args, **kwargs):
        super(TranslateAppInBulkForm, self).clean(*args, **kwargs)
        if not self.is_valid():
            return

        return self.cleaned_data

    def save(self, *args, **kwargs):
        self.instance.user = self.user
        translation_request_items = [
            models.AppTranslationRequestItem(
                translation_request=self.instance,
                link_object_id=obj.pk,
                app_label=self.app_label,
                link_model=self.model_name,
            )
            for obj in self.queryset
        ]
        models.AppTranslationRequestItem.objects.bulk_create(translation_request_items)
        return super(TranslateAppInBulkForm, self).save(*args, **kwargs)


class TranslateAppBulkMixin(ModelAdmin):
    """
    ModelAdmin mixin used to add bulk translation of objects
    """
    action = ""

    actions = ["translate_in_bulk"]
    change_form_template = 'admin/djangocms_translations/apptranslationrequest/change_form.html'

    def __init__(self, *args, **kwargs):
        super(TranslateAppBulkMixin, self).__init__(*args, **kwargs)

    def _get_template_context(self, title, form=None, **kwargs):
        context = {
            'has_change_permission': True,
            'media': self.media,
            'opts': self.opts,
            'root_path': reverse('admin:index'),
            'current_app': self.admin_site.name,
            'app_label': self.opts.app_label,
            'model_name': self.opts.model_name,
            'title': title,
            'original': title,
        }
        if form is not None:
            context.update({
                'adminform': form,
                'media': self.media + form.media,
                'errors': form.errors,
            })
        context.update(kwargs)
        return context

    def translate_in_bulk(self, request, queryset):
        """
        Action to translate the selected objects in bulk
        """
        # TODO also translate allinkCategory

        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        user = request.user
        source_lang = request.GET.get('source_language', 'de')
        target_lang = request.GET.get('target_language', 'en')
        provider_backend = request.GET.get('provider_backend', 'GptTranslationProvider')
        title = _('Create bulk translations')
        # form = TranslateAppInBulkForm(data=request.GET or None, user=request.user, app_label=app_label,
        #                               model_name=model_name, queryset=queryset)
        # form = TranslateAppInBulkStep1Form(data=request.GET or None, user=request.user)

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
        else:
            form = TranslateAppInBulkStep1Form(data=request.GET or None, user=request.user)
            context = self._get_template_context(title, form)
            return render(request, 'admin/djangocms_translations/apptranslationrequest/bulk_create_step_1.html',
                          context)

        # context = self._get_template_context(title, form)
        # print("form", form)
        # if form.is_valid():
        #     translation_request = form.save()
        #     print("translation_request", form, translation_request)
        #     # translation_request.set_content_from_app()
        #     # translation_request.get_quote_from_provider()
        #     # return redirect('admin:djangocms_translations_apptranslationrequest_changelist')
        #
        # else:
        #     print("form is not valid", form.errors)

        # return TemplateResponse(request, 'admin/djangocms_translations/apptranslationrequest/bulk_create_step_1.html',
        #                         context)
        # return render(request or None, 'admin/djangocms_translations/apptranslationrequest/bulk_create_step_1.html',
        #               context)


class TranslateAppMixin(object):
    """
    ModelAdmin mixin used to add translate content with gpt provider
    """
    action = ""

    # actions = ["translate_in_bulk"]

    @property
    def media(self):
        return super(TranslateAppMixin, self).media + widgets.Media(
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
        list_display = super(TranslateAppMixin, self).get_list_display(request)
        list_display = list(list_display) + ['translation_request_status', 'send_translation_request']

        return list_display
