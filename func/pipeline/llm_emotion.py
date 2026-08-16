# -*- coding: utf-8 -*-
# func/pipeline/llm_emotion.py
# LLM 与 Emotion 之间的情绪传递桥接

from func.log.default_log import DefaultLog


class LLMEmotionBridge:
    """LLM → Emotion 情绪传递桥接（emotion 模块尚未实现，暂留空）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def set_emotion(self, emotion: str):
        """设置角色当前表情（后期由 emotion 模块实现，当前留空）"""
        self.log.info(f"情绪指令: {emotion}")
        pass
