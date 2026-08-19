# -*- coding: utf-8 -*-
# func/catbrain/prompt_builder.py
# 完整系统提示词构建：仅按顺序拼接各模块 load 产出的 markdown 提示词

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.CharacterCard.character_prompt import MeowCharacterPrompt
from func.catbrain.CharacterCard.load_refaudio import MeowLoadRefAudio
from func.catbrain.CatValues.load_values import MeowLoadValues
from func.catbrain.UserMemory.load_usrmem import MeowLoadUserMemory
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory
from func.calendar.prompt_builder import DatePromptBuilder


class MeowPromptBuilder:
    """提示词构建器：按固定顺序拼接各模块已构建的 markdown 提示词"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.character_prompt = MeowCharacterPrompt()
        self.values = MeowLoadValues()
        self.usrmem = MeowLoadUserMemory()
        self.abmem = MeowLoadAbstractMemory()
        self.ref_audio = MeowLoadRefAudio()
        self.calendar = DatePromptBuilder()

    def _current_emotion(self) -> str:
        """读取当前情绪（来自 pipeline 情绪桥接）"""
        from func.pipeline.llm_emotion import LLMEmotionBridge
        return LLMEmotionBridge().get_emotion()

    def build_emotion(self) -> str:
        """构建当前情绪提示词（仅次于角色卡放置）"""
        return f"现在{AppConfig().ai_name}的情绪：{self._current_emotion()}"

    def build(self, username=None, current_message: str = "") -> str:
        """构建完整系统提示词（顺序：角色卡→情绪→价值观→用户记忆→日期→记忆摘要）"""
        # 当前用户优先取传入参数，缺失时从 llm_ltmem 桥接获取最近用户
        if not username:
            try:
                from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
                username = MeowLLMLtMemBridge().last_username
            except Exception:
                username = None
        parts = [
            self.character_prompt.build(),  # 角色卡（已含当前情绪）
            self.values.build(),
            self.usrmem.build(username),
            self.calendar.build(username),  # 日期块（节日/节气/生日）
            self.abmem.build_prompt(current_message, username),
        ]
        return "\n\n".join([p for p in parts if p])

    def build_active(self, cold_time, current_message: str = "") -> str:
        """构建主动回复系统提示词（顺序：角色卡→价值观→空闲占位→日期→记忆摘要，不含用户档案）"""
        parts = [
            self.character_prompt.build(),  # 角色卡（已含当前情绪）
            self.values.build(),
            f"# 现在已经{cold_time}秒没人跟你说话了",
            self.calendar.build_no_user(),  # 日期块（仅节日/节气，不获取 username）
            self.abmem.build_prompt(current_message, None),
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
