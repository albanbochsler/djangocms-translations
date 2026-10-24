from django.contrib import admin

from parler.admin import TranslatableAdmin

from djangocms_translations.mixins.admin import TranslateAppBulkMixin

from .models import Product


@admin.register(Product)
class ProductAdmin(TranslateAppBulkMixin, TranslatableAdmin):
    pass
