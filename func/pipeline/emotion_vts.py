# -*- coding: utf-8 -*-
# func/pipeline/emotion_vts.py
# LLM 情绪 → VTS 表情桥接：订阅情绪更新，解析槽位后触发 VTS 热键

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class EmotionVtsBridge:
    """订阅 LLMEmotionBridge 的情绪更新，映射为 VTS hotkey 并触发。

    - 依赖方向：pipeline → vts（合法），llm 不感知本桥接；
    - 情绪每更新一次，即解析槽位并触发一次表情。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        from func.pipeline.llm_emotion import LLMEmotionBridge
        LLMEmotionBridge().subscribe(self._on_emotion)

    def _on_emotion(self, emotion: str, intensity: float):
        """情绪更新回调：解析 hotkey 并触发"""
        try:
            from func.vts.emotion_mapper import VtsEmotionMapper
            hotkey = VtsEmotionMapper().resolve(emotion, intensity)
            if not hotkey:
                return
            from func.vts.vts_oper import VtsOper
            VtsOper().vts.trigger_hotkey(hotkey)
            self.log.info(f"[VTS表情] {emotion}({intensity}) → hotkey={hotkey}")
        except Exception:
            self.log.exception("LLM 情绪 → VTS 表情触发异常")
