from .. import models
from django import forms
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _


class CreateTranslationForm(forms.ModelForm):
    app_label = forms.CharField()  # better to use a ModelChoiceField with apphooks
    link_model = forms.CharField()  # better to use a ModelChoiceField with apphooks
    link_object_id = forms.IntegerField()

    class Meta:
        model = models.AppTranslationRequest
        fields = [
            'app_label',
            'link_model',
            'link_object_id',
            'source_language',
            'target_language',
            'provider_backend',
        ]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super(CreateTranslationForm, self).__init__(*args, **kwargs)

    def clean(self, *args, **kwargs):
        super(CreateTranslationForm, self).clean(*args, **kwargs)
        if not self.is_valid():
            return

        translation_request = models.AppTranslationRequest(
            source_language=self.cleaned_data['source_language'],
            target_language=self.cleaned_data['target_language'],
            provider_backend=self.cleaned_data['provider_backend'],
        )

        models.AppTranslationRequestItem(
            translation_request=translation_request,
            app_label=self.cleaned_data['app_label'],
            link_model=self.cleaned_data['link_model'],
            link_object_id=self.cleaned_data['link_object_id'],
        ).clean()

        return self.cleaned_data

    def save(self, *args, **kwargs):
        self.instance.user = self.user
        translation_request = super(CreateTranslationForm, self).save(*args, **kwargs)

        translation_request.items.create(
            app_label=self.cleaned_data['app_label'],
            link_model=self.cleaned_data['link_model'],
            link_object_id=self.cleaned_data['link_object_id'],
        )
        translation_request.set_provider_order_name(self.cleaned_data['link_model'])
        return translation_request


class ChooseTranslationQuoteForm(forms.ModelForm):
    class Meta:
        model = models.AppTranslationRequest
        fields = (
            'selected_quote',
        )
        widgets = {
            'selected_quote': forms.RadioSelect(),
        }

    def get_choice_label(self, obj):
        formatted_delivery_date = date_format(obj.delivery_date, "d. F Y")
        return format_html(_(
            '<strong>({}) {}</strong><br>'
            '{}'
            # 'Delivery until: {}<br>'
            # 'Price: {} {}'
        ), obj.delivery_date_name, obj.name, obj.description,)

    def fix_widget_choices(self):
        widget = self.fields['selected_quote'].widget
        new_widget_choices = []
        for translation_quote in models.AppTranslationQuote.objects.filter(
            pk__in=[choice[0].instance.pk for choice in widget.choices]):
            new_widget_choices.append((translation_quote.pk, self.get_choice_label(translation_quote)))
        widget.choices = new_widget_choices

    def __init__(self, *args, **kwargs):
        super(ChooseTranslationQuoteForm, self).__init__(*args, **kwargs)
        self.fields['selected_quote'].required = True
        self.fields['selected_quote'].queryset = self.instance.quotes.all()
        self.fields['selected_quote'].empty_label = None
        self.fix_widget_choices()
