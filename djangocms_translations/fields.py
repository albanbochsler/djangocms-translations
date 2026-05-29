from django.db import models


class DynamicChoiceCharField(models.CharField):
    """A ``CharField`` whose ``choices`` are derived from project settings.

    ``choices`` drive the form widgets, validation and ``get_<field>_display()``
    at runtime, but they have no effect on the database column. Django's
    ``deconstruct()`` normally bakes the evaluated choices into migrations, so
    every project with different ``LANGUAGES`` / ``ACTIVE_TRANSLATION_PROVIDERS``
    would generate a fresh, schema-irrelevant ``AlterField`` migration.

    This field strips ``choices`` from ``deconstruct()`` so the migration state
    is identical across projects and the autodetector stays silent.
    """

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("choices", None)
        return name, path, args, kwargs
