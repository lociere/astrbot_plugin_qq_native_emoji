"""Synthetic metadata only: no QQ accounts, resource URLs, keys, or artwork."""

import json
import tempfile
import unittest
from pathlib import Path

from native_emoji.catalog import (
    Catalog,
    EmojiError,
    Entry,
    clean_label,
    digits,
    favorite_entry,
    market_entry,
    parse_face_config,
    parse_incoming,
)

FACE_CONFIG = {
    "sysface": [{"QSid": "14", "QDes": "/微笑"}, {"QSid": "invalid"}, None],
    "emoji": [{"QSid": "😋", "QDes": "/美味", "QCid": "128523"}],
}
MARKET = {
    "emoji_package_id": 10,
    "emoji_id": "synthetic-id",
    "key": "synthetic-key",
    "summary": "开心",
}
FAVORITE = {
    "md5": "a" * 32,
    "resId": "synthetic-resource",
    "url": "https://example.invalid/a.gif",
    "desc": "开心",
    "isMarkFace": False,
}


class ParserTests(unittest.TestCase):
    def test_qq_resource_uses_qsid_and_separates_unicode(self):
        faces = parse_face_config(FACE_CONFIG)
        self.assertEqual([e.id for e in faces], ["face:14", "unicode:1f60b"])
        self.assertEqual(faces[0].segment, {"type": "face", "data": {"id": "14"}})
        self.assertEqual(faces[1].segment["data"]["text"], "😋")

    def test_reject_non_qq_catalog(self):
        for value in [[], {"images": []}, {"sysface": "fake"}]:
            with self.subTest(value=value), self.assertRaises(EmojiError):
                parse_face_config(value)

    def test_malformed_optional_unicode_section_does_not_drop_faces(self):
        self.assertEqual(len(parse_face_config({**FACE_CONFIG, "emoji": None})), 1)

    def test_both_market_input_shapes_keep_native_metadata(self):
        for kind in ["mface", "image"]:
            entry = parse_incoming([{"type": kind, "data": MARKET}], "chat-a")[0]
            self.assertEqual(entry.segment["type"], "mface")
            self.assertEqual(entry.segment["data"]["key"], "synthetic-key")
            self.assertEqual(entry.scope, "chat-a")
            self.assertNotIn("key", json.dumps(entry.public()))

    def test_partial_market_never_becomes_an_ordinary_image(self):
        self.assertEqual(parse_incoming([{"type": "image", "data": {"emoji_id": "x"}}], "a"), [])
        with self.assertRaises(EmojiError):
            market_entry({**MARKET, "key": ""}, "a")

    def test_plain_image_is_not_a_learnable_native_sticker(self):
        self.assertEqual(
            parse_incoming([{"type": "image", "data": {"url": "https://example.invalid/x"}}], "a"),
            [],
        )

    def test_face_result_and_chain_survive(self):
        row = {"type": "face", "data": {"id": "14", "resultId": "2", "chainCount": 3}}
        entry = parse_incoming([row], "a")[0]
        self.assertEqual(entry.segment["data"], {"id": "14", "resultId": "2", "chainCount": 3})

    def test_malformed_input_does_not_break_listener(self):
        bad = [
            None,
            "CQ:image",
            {"data": 2},
            {"type": "face", "data": {"id": []}},
            {"type": "face", "data": {"id": "14", "raw": "not-an-object"}},
        ]
        self.assertEqual(parse_incoming(bad, "a"), [])

    def test_favorite_is_custom_sticker_and_has_stable_identity(self):
        entry = favorite_entry(FAVORITE)
        refreshed = favorite_entry({**FAVORITE, "url": "https://example.invalid/refreshed.gif"})
        self.assertEqual(entry.id, refreshed.id)
        self.assertEqual(entry.segment["data"]["sub_type"], 1)
        self.assertNotIn("url", json.dumps(entry.public()))

    def test_res_id_identity_when_md5_missing(self):
        self.assertTrue(favorite_entry({**FAVORITE, "md5": ""}).id.startswith("favorite:"))

    def test_market_favorite_is_not_coerced_to_image(self):
        for flag in [True, 1, "1", "true"]:
            self.assertIsNone(favorite_entry({**FAVORITE, "isMarkFace": flag}))

    def test_no_arbitrary_files_or_unsupported_urls(self):
        for url in [
            "https://[invalid-ipv6/x",
            "file:///etc/passwd",
            "base64://x",
            "javascript:alert(1)",
            "/some/file",
            "https://user:pass@example.invalid/x",
        ]:
            self.assertIsNone(favorite_entry({**FAVORITE, "url": url}))

    def test_labels_are_bounded_and_control_characters_removed(self):
        self.assertEqual(clean_label("/开心\n\x00"), "开心")
        self.assertEqual(len(clean_label("x" * 1000)), 80)

    def test_numeric_fields_reject_negative_float_and_injection(self):
        for value in [-1, "1.2", "14,text=x", "9" * 100, True, None]:
            with self.subTest(value=value), self.assertRaises(EmojiError):
                digits(value, "id")


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalog = Catalog(Path(self.tmp.name), "platform-a:bot-a")

    def test_account_and_platform_isolation(self):
        self.catalog.remember(market_entry(MARKET, "chat-a"))
        self.catalog.save()
        for identity in ["platform-a:bot-b", "platform-b:bot-a"]:
            other = Catalog(Path(self.tmp.name), identity)
            other.load()
            self.assertFalse(other.entries)

    def test_chat_isolation_and_persistence(self):
        entry = market_entry(MARKET, "chat-a")
        self.catalog.remember(entry)
        self.catalog.save()
        restored = Catalog(Path(self.tmp.name), "platform-a:bot-a")
        restored.load()
        self.assertEqual(restored.get(entry.id, "chat-a"), entry)
        self.assertEqual(restored.search("", "all", "chat-b"), [])
        with self.assertRaises(EmojiError):
            restored.get(entry.id, "chat-b")

    def test_scope_override_preserves_learned_chain_parameters(self):
        global_entry = parse_face_config(FACE_CONFIG)[0]
        self.catalog.remember(global_entry)
        scoped = Entry(
            global_entry.id,
            "face",
            "learned",
            {"type": "face", "data": {"id": "14", "chainCount": 2}},
            "received_face",
            "chat-a",
        )
        self.catalog.remember(scoped)
        self.assertEqual(self.catalog.get("face:14", "chat-a"), scoped)
        self.assertEqual(len(self.catalog.search("", "face", "chat-a")), 1)
        self.assertEqual(self.catalog.get("face:14", "chat-b"), global_entry)

    def test_replace_removes_deleted_favorite_but_keeps_market(self):
        market = market_entry(MARKET, "a")
        self.catalog.remember(market)
        self.catalog.remember(favorite_entry(FAVORITE))
        self.catalog.replace({"qq_favorites"}, [])
        self.assertEqual(list(self.catalog.entries.values()), [market])

    def test_unicode_search_and_bounded_results(self):
        for entry in parse_face_config(FACE_CONFIG):
            self.catalog.remember(entry)
        self.assertEqual(self.catalog.search("😋", "unicode", "a")[0]["id"], "unicode:1f60b")
        self.assertEqual(len(self.catalog.search("", "all", "a", 1)), 1)
        with self.assertRaises(EmojiError):
            self.catalog.search("", "not-a-family", "a")

    def test_corrupt_or_mismatched_cache_fails_closed(self):
        self.catalog.path.write_text('{"version": 1, "account": "other"}', encoding="utf-8")
        with self.assertRaises(EmojiError):
            self.catalog.load()
