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

    @property
    def desire(self) -> int:
        desire = self.settings.get("emoji_desire", 50)
        if isinstance(desire, bool) or not isinstance(desire, int) or not 0 <= desire <= 100:
            raise EmojiError("表情使用倾向必须是 0—100 之间的整数")
        return desire

    @property
    def tendency(self) -> str:
        if self.desire == 0:
            return "关闭自动使用"
        if self.desire <= 20:
            return "极少使用"
        if self.desire <= 40:
            return "克制使用"
        if self.desire <= 60:
            return "自然使用"
        if self.desire <= 80:
            return "积极使用"
        return "很积极使用"

    def desire_guidance(self) -> str:
        text = f"表情使用倾向：{self.desire}/100（{self.tendency}）。"
        if self.desire == 0:
            return text + "AI回复只使用文字，不搜索、发送表情，也不直接输出Unicode emoji。"
        if self.desire <= 20:
            text += "平时优先用文字，只有表情特别贴切或对方明确要求时才考虑使用。"
        elif self.desire <= 40:
            text += "以文字为主，偶尔在鲜明情绪或接梗时用一个贴切表情。"
        elif self.desire <= 60:
            text += "日常对话中自然考虑表情，在表达情绪、回应玩笑或接梗时按需使用。"
        elif self.desire <= 80:
            text += "轻松聊天、表达情绪或接梗时，更积极地考虑用贴切表情参与回应。"
        else:
            text += "轻松聊天和情绪鲜明的回应优先考虑贴切表情，也可用一个表情单独回应。"
        return text + (
            "这不是发送概率，不要求每条回复都有表情。严肃讲解、认真倾诉时以内容为先；"
            "没有贴切候选就用文字，仍遵守类型开关、优先级、每轮次数和发送间隔。"
        )

    def order(self, automatic: bool = True) -> list[str]:
        configured = self.settings.get("family_priority", list(FAMILIES))
        if not isinstance(configured, list) or any(x not in FAMILIES for x in configured):
            raise EmojiError("表情优先级必须是 favorite、market、face、unicode 组成的列表")
        ordered = list(dict.fromkeys([*configured, *FAMILIES]))
        enabled = [f for f in ordered if self.settings.get(SWITCHES[f], True)]
        if automatic and self.desire == 0:
            return []
        if automatic and not self.settings.get("fallback_to_other_types", True):
            return enabled[:1]
        return enabled

    def require(self, family: str, automatic: bool = True) -> None:
        if automatic and self.desire == 0:
            raise EmojiError("表情使用倾向为0，AI自动表情已关闭，请使用自然文字回复")
        if family not in self.order(automatic):
            raise EmojiError("该表情类型已关闭或不在当前自动回退策略中，请使用自然文字回复")

    def clean_text(self, text: str, automatic: bool = True) -> str:
        return text if "unicode" in self.order(automatic) else emoji.replace_emoji(text, replace="")

    def public(self, automatic: bool = True) -> dict:
        order = self.order(automatic)
        return {
            "emoji_desire": self.desire,
            "usage_tendency": self.tendency,
            "automatic_emoji_enabled": bool(self.order()),
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
            if self.desire == 0:
                return self.desire_guidance()
            return "当前所有表情类型均已关闭，请只使用文字回复，不发送Unicode emoji。"
        text = self.desire_guidance()
        text += "当前表情考虑顺序：" + " → ".join(LABELS[f] for f in order) + "。"
        text += "先搜索首选类型，仅在候选贴合当前语境时使用。"
        if self.settings.get("fallback_to_other_types", True):
            text += "首选类型没有合适候选时，可以按顺序考虑下一类，也可以直接不发表情。"
        else:
            text += "首选类型没有合适候选时，只用文字回复，不改用其他类型。"
        text += "不要为了使用工具而硬发表情。Unicode可与文字同条；其他表情单独发送，随附文字由工具先另发一条。"
        if "unicode" not in order:
            text += "本轮普通文字中也不要直接输出Unicode emoji。"
        return text
