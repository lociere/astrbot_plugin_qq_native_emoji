"""Run manually with the real AstrBot SDK installed; uses no live platform or network.

PYTHONPATH=/path/to/AstrBot python tests/sdk_smoke.py
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from astrbot.core.provider.register import llm_tools  # noqa: E402
from test_catalog import FACE_CONFIG, MARKET  # noqa: E402
from test_service import FakeNapCat  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "qq_native_sdk_smoke", ROOT / "main.py", submodule_search_locations=[str(ROOT)]
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Event:
    def __init__(self, api):
        self.bot = SimpleNamespace(call_action=api)
        self.extras = {}
        self.unified_msg_origin = "synthetic-platform:FriendMessage:100"
        self.message_obj = SimpleNamespace(raw_message={})

    def get_platform_name(self):
        return "aiocqhttp"

    def get_platform_id(self):
        return "synthetic-platform"

    def get_self_id(self):
        return "synthetic-bot"

    def is_admin(self):
        return True

    def get_group_id(self):
        return ""

    def get_sender_id(self):
        return "100"

    def is_private_chat(self):
        return True

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value


async def smoke():
    tools = {t.name: t for t in llm_tools.func_list if t.name.startswith("qq_native_emoji_")}
    assert set(tools) == {"qq_native_emoji_search", "qq_native_emoji_send"}
    for name, expected in {
        "qq_native_emoji_search": {"query", "family", "limit"},
        "qq_native_emoji_send": {"emoji_id", "text", "result_id", "chain_count"},
    }.items():
        assert set(tools[name].parameters["properties"]) == expected, name
    with tempfile.TemporaryDirectory() as tmp:
        resource = Path(tmp) / "synthetic-face-resource.json"
        resource.write_text(json.dumps(FACE_CONFIG), encoding="utf-8")
        with patch.object(module.StarTools, "get_data_dir", return_value=Path(tmp)):
            plugin = module.QQNativeEmoji(
                SimpleNamespace(), {"face_config_paths": [str(resource)], "cooldown_seconds": 0}
            )
        api = FakeNapCat()
        event = Event(api)
        searched = json.loads(await plugin.search_tool(event, "微笑", "face", 12))
        assert searched["entries"][0]["id"] == "face:14"
        sent = json.loads(await plugin.send_tool(event, "face:14", "真的吗？"))
        assert sent["status"] == "sent"
        duplicate = json.loads(await plugin.send_tool(event, "face:14", "真的吗？"))
        assert duplicate["status"] == "already_attempted"
        quota = json.loads(await plugin.send_tool(event, "unicode:1f60b"))
        assert quota["status"] == "error_or_uncertain"
        assert sum(name.startswith("send_") for name, _ in api.calls) == 2
        # Source group metadata in a temporary private session must not reroute to that group.
        temporary = Event(api)
        temporary.get_group_id = lambda: "200"
        await plugin.send_tool(temporary, "face:14")
        assert api.calls[-1][0] == "send_private_msg"
        assert "group_id" not in api.calls[-1][1]
        event2 = Event(api)
        event2.message_obj.raw_message = {"message": [{"type": "image", "data": MARKET}]}
        request = SimpleNamespace(system_prompt="original persona", prompt="original message")
        await plugin.describe_incoming(event2, request)
        assert request.system_prompt.startswith("original persona")
        assert "market:10:synthetic-id" in request.prompt
        assert "synthetic-key" not in request.prompt
        assert not (await plugin._service(event2)).catalog.search(
            "", "market", event2.unified_msg_origin
        )
        from astrbot.api.event import MessageChain, MessageEventResult
        from astrbot.api.message_components import Plain
        from astrbot.api.provider import LLMResponse
        from astrbot.core.message.message_event_result import ResultContentType

        plugin.config["enable_unicode"] = False
        response = LLMResponse("assistant", result_chain=MessageChain([Plain("真的吗？😋……")]))
        await plugin.filter_llm_unicode(event2, response)
        assert response.completion_text == "真的吗？……"
        result = (
            MessageEventResult()
            .message("收到👩‍🚀？")
            .set_result_content_type(ResultContentType.LLM_RESULT)
        )
        event2.get_result = lambda: result
        await plugin.filter_result_unicode(event2)
        assert result.get_plain_text() == "收到？"
        request = SimpleNamespace(system_prompt="original persona", prompt="original message")
        plugin.config["fallback_to_other_types"] = False
        await plugin.describe_incoming(event2, request)
        assert "首选类型没有合适候选时，只用文字回复" in request.system_prompt
        # Usage preference still reaches the model when the optional tool tutorial is off.
        plugin.config.update(emoji_desire=85, tool_guidance=False)
        request = SimpleNamespace(system_prompt="original persona", prompt="original message")
        await plugin.describe_incoming(event2, request)
        assert request.system_prompt.startswith("original persona")
        assert "85/100" in request.system_prompt
        assert "这不是发送概率" in request.system_prompt
        assert "发送工具已发送或可能已发送" not in request.system_prompt

        # A cached service must honor zero immediately, before any platform API operation.
        plugin.config.update(emoji_desire=0, enable_unicode=True, fallback_to_other_types=True)
        zero = Event(api)
        count_before = len(api.calls)
        hidden = json.loads(await plugin.search_tool(zero, "", "all", 12))
        assert hidden["entries"] == []
        assert hidden["policy"]["emoji_desire"] == 0
        refused = json.loads(await plugin.send_tool(zero, "face:14", "不应发送的文字"))
        assert refused["status"] == "error_or_uncertain"
        assert len(api.calls) == count_before
        response = LLMResponse("assistant", "真的吗？😋……")
        await plugin.filter_llm_unicode(zero, response)
        assert response.completion_text == "真的吗？……"
        request = SimpleNamespace(system_prompt="original persona", prompt="original message")
        await plugin.describe_incoming(zero, request)
        assert "0/100" in request.system_prompt and "只使用文字" in request.system_prompt

        # Explicit manual sends remain permitted and retain the original message layout.
        manual = Event(api)
        sent = await plugin._send(manual, "face:14", automatic=False)
        assert sent["status"] == "sent"
        assert api.calls[-1][1]["message"] == [{"type": "face", "data": {"id": "14"}}]
        # SDK imports and handlers exercised in an isolated interpreter, not a running bot.
        await plugin.terminate()
    print(
        "AstrBot SDK smoke passed: tool schemas, handlers, quota, deduplication, incoming privacy"
    )


if __name__ == "__main__":
    asyncio.run(smoke())
