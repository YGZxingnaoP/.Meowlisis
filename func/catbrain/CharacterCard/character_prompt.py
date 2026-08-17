# -*- coding: utf-8 -*-
# func/catbrain/CharacterCard/character_prompt.py
# 角色卡提示词构建：读取角色卡字段并以 markdown 语法输出

from func.log.default_log import DefaultLog
from func.catbrain.CharacterCard.load_card import MeowLoadCard


class MeowCharacterPrompt:
    """角色卡提示词构建类：读取角色卡并构建 markdown 角色信息提示词"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.load_card = MeowLoadCard()

    def _pick_card(self, card: dict) -> dict:
        """从角色卡列表中选择当前角色卡（当前取第一张，性格与情绪不再参与选择）"""
        chars = card.get("characters") or []
        if not chars:
            return card
        return chars[0]

    def current_name(self) -> str:
        """返回当前角色卡名称（供参考音频等模块使用）"""
        card = self.load_card.load()
        info = self._pick_card(card)
        return str(info.get("name", "") or "")

    def build(self) -> str:
        """构建角色卡提示词（markdown 语法，不含参考音频路径）"""
        card = self.load_card.load()
        if not card:
            return ""
        info = self._pick_card(card)
        fields = [
            ("性格名称", info.get("name", "")),
            ("角色性格", info.get("personality", "")),
            ("角色设定", info.get("setting", "")),
            ("角色外貌", info.get("appearance", "")),
            ("角色生日", info.get("birthday", "")),
            ("角色身份证号", info.get("id_card", "")),
            ("QQ号", info.get("qq", "")),
            ("手机号", info.get("phone", "")),
            ("MBTI", info.get("mbti", "")),
            ("最喜欢的东西", info.get("favorite", "")),
            ("角色爱好", info.get("hobbies", "")),
            ("讨厌的东西", info.get("dislikes", "")),
            ("人际关系", info.get("relationships", "")),
        ]
        lines = ["# 角色卡"]
        for label, value in fields:
            if value:
                lines.append(f"- {label}：{value}")
        return self._ensure_markdown("\n".join(lines))

    @staticmethod
    def _ensure_markdown(text: str) -> str:
        """检查并确保输出为 markdown 语法（缺标题或列表符时微调补全）"""
        if not text:
            return ""
        lines = text.split("\n")
        if not lines[0].startswith("#"):
            lines.insert(0, "# 角色卡")
        fixed = []
        for line in lines[1:]:
            if line.strip() and not line.startswith(("#", "-", "*", ">", "|")):
                line = "- " + line
            fixed.append(line)
        return "\n".join([lines[0]] + fixed)
