"""Parse actual QQ metadata without bundling Tencent's artwork or a static ID map."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class EmojiError(ValueError):
    """An actionable validation or capability error safe to show to the caller."""


def clean_label(value: Any, fallback: str = "表情") -> str:
    # Labels are untrusted data, including QQ's OCR and user-edited descriptions.
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return text.strip().lstrip("/")[:80] or fallback


def digits(value: Any, name: str, maximum: int = 2**53 - 1) -> str:
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,16}", text) or int(text) > maximum:
        raise EmojiError(f"{name} 必须是有效的非负整数")
    return str(int(text))


@dataclass(frozen=True)
class Entry:
    id: str
    family: str
    label: str
    segment: dict[str, Any]
    source: str
    scope: str = ""

    def public(self) -> dict[str, str]:
        """Never expose resource URLs, local paths, or mface keys to the LLM."""
        return {"id": self.id, "family": self.family, "label": self.label}


def parse_face_config(data: Any) -> list[Entry]:
    if not isinstance(data, dict) or not isinstance(data.get("sysface"), list):
        raise EmojiError("文件不是 QQ face_config.json：缺少 sysface 数组")
    result = []
    for row in data["sysface"]:
        if not isinstance(row, dict):
            continue
        try:
            face_id = digits(row.get("QSid"), "QSid", 65535)
        except EmojiError:
            continue
        result.append(
            Entry(
                f"face:{face_id}",
                "face",
                clean_label(row.get("QDes")),
                {"type": "face", "data": {"id": face_id}},
                "qq_resource",
            )
        )
    # QQ lists Unicode emoji separately: they must remain Unicode, not fabricated IDs.
    unicode_rows = data.get("emoji", [])
    if not isinstance(unicode_rows, list):
        unicode_rows = []
    for row in unicode_rows:
        if not isinstance(row, dict):
            continue
        char = row.get("QSid", "")
        if not isinstance(char, str) or not char or char.isascii() or len(char) > 16:
            continue
        code = "-".join(f"{ord(c):x}" for c in char)
        result.append(
            Entry(
                f"unicode:{code}",
                "unicode",
                clean_label(row.get("QDes"), char),
                {"type": "text", "data": {"text": char}},
                "qq_resource",
            )
        )
    return result


def market_entry(data: dict, scope: str, label: str = "") -> Entry:
    package = digits(data.get("emoji_package_id"), "emoji_package_id")
    emoji = str(data.get("emoji_id", ""))
    key = str(data.get("key", ""))
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", emoji) or not key or len(key) > 512:
        raise EmojiError("商城表情缺少完整的 emoji_id/key，不能降级成图片")
    if any(ord(c) < 32 for c in key):
        raise EmojiError("商城表情 key 格式无效")
    summary = clean_label(label or data.get("summary"), "商城表情")
    return Entry(
        f"market:{package}:{emoji}",
        "market",
        summary,
        {
            "type": "mface",
            "data": {
                "emoji_package_id": int(package),
                "emoji_id": emoji,
                "key": key,
                "summary": summary,
            },
        },
        "received_market",
        scope,
    )


def parse_incoming(segments: Any, scope: str) -> list[Entry]:
    """NapCat reports mface as image + extra fields in several versions."""
    if not isinstance(segments, list):
        return []
    result = []
    for segment in segments[:100]:
        if not isinstance(segment, dict) or not isinstance(segment.get("data"), dict):
            continue
        kind, data = segment.get("type"), segment["data"]
        try:
            if kind == "mface" or (
                kind == "image" and "emoji_package_id" in data and "emoji_id" in data
            ):
                result.append(market_entry(data, scope))
            elif kind == "face":
                face_id = digits(data.get("id"), "face ID", 65535)
                payload: dict[str, Any] = {"id": face_id}
                # Retain animation/result/chain parameters from the native message.
                if data.get("resultId") is not None:
                    payload["resultId"] = digits(data["resultId"], "resultId", 65535)
                if data.get("chainCount") is not None:
                    payload["chainCount"] = int(digits(data["chainCount"], "chainCount", 100))
                raw = data.get("raw") or {}
                result.append(
                    Entry(
                        f"face:{face_id}",
                        "face",
                        clean_label(raw.get("faceText"), f"QQ表情{face_id}"),
                        {"type": "face", "data": payload},
                        "received_face",
                        scope,
                    )
                )
        except (EmojiError, TypeError, AttributeError):
            continue
    return result


def favorite_entry(row: dict) -> Entry | None:
    # A market favourite is NOT an ordinary custom image. It needs mface's key.
    if row.get("isMarkFace") in (True, 1, "1", "true"):
        return None
    md5 = str(row.get("md5", "")).lower()
    res_id = str(row.get("resId", ""))
    if re.fullmatch(r"[a-f0-9]{32}", md5):
        identity = md5
    elif res_id:
        identity = hashlib.sha256(res_id.encode()).hexdigest()[:32]
    else:
        return None
    # Only use the account's actual QQ collection URL. Never accept a path/URL from a tool.
    url = str(row.get("url", ""))
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        return None
    label = clean_label(row.get("modifyWord") or row.get("desc") or row.get("ocrWord"), "收藏表情")
    return Entry(
        f"favorite:{identity}",
        "favorite",
        label,
        {"type": "image", "data": {"file": url, "sub_type": 1, "summary": label}},
        "qq_favorites",
    )


class Catalog:
    """Account-isolated metadata store; no picture downloading or image library."""

    def __init__(self, directory: Path, account_key: str):
        self.path = directory / (hashlib.sha256(account_key.encode()).hexdigest() + ".json")
        self.account_key = account_key
        self.entries: dict[tuple[str, str], Entry] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or data.get("account") != self.account_key:
                raise ValueError("catalogue identity mismatch")
            self.entries = {}
            for row in data["entries"]:
                entry = Entry(**row)
                self.entries[(entry.scope, entry.id)] = entry
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise EmojiError("表情目录缓存无效，请管理员备份后移走对应缓存文件并重新同步") from exc
        except OSError as exc:
            raise EmojiError("表情目录缓存无法读取，请检查插件数据目录权限") from exc

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        # Open with restrictive permissions before writing any resource credentials.
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 1,
                    "account": self.account_key,
                    "entries": [asdict(e) for e in self.entries.values()],
                },
                f,
                ensure_ascii=False,
            )
        os.replace(temp, self.path)
        os.chmod(self.path, 0o600)

    def replace(self, sources: set[str], entries: list[Entry]) -> None:
        self.entries = {k: e for k, e in self.entries.items() if e.source not in sources}
        for entry in entries:
            self.entries[(entry.scope, entry.id)] = entry

    def remember(self, entry: Entry) -> None:
        self.entries[(entry.scope, entry.id)] = entry

    def get(self, identity: str, scope: str) -> Entry:
        entry = self.entries.get((scope, identity)) or self.entries.get(("", identity))
        if entry is None:
            raise EmojiError("该表情不在当前账号/会话目录中，请先搜索或同步")
        return entry

    def search(
        self,
        query: str,
        family: str,
        scope: str,
        limit: int = 12,
        family_order: list[str] | None = None,
    ) -> list[dict]:
        if family not in {"all", "face", "unicode", "market", "favorite"}:
            raise EmojiError("family 只能是 all/face/unicode/market/favorite")
        query = query.strip().casefold()
        order = (
            family_order if family_order is not None else ["favorite", "market", "face", "unicode"]
        )
        visible = {e.id: e for e in self.entries.values() if not e.scope}
        visible.update({e.id: e for e in self.entries.values() if e.scope == scope})
        rows = [
            e
            for e in visible.values()
            if e.family in order
            and (family == "all" or e.family == family)
            and (
                not query
                or query in (e.label + " " + e.id).casefold()
                or query == e.segment.get("data", {}).get("text")
            )
        ]
        rows.sort(key=lambda e: (order.index(e.family), e.label.casefold() != query, e.id))
        return [e.public() for e in rows[: max(1, min(limit, 50))]]
