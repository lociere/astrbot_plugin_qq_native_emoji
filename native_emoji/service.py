"""Read QQ resources and send Unicode inline or native stickers as separate messages."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .catalog import Catalog, EmojiError, digits, favorite_entry, parse_face_config
from .policy import EmojiPolicy

Action = Callable[..., Awaitable[Any]]


def unwrap(result: Any) -> Any:
    """CQHttp returns action data; HTTP-style test/other clients may return an envelope."""
    if isinstance(result, dict) and ("retcode" in result or "status" in result):
        if result.get("status") == "failed" or result.get("retcode", 0) != 0:
            raise EmojiError("NapCat 拒绝了操作，请检查登录状态与接口支持")
        return result.get("data")
    return result


class EmojiService:
    def __init__(self, catalog: Catalog, settings: dict):
        self.catalog = catalog
        self.settings = settings
        self.policy = EmojiPolicy(settings)
        self.refresh_lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.refreshed_at = 0.0
        self.last_send: dict[str, float] = {}
        self.status: dict[str, Any] = {}

    async def call(self, action: Action, name: str, **params) -> Any:
        try:
            return unwrap(await asyncio.wait_for(action(name, **params), timeout=15))
        except asyncio.TimeoutError as exc:
            raise EmojiError("NapCat 接口超时；发送结果可能不确定，不会自动重试") from exc
        except EmojiError:
            raise
        except Exception as exc:
            # Exceptions may contain private resource URLs or token-bearing request data.
            raise EmojiError("NapCat 接口调用失败，请检查接口支持与在线状态") from exc

    async def refresh(self, action: Action, force: bool = False) -> dict:
        async with self.refresh_lock:
            if self.status and not force and time.monotonic() - self.refreshed_at < 300:
                return self.status
            info = await self.call(action, "get_version_info")
            if not isinstance(info, dict) or "napcat" not in str(info.get("app_name", "")).lower():
                raise EmojiError("本插件需要 NapCat OneBot v11，不支持 QQ 官方机器人 API")
            entries = []
            warnings = []
            for raw_path in self.settings.get("face_config_paths", []):
                try:
                    path = Path(raw_path)

                    def read_resource(path=path):
                        if path.stat().st_size > 8 * 1024 * 1024:
                            raise EmojiError("QQ 表情配置文件过大")
                        return parse_face_config(json.loads(path.read_text(encoding="utf-8-sig")))

                    entries.extend(await asyncio.to_thread(read_resource))
                except (OSError, ValueError, TypeError):
                    warnings.append("QQ 资源文件读取失败，请检查只读挂载和 JSON 格式")
            count = max(1, min(int(self.settings.get("favorite_count", 1000)), 2000))
            favorite_ok = False
            skipped = 0
            received_count = 0
            if self.settings.get("enable_favorites", True):
                try:
                    rows = await self.call(action, "fetch_custom_face_detail", count=count)
                    if not isinstance(rows, list):
                        raise EmojiError("收藏详情接口返回格式不受支持")
                    received_count = len(rows)
                    for row in rows:
                        if not isinstance(row, dict):
                            skipped += 1
                            continue
                        entry = favorite_entry(row)
                        if entry:
                            entries.append(entry)
                        else:
                            skipped += 1
                    favorite_ok = True
                except EmojiError:
                    warnings.append("收藏详情接口不可用，收藏表情已停用，原生/已学习商城表情仍可用")
            self.catalog.replace({"qq_resource", "qq_favorites"}, entries)
            await self.save()
            self.status = {
                "napcat_version": str(info.get("app_version", "unknown")),
                "resource_entries": sum(e.source == "qq_resource" for e in entries),
                "favorite_entries": sum(e.family == "favorite" for e in entries),
                "favorites_available": favorite_ok,
                "favorites_requested": count,
                "favorites_returned": received_count,
                "favorites_may_be_truncated": received_count >= count,
                "skipped_favorites": skipped,
                "owned_market_catalog": "unavailable_in_documented_api",
                "warnings": warnings,
            }
            self.refreshed_at = time.monotonic()
            return self.status

    async def search(
        self,
        action: Action,
        query: str,
        family: str,
        scope: str,
        limit: int = 12,
        automatic: bool = True,
    ) -> dict:
        order = self.policy.order(automatic)
        if automatic and self.policy.desire == 0:
            return {
                "entries": [],
                "capabilities": self.status,
                "policy": self.policy.public(automatic),
            }
        if family != "all":
            self.policy.require(family, automatic)
        status = await self.refresh(action)
        return {
            "entries": self.catalog.search(query, family, scope, limit, order),
            "capabilities": status,
            "policy": self.policy.public(automatic),
        }

    async def save(self) -> None:
        try:
            await asyncio.to_thread(self.catalog.save)
        except OSError as exc:
            raise EmojiError("表情目录无法保存，请检查插件数据目录权限或磁盘空间") from exc

    async def send(
        self,
        action: Action,
        identity: str,
        scope: str,
        target: dict,
        text: str = "",
        result_id: str = "",
        chain_count: int = 0,
        automatic: bool = True,
    ) -> dict:
        if len(text) > 4000:
            raise EmojiError("随附文字最多 4000 字")
        # Check switches BEFORE touching cached entries or sending the accompanying text.
        self.policy.require(identity.split(":", 1)[0], automatic)
        text = self.policy.clean_text(text, automatic)
        # Resolve current collection URLs again; removed favourites cannot be sent from stale cache.
        await self.refresh(action, force=identity.startswith("favorite:"))
        entry = self.catalog.get(identity, scope)
        self.policy.require(entry.family, automatic)
        segment = copy.deepcopy(entry.segment)
        if result_id or chain_count:
            if entry.family != "face":
                raise EmojiError("result_id/chain_count 仅用于 QQ 原生 face")
            if result_id:
                segment["data"]["resultId"] = digits(result_id, "result_id", 65535)
            if chain_count:
                segment["data"]["chainCount"] = int(digits(chain_count, "chain_count", 100))
        if set(target) not in ({"group_id"}, {"user_id"}):
            raise EmojiError("只能发送到当前群聊或私聊")
        target = {k: int(digits(v, k)) for k, v in target.items()}
        split = entry.family != "unicode" and bool(text.strip())
        batches = (
            [[{"type": "text", "data": {"text": text}}], [segment]]
            if split
            else [([{"type": "text", "data": {"text": text}}] if text.strip() else []) + [segment]]
        )
        async with self.send_lock:
            now = time.monotonic()
            cooldown = max(0.0, float(self.settings.get("cooldown_seconds", 2)))
            if now - self.last_send.get(scope, float("-inf")) < cooldown:
                raise EmojiError("表情发送间隔过短，请稍后再试")
            # Reserve before awaiting: on an uncertain timeout do not automatically duplicate.
            self.last_send[scope] = now
            action_name = "send_group_msg" if "group_id" in target else "send_private_msg"
            message_ids = []
            for message in batches:
                try:
                    reply = await self.call(action, action_name, **target, message=message)
                    if not isinstance(reply, dict) or reply.get("message_id") in (None, "", 0, "0"):
                        raise EmojiError("NapCat 未返回 message_id，发送结果不确定，不会自动重试")
                    message_ids.append(str(reply["message_id"]))
                except EmojiError as exc:
                    if not split:
                        raise
                    # The first bubble might already have reached QQ. Report its receipt;
                    # never cause the agent to repeat text or blindly resend either bubble.
                    return {
                        "status": "partial_or_uncertain" if message_ids else "error_or_uncertain",
                        "message_ids": message_ids,
                        "text_status": "sent" if message_ids else "unknown",
                        "emoji_status": "unknown" if message_ids else "not_attempted",
                        "emoji": entry.public(),
                        "text": text,
                        "message": str(exc),
                        "instruction": "文字已发送或可能已发送，请勿复述，不要自动重试表情",
                    }
            # Bound runtime bookkeeping for bots participating in many chats.
            if len(self.last_send) > 2000:
                self.last_send = {
                    k: v for k, v in self.last_send.items() if now - v < max(cooldown, 60)
                }
            return {
                "status": "sent",
                "message_id": message_ids[-1],
                "message_ids": message_ids,
                "layout": "separate" if entry.family != "unicode" else "inline",
                "emoji": entry.public(),
                "text": text,
            }
