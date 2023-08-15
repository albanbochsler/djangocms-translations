from django.views.generic import CreateView, UpdateView
from django.urls import reverse
from . import forms, models


class CreateTranslationRequestView(CreateView):
    template_name = 'djangocms_translations/create_request.html'
    form_class = forms.CreateTranslationForm

    def get_success_url(self):
        return reverse('admin:djangocms_translations_apptranslationrequest_changelist')
        # return reverse('admin:choose-app-translation-quote', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        form_kwargs = super(CreateTranslationRequestView, self).get_form_kwargs()
        print("request.user: ", self.request)
        form_kwargs['user'] = self.request.user
        form_kwargs['initial'] = self.request.GET.dict()
        return form_kwargs

    def form_valid(self, form):
        response = super(CreateTranslationRequestView, self).form_valid(form)
        self.object.set_content_from_app()
        # self.object.get_quote_from_provider()
        return response


class ChooseTranslationQuoteView(UpdateView):
    template_name = 'djangocms_translations/choose_quote.html'
    form_class = forms.ChooseTranslationQuoteForm
    model = models.AppTranslationRequest

    def get_success_url(self):
        return reverse('admin:djangocms_translations_apptranslationrequest_changelist')

    def form_valid(self, form):
        response = super(ChooseTranslationQuoteView, self).form_valid(form)
        self.object.set_status(models.AppTranslationRequest.STATES.READY_FOR_SUBMISSION)
        self.object.submit_request()
        return response
