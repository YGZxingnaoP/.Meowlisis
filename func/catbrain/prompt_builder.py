# -*- coding: utf-8 -*-
# func/catbrain/prompt_builder.py
# 完整系统提示词构建：仅按顺序拼接各模块 load 产出的 markdown 提示词

import os
import json

from func.log.default_log import DefaultLog
from func.gobal.data import LLmData
from func.catbrain.CharacterCard.character_prompt import MeowCharacterPrompt
from func.catbrain.CharacterCard.load_refaudio import MeowLoadRefAudio
from func.catbrain.CatValues.load_values import MeowLoadValues
from func.catbrain.UserMemory.load_usrmem import MeowLoadUserMemory
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory


class MeowPromptBuilder:
    """提示词构建器：不在此处转化内容，仅按固定顺序拼接各模块已构建的 markdown 提示词"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.character_prompt = MeowCharacterPrompt()
        self.values = MeowLoadValues()
        self.usrmem = MeowLoadUserMemory()
        self.abmem = MeowLoadAbstractMemory()
        self.ref_audio = MeowLoadRefAudio()
        self.latest_emotion_path = os.path.join(".temp", "latest_emotion.json")

    def _current_emotion(self) -> str:
        """读取当前情绪（来自 .temp/latest_emotion.json，缺失回退默认 happy）"""
        try:
            if os.path.exists(self.latest_emotion_path):
                with open(self.latest_emotion_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    emotion = data.get("emotion")
                    if emotion:
                        return str(emotion)
        except Exception:
            pass
        return "happy"

    def build_emotion(self) -> str:
        """构建当前情绪提示词（仅次于角色卡放置）"""
        return f"现在{LLmData().Ai_Name}的情绪：{self._current_emotion()}"

    def build(self, username=None, current_message: str = "") -> str:
        """构建完整系统提示词（顺序：角色卡→情绪→价值观→用户记忆→记忆摘要）"""
        # 当前用户优先取传入参数，缺失时从 llm_ltmem 桥接获取最近用户
        if not username:
            try:
                from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
                username = MeowLLMLtMemBridge().last_username
            except Exception:
                username = None
        parts = [
            self.character_prompt.build(),
            self.build_emotion(),
            self.values.build(),
            self.usrmem.build(username),
            self.abmem.build_prompt(current_message, username),
        ]
        return "\n\n".join([p for p in parts if p])

    def build_character(self) -> str:
        """构建仅角色卡提示词（供摘要概括等模块使用）"""
        return self.character_prompt.build()

    def build_persona(self) -> str:
        """构建完整角色身份提示词（角色卡 + 价值观，供价值观/用户记忆分析使用）"""
        parts = [
            self.character_prompt.build(),
            self.values.build(),
        ]
        return "\n\n".join([p for p in parts if p])

    def get_ref_audio(self) -> dict:
        """获取当前角色卡对应的参考音频配置（供 TTS 使用，不含于 LLM 提示词）"""
        name = self.character_prompt.current_name()
        return self.ref_audio.get(name)
