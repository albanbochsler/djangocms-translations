from cms.api import add_plugin
from cms.models import PageContent

from djangocms_text_ckeditor.models import Text

from djangocms_translations.models import TranslationDirective, TranslationRequest

from .base import QUOTE, TranslationTestCase, mock_provider
from .test_app.models import Link


class GptExportTestCase(TranslationTestCase):
    def setUp(self):
        super().setUp()
        self.page = self.create_page()
        self.add_translation(self.page)
        self.request = TranslationRequest.objects.create(
            user=self.user, source_language="de", target_language="en", provider_backend="GptTranslationProvider"
        )
        self.item = self.request.items.create(source_cms_page=self.page, target_cms_page=self.page)

    def export(self):
        self.request.set_content_from_cms()
        return self.request.provider.get_export_data()

    def groups(self):
        return {group["GroupId"]: group["Items"] for group in self.export()["Groups"]}

    def test_maps_the_languages(self):
        data = self.export()

        self.assertEqual(data["SourceLang"], "de-CH")
        self.assertEqual(data["TargetLanguages"], ["en-US"])

    def test_groups_plugins_by_item_placeholder_and_plugin(self):
        text = Text.objects.get(language="de")

        self.assertEqual(
            self.groups()[f"{self.item.pk}:content:{text.pk}"], [{"Id": "body", "Content": "<p>Hallo Welt</p>"}]
        )

    def test_groups_page_fields_by_item_field_and_extension(self):
        extension = PageContent.admin_manager.get(page=self.page, language="en").pagetitleextension
        groups = self.groups()

        self.assertEqual(groups[f"{self.item.pk}:title:{extension.pk}"], [{"Id": "field", "Content": "Startseite"}])
        self.assertEqual(
            groups[f"{self.item.pk}:og_title:{extension.pk}"], [{"Id": "field", "Content": "Schweizer Cloud"}]
        )

    def test_skips_empty_fields(self):
        extension = PageContent.admin_manager.get(page=self.page, language="en").pagetitleextension

        self.assertNotIn(f"{self.item.pk}:hero_lead:{extension.pk}", self.groups())

    def test_sends_child_plugins_as_their_own_group(self):
        text = Text.objects.get(language="de")
        link = add_plugin(text.placeholder, "LinkPlugin", "de", target=text, label="Kontakt")

        self.assertEqual(
            self.groups()[f"{self.item.pk}:content:{link.pk}"], [{"Id": "label", "Content": "Kontakt"}]
        )

    def test_includes_the_directives(self):
        directive = TranslationDirective.objects.create(title="Brand", master_language="de")
        directive.translations.filter(language="de").update(directive_item="eqipe")
        directive.translations.filter(language="en").update(directive_item="eqipe", prompt_instruction="Keep")

        self.assertEqual(
            self.export()["Directives"],
            {
                directive.pk: {
                    "masterLanguage": "de-CH",
                    "de-CH": {"directive_item": "eqipe", "prompt_instruction": ""},
                    "en-US": {"directive_item": "eqipe", "prompt_instruction": "Keep"},
                },
            },
        )


class GptImportTestCase(TranslationTestCase):
    def test_imports_child_plugin_labels(self):
        page = self.create_page()
        text = Text.objects.get(language="de")
        add_plugin(text.placeholder, "LinkPlugin", "de", target=text, label="Kontakt")

        self.translate_pages(page)

        self.assertEqual(
            list(Link.objects.filter(language="en").values_list("label", flat=True)), ["[en] Kontakt"]
        )


class GptQuoteTestCase(TranslationTestCase):
    def test_creates_one_quote_per_delivery_option(self):
        page = self.create_page()
        request = TranslationRequest.objects.create(
            user=self.user, source_language="de", target_language="en", provider_backend="GptTranslationProvider"
        )
        request.items.create(source_cms_page=page, target_cms_page=page)
        request.set_content_from_cms()

        with mock_provider(QUOTE) as provider:
            request.get_quote_from_provider()

        self.assertEqual(provider.call_args.kwargs["url"], "http://ai-utils.test/quote")
        self.assertEqual(request.state, TranslationRequest.STATES.PENDING_APPROVAL)
        quote = request.quotes.get()
        self.assertEqual(quote.name, "gpt-6-luna (Next-generation translation)")
        self.assertEqual(quote.provider_options, {"OrderTypeId": 2, "DeliveryId": 1})
