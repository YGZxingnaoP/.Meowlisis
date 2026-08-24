# -*- coding: utf-8 -*-
# func/llm/emotion_controller.py
# 通过 LLM function calling 控制角色表情与性格（性格从角色卡动态读取）

import os
import json
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.pipeline.llm_emotion import LLMEmotionBridge


class EmotionController:
    """解析 LLM 的 tool_calls，将情绪与性格指令传递到 pipeline 并落盘"""

    # 情绪枚举（沿用现有 emote 内容，后续扩展情感强度等）
    EMOTIONS = ["happy", "sad", "call", "angry", "blush", "approve", "sweat", "blood", "love", "wordless"]
    TOOL_NAME = "set_emotion"
    LATEST_PATH = os.path.join(".temp", "latest_emotion.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.emotion_bridge = LLMEmotionBridge()
        # 累积流式 tool_calls 分片：{index: {"id", "name", "arguments"}}
        self.tool_calls: Dict[int, Dict[str, str]] = {}
        self.last_result = None

    def _get_personalities(self) -> List[str]:
        """从角色卡动态读取性格名列表（缺失或异常时返回空列表）"""
        try:
            from func.catbrain.CharacterCard.load_card import MeowLoadCard
            card = MeowLoadCard().load()
            chars = card.get("characters") or []
            if not chars:
                return []
            personalities = chars[0].get("personality") or {}
            if isinstance(personalities, dict):
                return [str(k) for k in personalities.keys()]
        except Exception:
            self.log.exception("读取角色卡性格列表失败")
        return []

    def build_tools(self) -> List[Dict]:
        """构建 function calling 的 tools 定义（情绪、强度、性格、是否需要价值观思考）"""
        properties = {
            "emotion": {"type": "string", "enum": self.EMOTIONS, "description": "角色当前表情"},
            "intensity": {"type": "number", "description": "情绪强度打分，满分5分", "minimum": 0, "maximum": 5},
            "need_thinking": {"type": "boolean", "description": "本次是否需要触发价值观思考，触动价值观/人生信条/做事原则时设为 true，普通闲聊设为 false"}
        }
        required = ["emotion", "intensity", "need_thinking"]

        # 性格参数：从角色卡动态读取，性格列表存在时才加入
        personalities = self._get_personalities()
        if personalities:
            properties["personality"] = {
                "type": "string",
                "enum": personalities,
                "description": "角色当前性格（从角色卡性格列表中选择）"
            }
            required = ["emotion", "intensity", "need_thinking", "personality"]

        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "设置角色当前表情、情绪强度与性格，并判断是否需要触发价值观思考",
                "parameters": {"type": "object", "properties": properties, "required": required}
            }
        }]

    def build_tool_choice(self) -> Dict:
        """构建指定强制调用情绪工具的 tool_choice（确保情绪工具每次必然调用）"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}

    def handle_stream_tool_calls(self, delta_tool_calls):
        """累积流式返回的 tool_calls 分片（含 id）"""
        for tc in delta_tool_calls:
            idx = tc.index
            if idx not in self.tool_calls:
                self.tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
            if tc.id:
                self.tool_calls[idx]["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    self.tool_calls[idx]["name"] = tc.function.name
                if tc.function.arguments:
                    self.tool_calls[idx]["arguments"] += tc.function.arguments

    def finalize(self) -> List[Dict]:
        """解析完整 tool_calls、落盘最新情绪与性格，必要时触发价值观思考并返回 payload"""
        result = {"emotion": "happy", "intensity": 3, "need_thinking": False}
        personalities = self._get_personalities()
        for tc in self.tool_calls.values():
            if tc["name"] == self.TOOL_NAME:
                try:
                    args = json.loads(tc["arguments"])
                    if args.get("emotion") in self.EMOTIONS:
                        result["emotion"] = args["emotion"]
                    if "intensity" in args:
                        result["intensity"] = args["intensity"]
                    if args.get("need_thinking") is True:
                        result["need_thinking"] = True
                    if personalities and args.get("personality") in personalities:
                        result["personality"] = args["personality"]
                except Exception:
                    pass
        self.last_result = result
        self._save_latest(result)
        self.emotion_bridge.set_emotion(result["emotion"], result["intensity"])
        if result["need_thinking"]:
            self._launch_thinking()
        payload = self.build_payload()
        self.tool_calls.clear()
        return payload

    def _launch_thinking(self):
        """通过 pipeline 的 llm_values 桥接触发价值观更新"""
        try:
            from func.pipeline.llm_values import MeowLLMValuesBridge
            MeowLLMValuesBridge().trigger_update("set_emotion 触发价值观思考")
        except Exception:
            self.log.exception("触发价值观更新失败")

    def build_payload(self) -> List[Dict]:
        """构建本工具的 tool_calls payload（供合并回填消息使用）"""
        payload = []
        for idx in sorted(self.tool_calls.keys()):
            tc = self.tool_calls[idx]
            if tc["name"] == self.TOOL_NAME:
                payload.append({
                    "id": tc["id"] or f"call_{idx}",
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]}
                })
        return payload

    def _save_latest(self, result: Dict):
        """保存最新情绪与性格到 .temp/latest_emotion.json"""
        try:
            os.makedirs(os.path.dirname(self.LATEST_PATH), exist_ok=True)
            with open(self.LATEST_PATH, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


