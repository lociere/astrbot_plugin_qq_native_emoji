import unittest

from native_emoji.catalog import EmojiError
from native_emoji.policy import EmojiPolicy


class PolicyTests(unittest.TestCase):
    def test_desire_defaults_and_each_guidance_band(self):
        self.assertEqual(EmojiPolicy({}).desire, 50)
        for number, label in (
            (0, "关闭自动使用"),
            (1, "极少使用"),
            (20, "极少使用"),
            (21, "克制使用"),
            (40, "克制使用"),
            (41, "自然使用"),
            (60, "自然使用"),
            (61, "积极使用"),
            (80, "积极使用"),
            (81, "很积极使用"),
            (100, "很积极使用"),
        ):
            with self.subTest(number=number):
                policy = EmojiPolicy({"emoji_desire": number})
                self.assertEqual(policy.tendency, label)
                self.assertIn(f"{number}/100", policy.guidance())
                self.assertEqual(policy.public()["emoji_desire"], number)

    def test_invalid_desire_is_rejected(self):
        for value in (-1, 101, 50.0, "50", None, True, False):
            with self.subTest(value=value), self.assertRaises(EmojiError):
                EmojiPolicy({"emoji_desire": value}).guidance()

    def test_zero_disables_automatic_only_including_plain_unicode(self):
        policy = EmojiPolicy({"emoji_desire": 0})
        self.assertEqual(policy.order(), [])
        self.assertEqual(policy.order(False), ["favorite", "market", "face", "unicode"])
        self.assertFalse(policy.public()["automatic_emoji_enabled"])
        self.assertEqual(policy.clean_text("真的吗？😋……"), "真的吗？……")
        self.assertEqual(policy.clean_text("真的吗？😋……", automatic=False), "真的吗？😋……")
        with self.assertRaisesRegex(EmojiError, "倾向为0"):
            policy.require("favorite")
        policy.require("favorite", automatic=False)

    def test_high_desire_cannot_override_disabled_types_or_fallback(self):
        policy = EmojiPolicy(
            {"emoji_desire": 100, "enable_favorites": False, "fallback_to_other_types": False}
        )
        self.assertEqual(policy.order(), ["market"])
        self.assertEqual(policy.clean_text("好😋"), "好")
        with self.assertRaises(EmojiError):
            policy.require("favorite", automatic=False)
        with self.assertRaises(EmojiError):
            policy.require("face")

    def test_positive_desire_preserves_permissions_and_does_not_add_random_gates(self):
        for value in (1, 25, 50, 75, 100):
            policy = EmojiPolicy({"emoji_desire": value})
            self.assertEqual(policy.order(), ["favorite", "market", "face", "unicode"])
            self.assertTrue(policy.public()["automatic_emoji_enabled"])
            self.assertIn("不是发送概率", policy.guidance())
            for family in policy.order():
                policy.require(family)

    def test_desire_reads_live_settings_in_cached_policy(self):
        settings = {"emoji_desire": 80}
        policy = EmojiPolicy(settings)
        settings["emoji_desire"] = 0
        self.assertEqual(policy.order(), [])
        settings["emoji_desire"] = 20
        self.assertEqual(policy.tendency, "极少使用")

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
