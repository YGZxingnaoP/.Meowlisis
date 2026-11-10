# -*- coding: utf-8 -*-
# func/llm/prompt_get.py
# 从 pipeline 获取系统提示词

from func.pipeline.system_prompt import SystemPromptBridge


class PromptGet:
    """从 pipeline 的 system_prompt 桥接获取完整系统提示词"""

    def __init__(self):
        self.bridge = SystemPromptBridge()

    def get_system_prompt(self, username=None, current_message: str = "",
                          recall: dict = None, explicit: bool = None,
                          topic: str = None) -> str:
        """获取完整系统提示词（来源为 catbrain，传入当前消息供记忆摘要检索）"""
        return self.bridge.get_system_prompt(username, current_message, recall=recall,
                                             explicit=explicit, topic=topic)

    def prepare_recall(self, current_message: str, uid=None) -> dict:
        """并行调度：提前算好回忆判定"""
        return self.bridge.prepare_recall(current_message, uid)

    def prepare_topic(self):
        """并行调度：预热话题缓存"""
        return self.bridge.prepare_topic()

    def get_danmaku_prompt(self, username=None, current_message: str = "",
                           multi_user: bool = False) -> str:
        """获取弹幕专用系统提示词（弹幕来源的回复后置词）"""
        return self.bridge.get_danmaku_prompt(username, current_message, multi_user)
