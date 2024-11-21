from .gpt import GptTranslationProvider
from .deepl import DeeplProvider
from .supertext import SupertextTranslationProvider

TRANSLATION_PROVIDERS = {
    cls.__name__: cls
    for cls in (
        SupertextTranslationProvider,
        GptTranslationProvider,
        DeeplProvider,
    )
}
