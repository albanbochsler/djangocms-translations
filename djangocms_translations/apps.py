from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DjangocmsTranslationsConfig(AppConfig):
    name = 'djangocms_translations'
    verbose_name = _('django CMS Translations')
    # The migrations use AutoField; pinning it keeps a project's DEFAULT_AUTO_FIELD from altering them.
    default_auto_field = 'django.db.models.AutoField'
