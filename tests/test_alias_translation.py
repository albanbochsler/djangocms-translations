from cms.api import add_plugin

from djangocms_alias.models import Alias, AliasContent, Category
from djangocms_text_ckeditor.models import Text
from djangocms_versioning.models import Version

from djangocms_translations.models import AppTranslationRequest

from .base import TranslationTestCase


class AliasTranslationTestCase(TranslationTestCase):
    def setUp(self):
        super().setUp()
        self.alias = Alias.objects.create(category=Category.objects.create(name="Layout"), position=0)

    def add_content(self, language, body, publish=True):
        content = AliasContent.objects.with_user(self.user).create(alias=self.alias, language=language, name="Footer")
        add_plugin(content.placeholder, "TextPlugin", language, body=body)
        if publish:
            Version.objects.get_for_content(content).publish(self.user)
        return content

    def versions(self, language="en"):
        return Version.objects.filter_by_content_grouping_values(AliasContent(alias=self.alias, language=language))

    def body(self, content):
        return Text.objects.get(placeholder=content.placeholder, language=content.language).body

    def test_translates_a_draft_alias(self):
        source = self.add_content("de", "<p>Adresse</p>", publish=False)

        request = self.translate_objects(source)

        self.assertEqual(request.state, AppTranslationRequest.STATES.IMPORTED)
        draft = self.versions().get(state="draft").content
        self.assertEqual(self.body(draft), "[en] <p>Adresse</p>")

    def test_copies_the_published_translation_into_a_new_draft(self):
        source = self.add_content("de", "<p>Adresse</p>")
        published = self.add_content("en", "<p>Address</p>")

        self.translate_objects(source)

        self.assertEqual(self.body(published), "<p>Address</p>")
        draft = self.versions().get(state="draft").content
        self.assertNotEqual(draft.pk, published.pk)
        self.assertEqual(self.body(draft), "[en] <p>Adresse</p>")

    def test_writes_into_the_existing_draft(self):
        source = self.add_content("de", "<p>Adresse</p>")
        published = self.add_content("en", "<p>Address</p>")
        draft = Version.objects.get_for_content(published).copy(self.user).content

        self.translate_objects(source)

        self.assertEqual(self.versions().count(), 2)
        self.assertEqual(self.body(draft), "[en] <p>Adresse</p>")
        self.assertEqual(self.body(published), "<p>Address</p>")
