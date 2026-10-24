import copy
import json
from contextlib import contextmanager
from unittest import mock

from django.urls import reverse

from cms.api import add_plugin, create_page
from cms.models import PageContent
from cms.test_utils.testcases import CMSTestCase

from djangocms_versioning.models import Version

from djangocms_translations.models import AppTranslationRequest, TranslationRequest

from .test_app.models import PageTitleExtension

PROVIDER = "GptTranslationProvider"


def translate(content):
    """The stand-in translator: marks every string, so a test can tell what came back."""
    return f"[en] {content}"


def content_placeholder(content):
    content.rescan_placeholders()
    return content.placeholders.get(slot="content")


def create_translated(model, **fields):
    """A parler object with its translated ``fields`` in German, the source language."""
    obj = model(**{name: value for name, value in fields.items() if name not in model._parler_meta.get_all_fields()})
    obj.set_current_language("de")
    for name in model._parler_meta.get_all_fields():
        if name in fields:
            setattr(obj, name, fields[name])
    obj.save()
    return obj


def provider_response(request_content):
    """The callback body the provider posts back: the request's groups, translated."""
    groups = copy.deepcopy(request_content["Groups"])
    for group in groups:
        for item in group["Items"]:
            item["Content"] = translate(item["Content"])
    return {"Groups": groups}


@contextmanager
def mock_provider(json_data=None):
    """Answers every provider HTTP call, so no test reaches ai-utils."""
    response = mock.Mock(ok=True)
    response.json.return_value = json_data if json_data is not None else {"Location": "/status/1"}
    with mock.patch("djangocms_translations.providers.gpt.requests.request", return_value=response) as request:
        yield request


QUOTE = {
    "Currency": "CHF",
    "Options": [
        {
            "OrderTypeId": 2,
            "Name": "gpt-6-luna",
            "ShortDescription": "Next-generation translation",
            "Description": "Most efficient GPT-6 model",
            "DeliveryOptions": [
                {"DeliveryId": 1, "Name": "OpenAI", "DeliveryDate": "2026-10-24T00:00:00+00:00", "Price": ""},
            ],
        },
    ],
}


class TranslationTestCase(CMSTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.get_superuser()

    def create_page(self, title="Startseite", body="<p>Hallo Welt</p>", og_title="Schweizer Cloud", publish=True):
        page = create_page(title, "fullwidth.html", "de", created_by=self.user)
        content = PageContent.admin_manager.get(page=page, language="de")
        if body:
            add_plugin(content_placeholder(content), "TextPlugin", "de", body=body)
        if og_title:
            PageTitleExtension.objects.create(extended_object=content, og_title=og_title)
        if publish:
            Version.objects.get_for_content(content).publish(self.user)
        return page

    def add_translation(self, page, title="Home", body="<p>Hello world</p>", publish=True):
        """An existing English translation, the state a re-translation starts from."""
        content = PageContent.objects.with_user(self.user).create(
            page=page, language="en", title=title, template="fullwidth.html"
        )
        add_plugin(content_placeholder(content), "TextPlugin", "en", body=body)
        PageTitleExtension.objects.create(extended_object=content, og_title="Swiss cloud")
        if publish:
            Version.objects.get_for_content(content).publish(self.user)
        return content

    def page_versions(self, page, language="en"):
        contents = PageContent.admin_manager.filter(page=page, language=language)
        return Version.objects.filter_by_grouper(page).filter(object_id__in=contents.values_list("pk", flat=True))

    def draft(self, page, language="en"):
        return self.page_versions(page, language).get(state="draft").content

    def translate_pages(self, *pages, translate_content=True, translate_title=True, translate_seo=True):
        """Runs a page request end to end: export, submit, then the provider's callback."""
        request = TranslationRequest.objects.create(
            user=self.user, source_language="de", target_language="en", provider_backend=PROVIDER
        )
        for page in pages:
            request.items.create(source_cms_page=page, target_cms_page=page)
        request.set_content_from_cms(
            translate_content=translate_content, translate_title=translate_title, translate_seo=translate_seo
        )
        request.set_request_content()
        with mock_provider():
            request.submit_request()
        self.callback("admin:translation-request-provider-callback", request)
        request.refresh_from_db()
        return request

    def translate_objects(self, *objects):
        """Runs an app request end to end for objects of one model."""
        request = AppTranslationRequest.objects.create(
            user=self.user, source_language="de", target_language="en", provider_backend=PROVIDER
        )
        for obj in objects:
            request.items.create(
                app_label=obj._meta.app_label, link_model=obj._meta.model_name, link_object_id=obj.pk
            )
        request.set_content_from_app()
        request.request_content = request.provider.get_export_data()
        request.save(update_fields=["request_content"])
        with mock_provider():
            request.submit_request()
        self.callback("admin:app-translation-request-provider-callback", request)
        request.refresh_from_db()
        return request

    def callback(self, url_name, request):
        response = self.client.post(
            reverse(url_name, args=[request.pk]),
            data=json.dumps(provider_response(request.request_content)),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        return response
