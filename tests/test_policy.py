import unittest

from native_emoji.catalog import EmojiError
from native_emoji.policy import EmojiPolicy


class PolicyTests(unittest.TestCase):
    def test_defaults_and_disabled_family_skipping(self):
        self.assertEqual(EmojiPolicy({}).order(), ["favorite", "market", "face", "unicode"])
        self.assertEqual(
            EmojiPolicy({"enable_market": False}).order(), ["favorite", "face", "unicode"]
        )

    def test_custom_order_deduplicates_and_appends_missing_families(self):
        self.assertEqual(
            EmojiPolicy({"family_priority": ["face", "face"]}).order(),
            ["face", "favorite", "market", "unicode"],
        )

    def test_invalid_configuration_fails_with_actionable_error(self):
        for value in ["favorite", ["bad"], [None]]:
            with self.assertRaises(EmojiError):
                EmojiPolicy({"family_priority": value}).order()

    def test_all_families_can_be_disabled(self):
        p = EmojiPolicy(
            {
                "enable_faces": False,
                "enable_market": False,
                "enable_favorites": False,
                "enable_unicode": False,
            }
        )
        self.assertEqual(p.order(), [])
        self.assertIsNone(p.public()["preferred_family"])
        self.assertIn("只使用文字", p.guidance())

    def test_no_fallback_uses_first_enabled_family(self):
        p = EmojiPolicy({"enable_favorites": False, "fallback_to_other_types": False})
        self.assertEqual(p.order(), ["market"])
        self.assertIn("face", p.order(automatic=False))
        self.assertIn("不改用其他类型", p.guidance())

    def test_unicode_filter_handles_sequences_without_touching_normal_text(self):
        p = EmojiPolicy({"enable_unicode": False})
        for symbol in ["😋", "👩‍🚀", "👍🏽", "🇨🇳", "1️⃣", "❤️"]:
            self.assertEqual(p.clean_text("真的？" + symbol + "……20℃，100元"), "真的？……20℃，100元")

    def test_enabled_unicode_is_unchanged(self):
        self.assertEqual(EmojiPolicy({}).clean_text("可以😋？"), "可以😋？")

    def test_preferred_only_prevents_plain_unicode_fallback(self):
        p = EmojiPolicy({"fallback_to_other_types": False})
        self.assertEqual(p.clean_text("你好😋"), "你好")
        self.assertEqual(p.clean_text("你好😋", automatic=False), "你好😋")
