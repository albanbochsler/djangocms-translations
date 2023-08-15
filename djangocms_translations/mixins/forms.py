from . import models
from django import forms


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
