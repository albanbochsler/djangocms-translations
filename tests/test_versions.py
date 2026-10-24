from djangocms_versioning.constants import ARCHIVED, DRAFT, PUBLISHED, UNPUBLISHED
from djangocms_versioning.models import Version

from djangocms_translations.models import TranslationRequest
from djangocms_translations.utils import get_working_version

from .base import TranslationTestCase


class GetWorkingVersionTestCase(TranslationTestCase):
    def setUp(self):
        super().setUp()
        self.page = self.create_page()
        self.published = Version.objects.get_for_content(self.add_translation(self.page))

    def versions(self):
        return self.page_versions(self.page)

    def states(self):
        return set(self.versions().values_list("state", flat=True))

    def test_prefers_the_draft(self):
        draft = self.published.copy(self.user)

        self.assertEqual(get_working_version(self.versions()), draft)

    def test_falls_back_to_the_published_version(self):
        self.published.copy(self.user).archive(self.user)

        self.assertEqual(self.states(), {PUBLISHED, ARCHIVED})
        self.assertEqual(get_working_version(self.versions()), self.published)

    def test_falls_back_to_the_newest_version(self):
        self.published.unpublish(self.user)
        newest = Version.objects.get(pk=self.published.pk).copy(self.user)
        newest.archive(self.user)

        self.assertEqual(self.states(), {UNPUBLISHED, ARCHIVED})
        self.assertEqual(get_working_version(self.versions()), newest)

    def test_returns_none_without_versions(self):
        self.assertIsNone(get_working_version(Version.objects.none()))


class GetTargetDraftTestCase(TranslationTestCase):
    def setUp(self):
        super().setUp()
        self.request = TranslationRequest(user=self.user, source_language="de", target_language="en")

    def test_creates_the_target_content_when_missing(self):
        page = self.create_page()

        version = self.request.get_target_draft(page, self.user, "de", "en")

        self.assertEqual(version.state, DRAFT)
        self.assertEqual(version.content.language, "en")
        self.assertEqual(version.content.title, "Startseite")

    def test_returns_none_without_source_content(self):
        page = self.create_page()

        self.assertIsNone(self.request.get_target_draft(page, self.user, "fr", "en"))
