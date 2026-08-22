# -*- coding: utf-8 -*-
# func/pipeline/system_prompt.py
# 系统提示词传递桥接（输入端为 catbrain 模块）
# 提示词顺序：前置词(行为约束) → 主体(角色卡/记忆) → 后置词(人设)

import os
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class SystemPromptBridge:
    """系统提示词桥接：注册 catbrain 构建器，按需获取提示词（单例）"""

    # 字段缺失时的默认值（前置词 = 行为约束；后置词 = 人设）
    DEFAULT_PROMPT = (
        "一次回复不要一次性解决复杂问题，可以留到之后回答；回复要有主见；"
        "唱歌，做题，发消息这种仅靠说话完成不了的问题，让{username}稍等"
    )
    DEFAULT_PROMPT_ACTIVE = "一次回复不要一次性解决复杂问题，可以留到之后回答；回复要有主见；"
    DEFAULT_PROMPT_NAPCAT = "一次回复不要一次性解决复杂问题，可以留到之后回答；回复要有主见"
    DEFAULT_POST = ""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        # catbrain 提示词构建器（由 api.py 注册）
        self._builder = None
        # 前置词/后置词文件路径（同文件，与前置词相同位置）
        self.front_path = os.path.join("character", "front", "prompt.json")

    def register_builder(self, builder):
        """注册 catbrain 提示词构建器"""
        self._builder = builder

    def _read_front(self) -> dict:
        """读取 character/front/prompt.json 完整内容（缺失返回空 dict）"""
        try:
            if os.path.exists(self.front_path):
                with open(self.front_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception("读取前置词/后置词失败")
        return {}

    # ==================== 前置词（行为约束，放最前） ====================
    def get_front_prompt(self) -> str:
        """获取主链路前置词（行为约束，放 system prompt 最前）"""
        data = self._read_front()
        return str(data.get("prompt", self.DEFAULT_PROMPT) or "").strip()

    def get_active_front_prompt(self) -> str:
        """获取主动回复前置词（行为约束，放最前）"""
        data = self._read_front()
        return str(data.get("prompt_active", self.DEFAULT_PROMPT_ACTIVE) or "").strip()

    def get_napcat_front_prompt(self) -> str:
        """获取 napcat 前置词（行为约束，放最前）"""
        data = self._read_front()
        return str(data.get("prompt_napcat", self.DEFAULT_PROMPT_NAPCAT) or "").strip()

    # ==================== 后置词（人设，放最后） ====================
    def get_post_prompt(self) -> str:
        """获取后置词（人设，放 system prompt 最后）"""
        data = self._read_front()
        return str(data.get("post_prompt", self.DEFAULT_POST) or "").strip()

    # ==================== 各场景完整提示词 ====================
    def get_poke_prompt(self) -> str:
        """戳一戳发牢骚专用提示词：仅前置词 + 自定义后置词（不含角色卡、用户记忆、日期、摘要）"""
        front = self.get_front_prompt()
        # 自定义后置词：被很多人戳，烦死了要骂他们
        post = "好多人在戳你，你觉得烦死了，骂他们！"
        parts = [p for p in (front, post) if p]
        return "\n\n".join(parts)

    def get_tool_prompt(self, username=None, current_message: str = "") -> str:
        """工具箱决策/工具调用用提示词：前置词(行为约束) + 角色人设(角色卡+价值观) + 后置词(人设)

        - 不含用户记忆、日期、记忆摘要（这些是「对话上下文」，决策/工具场景不需要）；
        - 后置词不加「你现在在和{name}说话」（决策/工具场景没有固定对话对象）。
        """
        body = ""
        if self._builder and hasattr(self._builder, "build_persona"):
            body = self._builder.build_persona()
        front = self.get_front_prompt()
        if front:
            front = front.replace("{username}", username or "主人")
        post = self.get_post_prompt()
        parts = [p for p in (front, body, post) if p]
        return "\n\n".join(parts)

    def get_system_prompt(self, username=None, current_message: str = "") -> str:
        """主链路提示词：前置词(行为约束) + body + 后置词(人设+说话人)"""
        body = ""
        if self._builder:
            body = self._builder.build(username, current_message)
        front = self.get_front_prompt()
        if front:
            front = front.replace("{username}", username or "主人")
        post = self.get_post_prompt()
        if post:
            name = username or "用户"
            post = f"{post}\n你现在在和{name}说话"
        parts = [p for p in (front, body, post) if p]
        return "\n\n".join(parts)

    def get_danmaku_prompt(self, username=None, current_message: str = "",
                           multi_user: bool = False) -> str:
        """弹幕提示词：前置词(行为约束) + body + 弹幕后置词(回复弹幕)

        - 单用户：body 含用户档案/记忆，后置词「你在回复{username}的弹幕」；
        - 多用户：body 仅角色人设(角色卡+价值观，不带用户档案)，后置词「你收到了好多弹幕，挑选一些回复一下」。
        """
        body = ""
        if self._builder:
            if multi_user and hasattr(self._builder, "build_persona"):
                body = self._builder.build_persona()
            else:
                body = self._builder.build(username, current_message)
        front = self.get_front_prompt()
        if front:
            front = front.replace("{username}", username or "主人")
        post = self.get_post_prompt()
        if multi_user:
            post = f"{post}\n你收到了好多弹幕，挑选一些回复一下"
        else:
            name = username or "用户"
            post = f"{post}\n你在回复{name}的弹幕"
        parts = [p for p in (front, body, post) if p]
        return "\n\n".join(parts)

    def get_napcat_prompt(self, username=None, current_message: str = "") -> str:
        """NapCat 提示词：前置词(行为约束+QQ指令) + body + 后置词(人设+说话人)"""
        body = ""
        if self._builder:
            body = self._builder.build(username, current_message, online=True)
        front = self.get_napcat_front_prompt()
        if front:
            # QQ 指令与字数限制追加到行为约束（前置词）后
            try:
                from func.toolbox.napcat.config import TBNapCatConfig
                word_count = int(TBNapCatConfig().reply_word_count or 10)
            except Exception:
                word_count = 10
            front = (
                f"{front}\n你在QQ里回复TA的消息，必须使用网络用语\n"
                f"每次回复{word_count}个字左右，严格控制在{word_count + 10}字以内"
            )
        post = self.get_post_prompt()
        if post:
            name = username or "用户"
            post = f"{post}\n你现在在和{name}说话"
        parts = [p for p in (front, body, post) if p]
        return "\n\n".join(parts)

    def get_napcat_group_prompt(self, username=None, group_name: str = "",
                                group_info_text: str = "", current_message: str = "") -> str:
        """NapCat 群聊提示词：前置词(行为约束+QQ群聊指令) + body(用户档案或群聊档案) + 后置词(在群内聊天)"""
        body = ""
        if self._builder and hasattr(self._builder, "build_group"):
            body = self._builder.build_group(
                username, group_name, group_info_text, current_message, online=True
            )
        elif self._builder:
            body = self._builder.build(username, current_message, online=True)
        front = self.get_napcat_front_prompt()
        if front:
            try:
                from func.toolbox.napcat.config import TBNapCatConfig
                word_count = int(TBNapCatConfig().reply_word_count or 10)
            except Exception:
                word_count = 10
            front = (
                f"{front}\n你在QQ群【{group_name}】里聊天，必须使用网络用语\n"
                f"每次回复{word_count}个字左右，严格控制在{word_count + 10}字以内"
            )
        post = self.get_post_prompt()
        if post:
            post = f"{post}\n你现在在QQ群【{group_name}】内和大家聊天"
        parts = [p for p in (front, body, post) if p]
        return "\n\n".join(parts)

    def get_watching_prompt(self, username=None, current_message: str = "",
                            front_note: str = "") -> str:
        """watching（长期观察屏幕）提示词：前置词 + 游戏场景说明 + body(不含摘要) + 后置词(在看XX内容)

        - front_note：AI 决策填写的游戏场景说明（谁在玩什么、画面特征等），加在前置词之后；
        - body：角色卡 + 价值观 + 用户档案 + 日期（不含长期记忆摘要 abmem）；
        - 后置词末尾追加「你在看{username}的内容」。
        """
        body = ""
        if self._builder and hasattr(self._builder, "build_watching"):
            body = self._builder.build_watching(username, current_message)
        elif self._builder:
            body = self._builder.build(username, current_message)

        front = self.get_front_prompt()
        if front:
            front = front.replace("{username}", username or "主人")
        if front_note and front_note.strip():
            front = f"{front}\n{front_note.strip()}"

        post = self.get_post_prompt()
        name = username or "用户"
        if post:
            post = f"{post}\n你现在在看{name}的屏幕内容，正在陪{name}"
        else:
            post = f"你现在在看{name}的屏幕内容，正在陪{name}"

        parts = [p for p in (front, body, post) if p]
        return "\n\n".join(parts)

    def get_active_prompt(self, cold_time, current_message: str = "") -> str:
        """主动回复提示词：前置词(行为约束) + body + 后置词(人设+空闲提示)"""
        body = ""
        if self._builder:
            body = self._builder.build_active(cold_time, current_message)
        front = self.get_active_front_prompt()
        post = self.get_post_prompt()
        if post:
            post = f"{post}\n已经{cold_time}秒没人跟你说话了，你必须自己找话题说话"
        parts = [p for p in (front, body, post) if p]
        return "\n\n".join(parts)

    # ==================== 其它（供摘要/价值观等模块，不含前后置词） ====================
    def get_character_prompt(self) -> str:
        """获取仅角色卡提示词（供摘要等模块使用）"""
        if self._builder and hasattr(self._builder, 'build_character'):
            return self._builder.build_character()
        return ""

    def get_persona_prompt(self) -> str:
        """获取完整角色身份提示词（角色卡 + 价值观，供价值观/用户记忆分析使用）"""
        if self._builder and hasattr(self._builder, 'build_persona'):
            return self._builder.build_persona()
        return ""

    def get_ref_audio(self) -> dict:
        """获取当前角色卡对应的参考音频配置（供 TTS 使用，不含于 LLM 提示词）"""
        if self._builder and hasattr(self._builder, 'get_ref_audio'):
            return self._builder.get_ref_audio()
        return {}
