# -*- coding: utf-8 -*-
# func/llm/emotion_controller.py
# 通过 LLM function calling 控制角色表情

import json
from typing import Dict, List

from func.pipeline.llm_emotion import LLMEmotionBridge


class EmotionController:
    """解析 LLM 的 tool_calls，将情绪指令传递到 pipeline（本质为 function calling）"""

    # 情绪枚举（沿用现有 emote 内容，后续扩展情感强度等）
    EMOTIONS = ["happy", "sad", "call", "angry", "blush", "approve", "sweat", "blood", "love"]

    def __init__(self):
        self.emotion_bridge = LLMEmotionBridge()
        # 累积流式 tool_calls 分片：{index: {"name", "arguments"}}
        self.tool_calls: Dict[int, Dict[str, str]] = {}

    def build_tools(self) -> List[Dict]:
        """构建 function calling 的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": "set_emotion",
                "description": "根据回复内容设置角色当前表情",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "emotion": {"type": "string", "enum": self.EMOTIONS}
                    },
                    "required": ["emotion"]
                }
            }
        }]

    def handle_stream_tool_calls(self, delta_tool_calls):
        """累积流式返回的 tool_calls 分片"""
        for tc in delta_tool_calls:
            idx = tc.index
            if idx not in self.tool_calls:
                self.tool_calls[idx] = {"name": "", "arguments": ""}
            if tc.function:
                if tc.function.name:
                    self.tool_calls[idx]["name"] = tc.function.name
                if tc.function.arguments:
                    self.tool_calls[idx]["arguments"] += tc.function.arguments

    def finalize(self):
        """流结束后解析完整 tool_calls 并传递情绪到 pipeline"""
        for idx, tc in self.tool_calls.items():
            if tc["name"] == "set_emotion":
                try:
                    args = json.loads(tc["arguments"])
                    emotion = args.get("emotion")
                    if emotion in self.EMOTIONS:
                        self.emotion_bridge.set_emotion(emotion)
                except Exception:
                    pass
        self.tool_calls.clear()
