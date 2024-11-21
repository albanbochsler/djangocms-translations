from django.conf import settings

TRANSLATIONS_CONF = getattr(settings, 'DJANGOCMS_TRANSLATIONS_CONF', {})
TRANSLATIONS_USE_STAGING = getattr(settings, 'DJANGOCMS_TRANSLATIONS_USE_STAGING', True)
TRANSLATIONS_BULK_BATCH_SIZE = getattr(settings, 'DJANGOCMS_TRANSLATIONS_BULK_BATCH_SIZE', 100)
TRANSLATIONS_INLINE_CONF = getattr(settings, 'DJANGOCMS_TRANSLATIONS_INLINE_CONF', {})
TRANSLATIONS_PAGE_CONF = getattr(settings, 'DJANGOCMS_TRANSLATIONS_PAGE_CONF', {})
TRANSLATIONS_TITLE_EXTENSION = getattr(settings, 'DJANGOCMS_TRANSLATIONS_TITLE_EXTENSION',
                                       {"app_label": "config", "model_name": "allinktitleextension"})

LANGUAGE_MAPPING = {
    'ch-de': 'de-CH',
    'ch-fr': 'fr-CH',
    'da': 'da-DK',
    'de': 'de-CH',
    'en': 'en-US',
    'es': 'es-ES',
    'es-xl': 'es-419',
    'fi': 'fi-FI',
    'fr': 'fr-CH',
    'it': 'it-CH',
    'ja': 'ja-JP',
    'nb': 'nb-NO',
    'nl': 'nl-NL',
    'pl': 'pl-PL',
    'ru': 'ru-RU',
    'sk': 'sk-SK',
    'sv': 'sv-SE',
}
