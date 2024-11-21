from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DjangocmsTranslationsConfig(AppConfig):
    name = 'djangocms_translations'
    verbose_name = _('django CMS Translations')
