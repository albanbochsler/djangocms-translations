#!/usr/bin/env python
HELPER_SETTINGS = {
    "SECRET_KEY": "djangocms-translations-test-suite",
    "INSTALLED_APPS": [
        "parler",
        "djangocms_text_ckeditor",
        "djangocms_versioning",
        "djangocms_alias",
        "tests.test_app",
    ],
    "LANGUAGE_CODE": "de",
    "LANGUAGES": (
        ("de", "Deutsch"),
        ("en", "English"),
    ),
    "CMS_LANGUAGES": {
        1: [
            {"code": "de", "name": "Deutsch"},
            {"code": "en", "name": "English", "fallbacks": ["de"]},
        ],
    },
    "PARLER_LANGUAGES": {
        1: ({"code": "de"}, {"code": "en"}),
        "default": {"fallbacks": ["de"], "hide_untranslated": False},
    },
    "PARLER_ENABLE_CACHING": False,
    "DJANGOCMS_TRANSLATIONS_CONF": {
        "TextPlugin": {"fields": ["body"]},
        "LinkPlugin": {"fields": ["label"], "text_field_child_label": "label"},
    },
    "DJANGOCMS_TRANSLATIONS_INLINE_CONF": {
        "feature": {"fields": ["label"], "related_path": ["features"]},
    },
    "DJANGOCMS_TRANSLATIONS_TITLE_EXTENSION": {"app_label": "test_app", "model_name": "pagetitleextension"},
    "DEFAULT_TRANSLATION_PROVIDER": "GptTranslationProvider",
    "ACTIVE_TRANSLATION_PROVIDERS": ("djangocms_translations.providers.GptTranslationProvider",),
    "DJANGOCMS_TRANSLATIONS_USE_STAGING": True,
    "DJANGOCMS_TRANSLATIONS_API_STAGE_URL": "http://ai-utils.test",
}


def run():
    from app_helper import runner

    runner.cms("djangocms_translations", extra_args=[])


if __name__ == "__main__":
    run()
