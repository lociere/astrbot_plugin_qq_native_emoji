import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from test_catalog import FACE_CONFIG, FAVORITE, MARKET

from native_emoji.catalog import Catalog, EmojiError, market_entry
from native_emoji.service import EmojiService, unwrap


class FakeNapCat:
    def __init__(self):
        self.calls = []
        self.favorites = [FAVORITE]
        self.error = None
        self.response = {"message_id": 123}

    async def __call__(self, name, **params):
        self.calls.append((name, params))
        if name == "get_version_info":
            return {"app_name": "NapCat.Onebot", "app_version": "synthetic-version"}
        if name == "fetch_custom_face_detail":
            if self.error == "favorites":
                raise RuntimeError("private URL must never be exposed")
            return self.favorites
        if name.startswith("send_"):
            if self.error == "send":
                raise RuntimeError("secret-token=synthetic")
            if self.error == "timeout":
                raise asyncio.TimeoutError
            return self.response
        raise AssertionError(name)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        directory = Path(self.tmp.name)
        resource = directory / "synthetic-resource.json"
        resource.write_text(json.dumps(FACE_CONFIG), encoding="utf-8")
        self.service = EmojiService(
            Catalog(directory, "platform:bot"),
            {
                "face_config_paths": [str(resource)],
                "favorite_count": 1000,
                "cooldown_seconds": 0,
            },
        )
        self.api = FakeNapCat()

    async def test_zero_desire_auto_search_does_not_read_napcat(self):
        self.service.settings["emoji_desire"] = 0
        for family in ("all", "favorite", "face", "unicode", "market"):
            result = await self.service.search(self.api, "", family, "a")
            self.assertEqual(result["entries"], [])
            self.assertEqual(result["policy"]["emoji_desire"], 0)
        self.assertEqual(self.api.calls, [])
        manual = await self.service.search(self.api, "", "face", "a", automatic=False)
        self.assertTrue(manual["entries"])

    async def test_zero_desire_rejects_automatic_send_before_text_or_api(self):
        self.service.settings["emoji_desire"] = 0
        with self.assertRaisesRegex(EmojiError, "倾向为0"):
            await self.service.send(self.api, "face:14", "a", {"user_id": "100"}, "文字")
        self.assertEqual(self.api.calls, [])
        await self.service.send(self.api, "face:14", "a", {"user_id": "100"}, automatic=False)
        self.assertEqual(sum(name.startswith("send_") for name, _ in self.api.calls), 1)

    async def test_high_desire_does_not_bypass_existing_cooldown(self):
        self.service.settings.update(emoji_desire=100, cooldown_seconds=10)
        await self.service.send(self.api, "face:14", "a", {"user_id": "100"})
        with self.assertRaisesRegex(EmojiError, "间隔"):
            await self.service.send(self.api, "face:14", "a", {"user_id": "100"})

    async def test_refresh_uses_explicit_collection_limit(self):
        status = await self.service.refresh(self.api)
        self.assertEqual(status["resource_entries"], 2)
        self.assertEqual(status["favorite_entries"], 1)
        self.assertIn(("fetch_custom_face_detail", {"count": 1000}), self.api.calls)

    async def test_concurrent_refresh_is_coalesced(self):
        await asyncio.gather(*(self.service.refresh(self.api) for _ in range(10)))
        self.assertEqual(sum(name == "fetch_custom_face_detail" for name, _ in self.api.calls), 1)

    async def test_native_and_text_are_two_ordered_private_messages(self):
        reply = await self.service.send(
            self.api, "face:14", "chat-a", {"user_id": "100"}, "是吗？……"
        )
        sends = [(name, args) for name, args in self.api.calls if name.startswith("send_")]
        self.assertEqual(len(sends), 2)
        name, args = sends[0]
        self.assertEqual(name, "send_private_msg")
        self.assertEqual(
            args["message"],
            [
                {"type": "text", "data": {"text": "是吗？……"}},
            ],
        )
        self.assertEqual(sends[1][1]["message"], [{"type": "face", "data": {"id": "14"}}])
        self.assertEqual(reply["layout"], "separate")
        self.assertEqual(len(reply["message_ids"]), 2)
        self.assertEqual(reply["status"], "sent")
        self.assertEqual(reply["message_id"], "123")

    async def test_group_native_send_preserves_result_and_chain(self):
        await self.service.send(
            self.api, "face:14", "chat-a", {"group_id": "200"}, result_id="2", chain_count=3
        )
        name, args = self.api.calls[-1]
        self.assertEqual(name, "send_group_msg")
        self.assertNotIn("user_id", args)
        self.assertEqual(args["message"][0]["data"], {"id": "14", "resultId": "2", "chainCount": 3})

    async def test_market_send_never_uses_image(self):
        entry = market_entry(MARKET, "chat-a")
        self.service.catalog.remember(entry)
        await self.service.send(self.api, entry.id, "chat-a", {"user_id": "100"})
        segment = self.api.calls[-1][1]["message"][0]
        self.assertEqual(segment["type"], "mface")
        self.assertEqual(segment["data"]["key"], MARKET["key"])

    async def test_favorite_is_revalidated_and_retains_sticker_subtype(self):
        await self.service.refresh(self.api)
        self.api.favorites = [{**FAVORITE, "url": "https://example.invalid/new.gif"}]
        await self.service.send(self.api, "favorite:" + "a" * 32, "chat-a", {"user_id": "100"})
        segment = self.api.calls[-1][1]["message"][0]
        self.assertEqual(segment["data"]["sub_type"], 1)
        self.assertEqual(segment["data"]["file"], "https://example.invalid/new.gif")

    async def test_deleted_favorite_cannot_send_from_old_cache(self):
        await self.service.refresh(self.api)
        self.api.favorites = []
        with self.assertRaises(EmojiError):
            await self.service.send(self.api, "favorite:" + "a" * 32, "chat-a", {"user_id": "100"})
        self.assertFalse(any(name.startswith("send_") for name, _ in self.api.calls))

    async def test_unsupported_favorites_degrade_without_fake_success(self):
        self.api.error = "favorites"
        status = await self.service.refresh(self.api)
        self.assertFalse(status["favorites_available"])
        self.assertEqual(status["resource_entries"], 2)
        self.assertNotIn("private URL", json.dumps(status))
        await self.service.send(self.api, "face:14", "chat-a", {"user_id": "100"})

    async def test_collection_truncation_is_reported(self):
        self.service.settings["favorite_count"] = 1
        self.assertTrue((await self.service.refresh(self.api))["favorites_may_be_truncated"])

    async def test_missing_message_id_does_not_claim_success(self):
        self.api.response = {}
        with self.assertRaisesRegex(EmojiError, "message_id"):
            await self.service.send(self.api, "face:14", "chat-a", {"user_id": "100"})

    async def test_failed_action_is_not_success(self):
        self.api.response = {"status": "failed", "retcode": 1200, "data": None}
        with self.assertRaises(EmojiError):
            await self.service.send(self.api, "face:14", "chat-a", {"user_id": "100"})

    async def test_timeout_no_retry_and_no_claim_of_success(self):
        self.api.error = "timeout"
        with self.assertRaisesRegex(EmojiError, "不会自动重试"):
            await self.service.send(self.api, "face:14", "chat-a", {"user_id": "100"})
        self.assertEqual(sum(name.startswith("send_") for name, _ in self.api.calls), 1)

    async def test_exceptions_do_not_leak_request_secrets(self):
        self.api.error = "send"
        with self.assertRaises(EmojiError) as ctx:
            await self.service.send(self.api, "face:14", "chat-a", {"user_id": "100"})
        self.assertNotIn("synthetic", str(ctx.exception))

    async def test_cooldown_enforced_for_same_session(self):
        self.service.settings["cooldown_seconds"] = 10
        await self.service.send(self.api, "face:14", "a", {"user_id": "100"})
        with self.assertRaisesRegex(EmojiError, "间隔"):
            await self.service.send(self.api, "face:14", "a", {"user_id": "100"})
        await self.service.send(self.api, "face:14", "b", {"user_id": "200"})

    async def test_invalid_destination_and_unknown_id_do_not_send(self):
        for target in [{}, {"user_id": "100", "group_id": "200"}, {"user_id": "bad"}]:
            with self.subTest(target=target), self.assertRaises(EmojiError):
                await self.service.send(self.api, "face:14", "a", target)
        with self.assertRaises(EmojiError):
            await self.service.send(self.api, "face:999", "a", {"user_id": "100"})
        self.assertFalse(any(name.startswith("send_") for name, _ in self.api.calls))

    async def test_unsupported_backend_rejected(self):
        async def other(name, **params):
            return {"app_name": "other"}

        with self.assertRaisesRegex(EmojiError, "NapCat"):
            await self.service.refresh(other)

    async def test_unicode_remains_text(self):
        await self.service.send(self.api, "unicode:1f60b", "a", {"user_id": "100"})
        self.assertEqual(
            self.api.calls[-1][1]["message"], [{"type": "text", "data": {"text": "😋"}}]
        )

    async def test_native_parameters_not_applied_to_favorites(self):
        with self.assertRaises(EmojiError):
            await self.service.send(
                self.api, "favorite:" + "a" * 32, "a", {"user_id": "100"}, result_id="1"
            )

    async def test_unicode_with_text_stays_in_one_message(self):
        reply = await self.service.send(
            self.api, "unicode:1f60b", "a", {"user_id": "100"}, "好吃？"
        )
        sends = [args for name, args in self.api.calls if name.startswith("send_")]
        self.assertEqual(len(sends), 1)
        self.assertEqual([s["data"]["text"] for s in sends[0]["message"]], ["好吃？", "😋"])
        self.assertEqual(reply["layout"], "inline")

    async def test_favorite_and_market_always_get_their_own_bubble(self):
        market = market_entry(MARKET, "a")
        self.service.catalog.remember(market)
        for identity, kind in [("favorite:" + "a" * 32, "image"), (market.id, "mface")]:
            self.api.calls.clear()
            await self.service.send(self.api, identity, "a", {"group_id": "200"}, "真的吗？……")
            sends = [args for name, args in self.api.calls if name.startswith("send_")]
            self.assertEqual(len(sends), 2)
            self.assertEqual(
                sends[0]["message"], [{"type": "text", "data": {"text": "真的吗？……"}}]
            )
            self.assertEqual(len(sends[1]["message"]), 1)
            self.assertEqual(sends[1]["message"][0]["type"], kind)

    async def test_partial_failure_reports_delivered_text_without_retry(self):
        count = 0

        async def partial(name, **params):
            nonlocal count
            if name.startswith("send_"):
                count += 1
                if count == 2:
                    raise asyncio.TimeoutError
            return await self.api(name, **params)

        result = await self.service.send(partial, "face:14", "a", {"user_id": "100"}, "先发文字？")
        self.assertEqual(count, 2)
        self.assertEqual(result["status"], "partial_or_uncertain")
        self.assertEqual(result["text_status"], "sent")
        self.assertEqual(result["message_ids"], ["123"])
        self.assertEqual(result["emoji_status"], "unknown")

    async def test_text_timeout_does_not_attempt_sticker(self):
        self.api.error = "timeout"
        result = await self.service.send(self.api, "face:14", "a", {"user_id": "100"}, "文字？")
        self.assertEqual(result["status"], "error_or_uncertain")
        self.assertEqual(result["emoji_status"], "not_attempted")
        self.assertEqual(result["message_ids"], [])
        self.assertEqual(sum(name.startswith("send_") for name, _ in self.api.calls), 1)

    async def test_each_family_switch_blocks_cached_ids_and_accompanying_text(self):
        await self.service.refresh(self.api)
        market = market_entry(MARKET, "a")
        self.service.catalog.remember(market)
        from native_emoji.policy import SWITCHES

        for family, identity in [
            ("face", "face:14"),
            ("unicode", "unicode:1f60b"),
            ("market", market.id),
            ("favorite", "favorite:" + "a" * 32),
        ]:
            self.service.settings[SWITCHES[family]] = False
            self.api.calls.clear()
            with self.assertRaises(EmojiError):
                await self.service.send(self.api, identity, "a", {"user_id": "100"}, "不应该发出")
            self.assertEqual(self.api.calls, [])
            self.service.settings[SWITCHES[family]] = True

    async def test_default_priority_and_custom_priority_are_applied_before_limit(self):
        result = await self.service.search(self.api, "", "all", "a", limit=1)
        self.assertEqual(result["entries"][0]["family"], "favorite")
        self.service.settings["family_priority"] = ["unicode", "face", "favorite", "market"]
        result = await self.service.search(self.api, "", "all", "a", limit=1)
        self.assertEqual(result["entries"][0]["family"], "unicode")

    async def test_disabled_favorites_hidden_even_with_warm_cache(self):
        await self.service.refresh(self.api)
        self.service.settings["enable_favorites"] = False
        result = await self.service.search(self.api, "", "all", "a")
        self.assertFalse(any(e["family"] == "favorite" for e in result["entries"]))
        self.assertEqual(result["policy"]["preferred_family"], "market")

    async def test_no_fallback_blocks_lower_family_for_tools_but_not_manual_command(self):
        self.service.settings["fallback_to_other_types"] = False
        result = await self.service.search(self.api, "", "all", "a")
        self.assertEqual({e["family"] for e in result["entries"]}, {"favorite"})
        with self.assertRaises(EmojiError):
            await self.service.send(self.api, "face:14", "a", {"user_id": "100"})
        result = await self.service.send(
            self.api, "face:14", "a", {"user_id": "100"}, automatic=False
        )
        self.assertEqual(result["status"], "sent")

    async def test_no_preferred_match_can_return_empty_without_forcing_another_emoji(self):
        self.service.settings["fallback_to_other_types"] = False
        result = await self.service.search(self.api, "微笑", "all", "a")
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["policy"]["no_suitable_candidate"], "reply_with_text_without_emoji")

    async def test_unicode_switch_cleans_accompanying_text_but_keeps_punctuation(self):
        self.service.settings["enable_unicode"] = False
        result = await self.service.send(
            self.api, "face:14", "a", {"user_id": "100"}, "真的吗？😋……"
        )
        self.assertEqual(result["text"], "真的吗？……")
        self.assertEqual(self.api.calls[-2][1]["message"][0]["data"]["text"], "真的吗？……")


class EnvelopeTests(unittest.TestCase):
    def test_cqhttp_and_envelope(self):
        self.assertEqual(unwrap({"message_id": 1}), {"message_id": 1})
        self.assertEqual(
            unwrap({"status": "ok", "retcode": 0, "data": {"message_id": 1}}), {"message_id": 1}
        )
