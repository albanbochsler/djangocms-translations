from django.conf import settings


TRANSLATIONS_CONF = getattr(settings, 'DJANGOCMS_TRANSLATIONS_CONF', {})
TRANSLATIONS_USE_STAGING = getattr(settings, 'DJANGOCMS_TRANSLATIONS_USE_STAGING', True)