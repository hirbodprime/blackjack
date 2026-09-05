from unittest import TestCase

from game.i18n import translate


class TranslationTests(TestCase):
    def test_english_translation(self):
        self.assertEqual(translate("play.back", "en"), "◀️ Back")

    def test_persian_translation(self):
        self.assertEqual(translate("play.back", "fa"), "◀️ بازگشت")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(translate("play.back", "de"), "◀️ Back")

    def test_unknown_key_is_visible_for_developers(self):
        self.assertEqual(translate("missing.key", "fa"), "missing.key")

    def test_translation_formats_values(self):
        self.assertEqual(
            translate("compact.changed", "en", state="on"),
            "Compact mode is now on.",
        )
