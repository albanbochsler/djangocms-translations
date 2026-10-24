import unittest

from django.test import override_settings
from django.urls import reverse

from cms.api import add_plugin
from cms.models import PageContent

from djangocms_alias.models import Alias, AliasContent, Category
from djangocms_text_ckeditor.models import Text
from djangocms_versioning.models import Version

from djangocms_translations.models import TranslationRequest

from .base import QUOTE, TranslationTestCase, mock_provider
from .test_app.models import PageTitleExtension


def text_bodies(content, language="en"):
    texts = Text.objects.filter(placeholder__in=content.placeholders.all(), language=language)
    return list(texts.values_list("body", flat=True))


class NewPageTranslationTestCase(TranslationTestCase):
    def test_imports_content_into_a_new_draft(self):
        page = self.create_page()

        request = self.translate_pages(page)

        self.assertEqual(request.state, TranslationRequest.STATES.IMPORTED)
        self.assertEqual(text_bodies(self.draft(page)), ["[en] <p>Hallo Welt</p>"])

    def test_leaves_the_source_language_alone(self):
        page = self.create_page()

        self.translate_pages(page)

        german = PageContent.objects.get(page=page, language="de")
        self.assertEqual(text_bodies(german, "de"), ["<p>Hallo Welt</p>"])
        self.assertEqual(german.title, "Startseite")
        self.assertEqual(german.pagetitleextension.og_title, "Schweizer Cloud")

    def test_translates_the_title_of_a_new_page(self):
        page = self.create_page()

        self.translate_pages(page)

        draft = self.draft(page)
        self.assertEqual(draft.title, "[en] Startseite")
        self.assertEqual(draft.pagetitleextension.og_title, "[en] Schweizer Cloud")

    @unittest.expectedFailure
    @override_settings(
        CMS_LANGUAGES={
            1: [
                {"code": "de", "name": "Deutsch", "fallbacks": []},
                {"code": "en", "name": "English", "fallbacks": []},
            ],
        },
    )
    def test_translates_the_title_of_a_new_page_without_a_language_fallback(self):
        # Without a fallback to the source, get_export_fields() finds no target content and sets no pk,
        # and the GPT export drops pk-less fields in a bare ``except``: the new page keeps the German title.
        page = self.create_page()

        self.translate_pages(page)

        self.assertEqual(self.draft(page).title, "[en] Startseite")


class ExistingPageTranslationTestCase(TranslationTestCase):
    def setUp(self):
        super().setUp()
        self.page = self.create_page()

    def test_copies_the_published_translation_into_a_new_draft(self):
        published = self.add_translation(self.page)

        self.translate_pages(self.page)

        states = dict(self.page_versions(self.page).values_list("state", "object_id"))
        self.assertEqual(states["published"], published.pk)
        self.assertNotEqual(states["draft"], published.pk)
        self.assertEqual(text_bodies(published), ["<p>Hello world</p>"])
        self.assertEqual(text_bodies(self.draft(self.page)), ["[en] <p>Hallo Welt</p>"])

    def test_reuses_an_existing_draft(self):
        draft = self.add_translation(self.page, publish=False)

        self.translate_pages(self.page)

        self.assertEqual(self.page_versions(self.page).count(), 1)
        self.assertEqual(self.draft(self.page).pk, draft.pk)
        self.assertEqual(text_bodies(draft), ["[en] <p>Hallo Welt</p>"])

    def test_builds_on_the_published_version_rather_than_an_archived_one(self):
        archived = self.add_translation(self.page)
        archived.meta_description = "archived"
        archived.save()
        version = Version.objects.get_for_content(archived).copy(self.user)
        version.content.meta_description = "published"
        version.content.save()
        version.publish(self.user)

        self.translate_pages(self.page)

        self.assertEqual(self.draft(self.page).meta_description, "published")

    def test_updates_the_title(self):
        self.add_translation(self.page)

        self.translate_pages(self.page)

        self.assertEqual(self.draft(self.page).title, "[en] Startseite")

    def test_writes_the_title_extension_on_the_draft(self):
        published = self.add_translation(self.page)

        self.translate_pages(self.page)

        self.assertEqual(self.draft(self.page).pagetitleextension.og_title, "[en] Schweizer Cloud")
        published.refresh_from_db()
        self.assertEqual(PageTitleExtension.objects.get(extended_object=published).og_title, "Swiss cloud")

    def test_keeps_the_title_when_titles_are_not_translated(self):
        self.add_translation(self.page)

        self.translate_pages(self.page, translate_title=False)

        draft = self.draft(self.page)
        self.assertEqual(draft.title, "Home")
        self.assertEqual(draft.pagetitleextension.og_title, "[en] Schweizer Cloud")

    def test_clears_only_the_page_placeholders(self):
        draft = self.add_translation(self.page, publish=False)
        category = Category.objects.create(name="Shared")
        alias = Alias.objects.create(category=category, position=0)
        # Same object id as the page's draft content, so only the content type tells them apart.
        alias_content = AliasContent.objects.with_user(self.user).create(
            pk=draft.pk, alias=alias, language="en", name="Footer"
        )
        add_plugin(alias_content.placeholder, "TextPlugin", "en", body="<p>Footer</p>")

        self.translate_pages(self.page)

        self.assertEqual(
            list(Text.objects.filter(placeholder=alias_content.placeholder).values_list("body", flat=True)),
            ["<p>Footer</p>"],
        )


class ProviderCallbackTestCase(TranslationTestCase):
    def test_ignores_a_request_that_is_not_in_translation(self):
        request = TranslationRequest.objects.create(
            user=self.user, source_language="de", target_language="en", provider_backend="GptTranslationProvider"
        )

        response = self.client.post(
            reverse("admin:translation-request-provider-callback", args=[request.pk]),
            data="{}",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)


class BulkTranslationAdminTestCase(TranslationTestCase):
    def test_creates_a_request_with_quotes_for_the_chosen_pages(self):
        home = self.create_page("Startseite")
        about = self.create_page("Über uns")

        with self.login_user_context(self.user), mock_provider(QUOTE):
            step_1 = self.client.post(
                reverse("admin:translate-in-bulk-step-1"),
                {
                    "source_language": "de",
                    "target_language": "en",
                    "provider_backend": "GptTranslationProvider",
                    "translate_content": "on",
                    "translate_title": "on",
                    "translate_seo": "on",
                },
            )
            step_2 = self.client.post(reverse("admin:translate-in-bulk-step-2"), {"pages": [home.pk, about.pk]})

        self.assertRedirects(step_1, reverse("admin:translate-in-bulk-step-2"), fetch_redirect_response=False)
        self.assertEqual(step_2.status_code, 302)
        request = TranslationRequest.objects.get()
        self.assertEqual(request.state, TranslationRequest.STATES.PENDING_APPROVAL)
        self.assertCountEqual(request.items.values_list("source_cms_page", flat=True), [home.pk, about.pk])
        self.assertEqual(request.quotes.get().provider_options, {"OrderTypeId": 2, "DeliveryId": 1})
