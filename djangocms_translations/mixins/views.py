import json

from django.views.generic import CreateView, UpdateView
from django.urls import reverse
from . import forms
from .. import models
from django.views.decorators.http import require_POST
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt


class CreateTranslationRequestView(CreateView):
    template_name = 'djangocms_translations/create_request.html'
    form_class = forms.CreateTranslationForm

    def get_success_url(self):
        return reverse('admin:choose-app-translation-quote', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        form_kwargs = super(CreateTranslationRequestView, self).get_form_kwargs()
        form_kwargs['user'] = self.request.user
        form_kwargs['initial'] = self.request.GET.dict()
        return form_kwargs

    def form_valid(self, form):
        response = super(CreateTranslationRequestView, self).form_valid(form)
        self.object.set_content_from_app()
        self.object.get_quote_from_provider()
        return response


class ChooseTranslationQuoteView(UpdateView):
    template_name = 'djangocms_translations/choose_quote.html'
    form_class = forms.ChooseTranslationQuoteForm
    model = models.AppTranslationRequest

    def get_success_url(self):
        try:
            return reverse('admin:{}_{}_{}'.format(self.object.get_app_from_export_content(),
                                                   self.object.get_app_from_export_content(), 'changelist'))
        except Exception as e:
            return reverse('admin:djangocms_translations_apptranslationrequest_changelist')

    def form_valid(self, form):
        response = super(ChooseTranslationQuoteView, self).form_valid(form)
        self.object.set_status(models.AppTranslationRequest.STATES.READY_FOR_SUBMISSION)
        self.object.submit_request()
        return response


@csrf_exempt
@require_POST
def process_provider_callback_view(request, pk):
    requests = (
        models.AppTranslationRequest
        .objects
        .all()
    )
    trans_request = get_object_or_404(requests, pk=pk)
    # convert request body to dict
    request_body = json.loads(request.body)
    success = trans_request.import_response(request_body)
    return JsonResponse({'success': success})


@require_POST
def get_quote_from_provider_view(request, pk):
    if not request.user.is_staff:
        raise PermissionDenied

    translation_request = get_object_or_404(
        models.AppTranslationRequest.objects.filter(state=models.AppTranslationRequest.STATES.PENDING_QUOTE),
        pk=pk,
    )

    translation_request.get_quote_from_provider()

    return JsonResponse({'success': True})
