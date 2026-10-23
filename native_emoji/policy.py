"""One policy for visible candidates, native sends, and outgoing Unicode text."""

from __future__ import annotations

import emoji

from .catalog import EmojiError

FAMILIES = ("favorite", "market", "face", "unicode")
SWITCHES = {
    "favorite": "enable_favorites",
    "market": "enable_market",
    "face": "enable_faces",
    "unicode": "enable_unicode",
}
LABELS = {
    "favorite": "收藏表情",
    "market": "商城表情",
    "face": "QQ原生表情",
    "unicode": "Unicode emoji",
}


class EmojiPolicy:
    def __init__(self, settings: dict):
        self.settings = settings

    def order(self, automatic: bool = True) -> list[str]:
        configured = self.settings.get("family_priority", list(FAMILIES))
        if not isinstance(configured, list) or any(x not in FAMILIES for x in configured):
            raise EmojiError("表情优先级必须是 favorite、market、face、unicode 组成的列表")
        ordered = list(dict.fromkeys([*configured, *FAMILIES]))
        enabled = [f for f in ordered if self.settings.get(SWITCHES[f], True)]
        if automatic and not self.settings.get("fallback_to_other_types", True):
            return enabled[:1]
        return enabled

    def require(self, family: str, automatic: bool = True) -> None:
        if family not in self.order(automatic):
            raise EmojiError("该表情类型已关闭或不在当前自动回退策略中，请使用自然文字回复")

    def clean_text(self, text: str, automatic: bool = True) -> str:
        return text if "unicode" in self.order(automatic) else emoji.replace_emoji(text, replace="")

    def public(self, automatic: bool = True) -> dict:
        order = self.order(automatic)
        return {
            "enabled_families": self.order(False),
            "priority": order,
            "preferred_family": order[0] if order else None,
            "fallback_to_other_types": bool(self.settings.get("fallback_to_other_types", True)),
            "no_suitable_candidate": "reply_with_text_without_emoji",
            "layout": "unicode_inline_other_families_standalone",
        }

    def guidance(self) -> str:
        order = self.order()
        if not order:
            return "当前所有表情类型均已关闭，请只使用文字回复，不发送Unicode emoji。"
        text = "当前表情考虑顺序：" + " → ".join(LABELS[f] for f in order) + "。"
        text += "先搜索首选类型，仅在候选贴合当前语境时使用。"
        if self.settings.get("fallback_to_other_types", True):
            text += "首选类型没有合适候选时，可以按顺序考虑下一类，也可以直接不发表情。"
        else:
            text += "首选类型没有合适候选时，只用文字回复，不改用其他类型。"
        text += "不要为了使用工具而硬发表情。Unicode可与文字同条；其他表情单独发送，随附文字由工具先另发一条。"
        if "unicode" not in order:
            text += "本轮普通文字中也不要直接输出Unicode emoji。"
        return text
