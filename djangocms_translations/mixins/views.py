import json

from django.views.generic import CreateView, UpdateView
from django.urls import reverse
from . import forms, models
from django.views.decorators.http import require_GET, require_POST
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db import IntegrityError
from django.views.decorators.csrf import csrf_exempt

from .models import AppTranslationRequest


class CreateTranslationRequestView(CreateView):
    template_name = 'djangocms_translations/create_request.html'
    form_class = forms.CreateTranslationForm

    def get_success_url(self):
        # return reverse('admin:djangocms_translations_apptranslationrequest_changelist')
        return reverse('admin:choose-app-translation-quote', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        form_kwargs = super(CreateTranslationRequestView, self).get_form_kwargs()
        print("request.user: ", self.request)
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
        AppTranslationRequest
        .objects
        .all()  # TODO change to PENDING_QUOTE
        # .filter(state=AppTranslationRequest.STATES.IN_TRANSLATION)
    )
    trans_request = get_object_or_404(requests, pk=pk)
    # convert request body to dict
    request_body = json.loads(request.body)
    success = trans_request.import_response(request_body)
    return JsonResponse({'success': success})


@require_POST
def get_quote_from_provider_view(request, pk):
    print("get_quote_from_provider_view", pk)
    if not request.user.is_staff:
        raise PermissionDenied

    translation_request = get_object_or_404(
        AppTranslationRequest.objects.filter(state=AppTranslationRequest.STATES.PENDING_QUOTE),
        pk=pk,
    )

    translation_request.get_quote_from_provider()

    print("translation_request.get_quote_from_provider()", translation_request.get_quote_from_provider())
    return JsonResponse({'success': True})
