import json

from django.urls import reverse

from djangocms_translations.models import AppTranslationRequest

from .base import QUOTE, TranslationTestCase, create_translated, mock_provider
from .test_app.models import Feature, Product


class AppTranslationTestCase(TranslationTestCase):
    def setUp(self):
        super().setUp()
        self.product = create_translated(
            Product, name="Speicher", description="Daten in der Schweiz", website="https://eqipe.ch"
        )
        self.features = [
            create_translated(Feature, product=self.product, label="Tägliches Backup"),
            create_translated(Feature, product=self.product, label="Eigene Domain"),
        ]

    def test_translates_the_fields(self):
        request = self.translate_objects(self.product)

        self.assertEqual(request.state, AppTranslationRequest.STATES.IMPORTED)
        english = Product.objects.language("en").get(pk=self.product.pk)
        self.assertEqual(english.name, "[en] Speicher")
        self.assertEqual(english.description, "[en] Daten in der Schweiz")

    def test_translates_the_inlines(self):
        self.translate_objects(self.product)

        labels = [feature.safe_translation_getter("label", language_code="en") for feature in self.features]
        self.assertEqual(labels, ["[en] Tägliches Backup", "[en] Eigene Domain"])

    def test_leaves_links_untranslated(self):
        request = self.translate_objects(self.product)

        contents = [item["Content"] for group in request.request_content["Groups"] for item in group["Items"]]
        self.assertNotIn("https://eqipe.ch", contents)
        self.assertEqual(Product.objects.language("en").get(pk=self.product.pk).website, "")

    def test_leaves_the_source_language_alone(self):
        self.translate_objects(self.product)

        german = Product.objects.language("de").get(pk=self.product.pk)
        self.assertEqual(german.name, "Speicher")
        self.assertEqual(self.features[0].safe_translation_getter("label", language_code="de"), "Tägliches Backup")


class AppBulkActionTestCase(TranslationTestCase):
    def test_creates_a_request_with_quotes(self):
        products = [create_translated(Product, name="Speicher"), create_translated(Product, name="Backup")]

        with self.login_user_context(self.user), mock_provider(QUOTE):
            response = self.client.post(
                reverse("admin:test_app_product_changelist"),
                {"action": "translate_in_bulk_en", "_selected_action": [product.pk for product in products]},
            )

        self.assertEqual(response.status_code, 302)
        request = AppTranslationRequest.objects.get()
        self.assertEqual(request.target_language, "en")
        self.assertEqual(request.state, AppTranslationRequest.STATES.PENDING_APPROVAL)
        self.assertCountEqual(request.items.values_list("link_object_id", flat=True), [p.pk for p in products])
        self.assertEqual(len(json.loads(request.export_fields)), 2)

    def test_choosing_a_quote_submits_the_request(self):
        product = create_translated(Product, name="Speicher")
        with self.login_user_context(self.user), mock_provider(QUOTE):
            self.client.post(
                reverse("admin:test_app_product_changelist"),
                {"action": "translate_in_bulk_en", "_selected_action": [product.pk]},
            )
        request = AppTranslationRequest.objects.get()

        with self.login_user_context(self.user), mock_provider() as provider:
            self.client.post(
                reverse("admin:choose-app-translation-quote", args=[request.pk]),
                {"selected_quote": request.quotes.get().pk},
            )

        request.refresh_from_db()
        self.assertEqual(request.state, AppTranslationRequest.STATES.IN_TRANSLATION)
        sent = provider.call_args.kwargs["json"]
        self.assertEqual(sent["OrderTypeId"], 2)
        self.assertEqual(provider.call_args.kwargs["url"], "http://ai-utils.test/order")
