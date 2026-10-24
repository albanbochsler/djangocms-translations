from django.db import models

from cms.extensions import PageContentExtension, extension_pool
from cms.models import CMSPlugin

from parler.models import TranslatableModel, TranslatedFields


class PageTitleExtension(PageContentExtension):
    """The title extension the translations conf points at, like a project's SEO extension."""

    og_title = models.CharField(max_length=255, blank=True)
    hero_lead = models.TextField(blank=True)


extension_pool.register(PageTitleExtension)


class Link(CMSPlugin):
    """A child plugin of text, whose label travels inside the text body."""

    label = models.CharField(max_length=255)


class Product(TranslatableModel):
    """A parler app model, the shape of a project's news or price table."""

    translations = TranslatedFields(
        name=models.CharField(max_length=255),
        description=models.TextField(blank=True),
        website=models.URLField(blank=True),
    )


class Feature(TranslatableModel):
    """An inline of Product, reached through DJANGOCMS_TRANSLATIONS_INLINE_CONF."""

    product = models.ForeignKey(Product, related_name="features", on_delete=models.CASCADE)
    translations = TranslatedFields(
        label=models.CharField(max_length=255, blank=True),
    )
