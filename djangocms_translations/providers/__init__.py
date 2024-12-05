from importlib import import_module

from .gpt import GptTranslationProvider
from .deepl import DeeplProvider
from .supertext import SupertextTranslationProvider
from django.conf import settings


def load_class_from_string(class_path):
    module_path, class_name = class_path.rsplit('.', 1)  # Split at the last dot
    module = import_module(module_path)  # Dynamically import the module
    return getattr(module, class_name)


ACTIVE_TRANSLATION_PROVIDERS = getattr(settings, 'ACTIVE_TRANSLATION_PROVIDERS', [
    'djangocms_translations.providers.SupertextTranslationProvider',
    'djangocms_translations.providers.GptTranslationProvider',
    'djangocms_translations.providers.DeeplProvider',
])


TRANSLATION_PROVIDERS = {
    load_class_from_string(cls).__name__: load_class_from_string(cls)
    for cls in ACTIVE_TRANSLATION_PROVIDERS
}

TRANSLATION_PROVIDER_CHOICES = (
    (load_class_from_string(cls).__name__, load_class_from_string(cls).NAME)
    for cls in ACTIVE_TRANSLATION_PROVIDERS
)
