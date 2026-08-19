# -*- coding: utf-8 -*-
# func/pipeline/system_prompt.py
# 系统提示词传递桥接（输入端为 catbrain 模块，最前面拼接前置词）

import os
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class SystemPromptBridge:
    """系统提示词桥接：注册 catbrain 构建器，按需获取提示词（单例）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        # catbrain 提示词构建器（由 api.py 注册）
        self._builder = None
        # 前置词文件路径
        self.front_path = os.path.join("character", "front", "prompt.json")

    def register_builder(self, builder):
        """注册 catbrain 提示词构建器"""
        self._builder = builder

    def get_front_prompt(self) -> str:
        """读取前置词（character/front/prompt.json 的 prompt 字段，缺失返回空）"""
        try:
            if os.path.exists(self.front_path):
                with open(self.front_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return str(data.get("prompt", "") or "").strip()
        except Exception:
            self.log.exception("读取前置词失败")
        return ""

    def get_system_prompt(self, username=None, current_message: str = "") -> str:
        """获取完整系统提示词：前置词(末尾追加当前说话人) + catbrain 构建内容"""
        body = ""
        if self._builder:
            body = self._builder.build(username, current_message)
        front = self.get_front_prompt()
        if front:
            name = username or "用户"
            front = f"{front}\n你现在在和{name}说话"
        if front and body:
            return front + "\n\n" + body
        return front or body

    def get_napcat_prompt(self, username=None, current_message: str = "") -> str:
        """获取 NapCat 专用系统提示词：前置词末尾追加「你在QQ里回复」优化，使用在线情绪/性格"""
        body = ""
        if self._builder:
            body = self._builder.build(username, current_message, online=True)
        front = self.get_front_prompt()
        if front:
            name = username or "用户"
            front = f"{front}\n你现在在和{name}说话\n你在QQ里回复TA的消息，必须使用网络用语"
        if front and body:
            return front + "\n\n" + body
        return front or body

    def get_active_prompt(self, cold_time, current_message: str = "") -> str:
        """获取主动回复系统提示词：前置词末尾追加空闲提示 + catbrain 主动回复内容（不含用户档案）"""
        body = ""
        if self._builder:
            body = self._builder.build_active(cold_time, current_message)
        front = self.get_front_prompt()
        if front:
            front = f"{front}\n已经{cold_time}秒没人跟你说话了，你必须自己找话题说话"
        if front and body:
            return front + "\n\n" + body
        return front or body

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
        """获取当前角色卡对应的参考音频配置（供 TTS 使用）"""
        if self._builder and hasattr(self._builder, 'get_ref_audio'):
            return self._builder.get_ref_audio()
        return {}
