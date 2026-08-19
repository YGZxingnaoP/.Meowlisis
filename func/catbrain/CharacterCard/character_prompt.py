# -*- coding: utf-8 -*-
# func/catbrain/CharacterCard/character_prompt.py
# 角色卡提示词构建：读取角色卡字段并以 markdown 语法输出（共用字段 + 多设定 + 当前性格 + 情绪）

import os
import json

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.config import MeowCatBrainConfig
from func.catbrain.CharacterCard.load_card import MeowLoadCard


class MeowCharacterPrompt:
    """角色卡提示词构建类：读取角色卡并构建 markdown 角色信息提示词"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.load_card = MeowLoadCard()
        self.latest_emotion_path = os.path.join(".temp", "latest_emotion.json")

    def _pick_card(self, card: dict) -> dict:
        """从角色卡列表中取当前角色卡（单角色文件取第一个元素）"""
        chars = card.get("characters") or []
        if not chars:
            return card
        return chars[0]

    def current_name(self) -> str:
        """返回当前角色卡名称（供参考音频等模块使用）"""
        card = self.load_card.load()
        info = self._pick_card(card)
        return str(info.get("name", "") or "")

    def _read_latest_emotion(self, online: bool = False) -> dict:
        """读取情绪文件（online 时读 latest_emotion_online.json，否则读主情绪文件）"""
        path = os.path.join(".temp", "latest_emotion_online.json") if online else self.latest_emotion_path
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _current_personality_name(self, online: bool = False) -> str:
        """读取当前选中的性格名（online 时读在线情绪文件，否则读主情绪文件）"""
        data = self._read_latest_emotion(online)
        name = data.get("personality")
        return str(name) if name else ""

    def _current_emotion(self, online: bool = False) -> str:
        """读取当前情绪（online 时读 napcat 在线情绪桥接，否则读主情绪桥接）"""
        if online:
            from func.toolbox.napcat.emotion_bridge import TBNapCatEmotionBridge
            return TBNapCatEmotionBridge().get_emotion()
        from func.pipeline.llm_emotion import LLMEmotionBridge
        return LLMEmotionBridge().get_emotion()

    def _current_personality_prompt(self, info: dict, online: bool = False) -> str:
        """返回当前性格对应的提示词（无匹配时回退第一个性格）"""
        personalities = info.get("personality") or {}
        if not isinstance(personalities, dict):
            return str(personalities) if personalities else ""
        name = self._current_personality_name(online)
        if name and name in personalities:
            return str(personalities[name] or "")
        if personalities:
            return str(list(personalities.values())[0] or "")
        return ""

    def build(self, online: bool = False) -> str:
        """构建角色卡提示词（markdown，标题为角色名，性格/设定/情绪紧接昵称之后）

        online=True 时，性格与情绪读取 napcat 在线数据源。
        """
        card = self.load_card.load()
        if not card:
            return ""
        info = self._pick_card(card)

        # 标题使用角色名（ai_name）
        ai_name = str(info.get("name", "") or AppConfig().ai_name)
        lines = [f"# {ai_name}"]

        # 角色名称与昵称
        name = info.get("name", "")
        if name:
            lines.append(f"- 角色名称：{name}")
        nickname = info.get("nickname", "")
        if nickname:
            lines.append(f"- 昵称：{nickname}")

        # 角色性格（紧接昵称）
        personality_prompt = self._current_personality_prompt(info, online)
        if personality_prompt:
            lines.append(f"- 角色性格：{personality_prompt}")

        # 设定（紧接性格，字典多条；兼容旧字符串格式）
        setting = info.get("setting") or {}
        if isinstance(setting, dict):
            for key, value in setting.items():
                if value:
                    lines.append(f"- 设定（{key}）：{value}")
        elif setting:
            lines.append(f"- 角色设定：{setting}")

        # 现在的情绪（紧接设定）
        lines.append(f"- 现在的情绪：{self._current_emotion(online)}")

        # 角色外貌（位于个人信息提示之前）
        appearance = info.get("appearance", "")
        if appearance:
            lines.append(f"- 角色外貌：{appearance}")

        # 硬编码提示：以下仅为个人信息，禁止主动强调
        lines.append("## 以下只是个人信息喵，禁止主动强调，只有话题强相关才提及哦")

        # 其余共用字段（生日开始）
        fields = [
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
