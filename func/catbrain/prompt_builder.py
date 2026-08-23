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

    def build(self, username=None, current_message: str = "", online: bool = False,
              mark_first: bool = True) -> str:
        """构建完整系统提示词（顺序：角色卡→情绪→价值观→用户记忆→日期→记忆摘要）

        online=True 时，角色卡使用 napcat 在线情绪/性格数据源。
        mark_first=False 时日期块不占用「当天首次说话」祝福判定。
        """
        # 当前用户优先取传入参数，缺失时从 llm_ltmem 桥接获取最近用户
        if not username:
            try:
                from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
                username = MeowLLMLtMemBridge().last_username
            except Exception:
                username = None
        parts = [
            self.character_prompt.build(online=online),  # 角色卡（已含当前情绪）
            self.values.build(),
            self.usrmem.build(username),
            self._build_knowledge(username, current_message),  # 知识库（用户档案下方）
            self.calendar.build(username, mark_first=mark_first),  # 日期块（节日/节气/生日）
            self.abmem.build_prompt(current_message, username),
        ]
        return "\n\n".join([p for p in parts if p])

    def build_group(self, username=None, group_name: str = "", group_info_text: str = "",
                    current_message: str = "", online: bool = True) -> str:
        """构建群聊系统提示词（顺序：角色卡→价值观→[用户档案|群聊档案]→日期→记忆摘要）

        - 仅当用户在群内单独 @ 角色时（username 非空）才使用该用户档案；
        - 否则使用群聊档案 group_info_text（原用户档案处替换为群聊档案）。
        - 长期记忆摘要仅根据当前话题（无用户时 username 传空，joint 相似度不参与）。
        """
        if username:
            user_block = self.usrmem.build(username)
            calendar_block = self.calendar.build(username)
        else:
            user_block = group_info_text or ""
            calendar_block = self.calendar.build_no_user()  # 群聊无特定用户：不检查生日
        parts = [
            self.character_prompt.build(online=online),  # 角色卡（已含当前情绪）
            self.values.build(),
            user_block,
            self._build_knowledge(username, current_message),  # 知识库（用户档案下方）
            calendar_block,
            self.abmem.build_prompt(current_message, username or ""),
        ]
        return "\n\n".join([p for p in parts if p])

    def build_watching(self, username=None, current_message: str = "") -> str:
        """构建 watching（长期观察屏幕）系统提示词 body。

        顺序：角色卡→价值观→用户档案→日期，不含长期记忆摘要（abmem）。
        """
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
            self._build_knowledge(username, current_message),  # 知识库（用户档案下方）
            self.calendar.build(username),  # 日期块
        ]
        return "\n\n".join([p for p in parts if p])

    def build_active(self, cold_time, current_message: str = "", topic_override: str = "") -> str:
        """构建主动回复系统提示词（顺序：角色卡→价值观→空闲占位→日期→记忆摘要，不含用户档案）

        topic_override：外部指定话题（如视频话题），透传给 abmem 用于记忆摘要筛选。
        """
        parts = [
            self.character_prompt.build(),  # 角色卡（已含当前情绪）
            self.values.build(),
            f"# 现在已经{cold_time}秒没人跟你说话了",
            self.calendar.build_no_user(),  # 日期块（仅节日/节气，不获取 username）
            self.abmem.build_prompt(current_message, None, topic_override=topic_override),
        ]
        return "\n\n".join([p for p in parts if p])

    @staticmethod
    def _build_knowledge(username: str = "", current_message: str = "") -> str:
        """从 database_core 获取知识库提示词（含网络搜索摘要，同步）"""
        try:
            from func.database.database_core import CatLearnCore
            return CatLearnCore().build_knowledge_prompt(username, current_message)
        except Exception:
            return ""

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
