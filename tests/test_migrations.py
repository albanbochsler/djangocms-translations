from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings


class MigrationTestCase(TestCase):
    @override_settings(MIGRATION_MODULES={})
    def test_for_missing_migrations(self):
        output = StringIO()
        try:
            call_command(
                "makemigrations", "djangocms_translations", check=True, dry_run=True, interactive=False, stdout=output
            )
        except SystemExit:
            self.fail(f"There are missing migrations:\n {output.getvalue()}")
