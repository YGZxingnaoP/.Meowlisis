# -*- coding: utf-8 -*-
"""
消息构建器：负责将角色卡、记忆、身份提示等组装成最终的消息列表。
"""

from typing import List, Dict, Optional
from .character import CharacterCard


class MessageBuilder:
    """构建最终发送给 LLM 的消息列表"""

    def __init__(self, role_file: str = None, character: CharacterCard = None):
        """
        初始化消息构建器
        :param role_file: 角色卡文件路径（与 character 二选一）
        :param character: CharacterCard 实例（优先使用）
        """
        if character:
            self.character = character
        elif role_file:
            self.character = CharacterCard(role_file)
        else:
            # 默认角色卡路径
            self.character = CharacterCard("./character/MiaoWu.yaml")

    def build(
        self,
        messages: List[Dict[str, str]],
        relation: str,
        username: str = None,
        include_system: bool = True,
        include_few_shot: bool = True,
        include_identity: bool = True
    ) -> List[Dict[str, str]]:
        """
        构建最终消息列表
        :param messages: 基础消息（通常来自记忆管理器）
        :param relation: 与用户的关系（如“粉丝”、“主人”）
        :param username: 用户名（用于身份提示）
        :param include_system: 是否包含系统提示
        :param include_few_shot: 是否包含 few-shot 示例
        :param include_identity: 是否包含身份提示
        :return: 构建后的消息列表
        """
        result = []

        # 构建系统提示
        system_prompt = ""
        few_shot_messages = []
        try:
            system_prompt = self.character.build_system_prompt()
            few_shot_messages = self.character.build_few_shot_messages()
        except Exception as e:
            # 角色卡加载失败，忽略
            pass

        if include_system and system_prompt:
            result.append({"role": "system", "content": system_prompt})

        if include_few_shot and few_shot_messages:
            result.extend(few_shot_messages)

        # 添加身份提示
        if include_identity and username:
            identity = f"你和{username}的关系是{relation}。"
            if relation != "主人":
                identity += f"不是你的主人。"
            # 如果已经有系统消息，追加到系统消息末尾；否则新建一条系统消息
            if result and result[0]["role"] == "system":
                result[0]["content"] += f"\n{identity}"
            else:
                result.insert(0, {"role": "system", "content": identity})

        # 追加对话历史
        result.extend(messages)
        return result