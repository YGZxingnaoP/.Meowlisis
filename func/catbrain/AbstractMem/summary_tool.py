# -*- coding: utf-8 -*-
"""摘要事件工具与去重比对工具定义"""
import json
import re
from typing import List, Dict

from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.tag_store import MeowTagStore


class MeowSummaryTool:
    """摘要工具：约束 LLM 输出事件格式，并定义去重比对工具"""

    TOOL_NAME = "save_memory_summary"
    TOOL_DEDUP_NAME = "judge_memory_relation"
    TOPICS = ["日常", "爱好", "哲思", "闲聊", "情感"]
    ACCURACY_VALUES = [1, 3, 5]

    def __init__(self):
        self.tag_store = MeowTagStore()
        self.config = MeowCatBrainConfig()

    @staticmethod
    def parse_arguments(text, default=None):
        """容错解析 LLM 生成的工具参数 JSON，失败返回 default"""
        if default is None:
            default = {}
        if not text:
            return default
        text = str(text).strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass
        try:
            import ast
            val = ast.literal_eval(text)
            if isinstance(val, dict):
                return val
        except Exception:
            pass
        try:
            fixed = re.sub(r'"\s*(?=")', '",', text)
            fixed = re.sub(r'(\}|\])\s*(?=")', r'\1,', fixed)
            fixed = re.sub(r'"\s*(?=\{)', '",', fixed)
            return json.loads(fixed)
        except Exception:
            pass
        return default

    def build_tools(self) -> List[Dict]:
        """构建事件概括工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "以第一人称概括一条事件记忆，每次调用只输出一个事件，可多次调用",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string", "description": "事件内容，50字以内，包含人物与具体事件"},
                        "accuracy": {
                            "type": "integer",
                            "enum": self.ACCURACY_VALUES,
                            "description": "概括置信度：完全确定5，有疑问3，严重质疑1"
                        },
                        "importance": {
                            "type": "number",
                            "description": "事件重要程度，满分10分，涉及价值观、用户爱好习惯等内容分数偏高",
                            "minimum": 0,
                            "maximum": 10
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "事件标签短语列表，按重点从大到小排列，优先从已有tags附件选择",
                            "maxItems": self.config.summary_tags_limit
                        },
                        "topics": {
                            "type": "array",
                            "items": {"type": "string", "enum": self.TOPICS},
                            "description": "事件所属话题列表，仅从限定话题中选择，可多个"
                        },
                        "joint": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "该事件涉及的用户名列表（不含AI自己），可多人"
                        }
                    },
                    "required": ["event", "accuracy", "importance", "tags", "topics", "joint"]
                }
            }
        }]

    def force_tool_choice(self) -> str:
        """构建强制调用事件概括工具的 tool_choice"""
        return "required"

    def build_dedup_tool(self) -> List[Dict]:
        """构建去重比对工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_DEDUP_NAME,
                "description": "判断新事件与多条候选记忆的关系：same相同、opposite相反、origin无关",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text_id": {"type": "string", "description": "候选记忆编号"},
                                    "relation": {
                                        "type": "string",
                                        "enum": ["same", "opposite", "origin"],
                                        "description": "same相同/opposite相反/origin无关"
                                    }
                                },
                                "required": ["text_id", "relation"]
                            }
                        }
                    },
                    "required": ["results"]
                }
            }
        }]

    def force_dedup_tool_choice(self) -> Dict:
        """构建强制调用去重比对工具的 tool_choice"""
        return {"type": "function", "function": {"name": self.TOOL_DEDUP_NAME}}

    def build_topic_tool(self) -> List[Dict]:
        """构建话题决策工具定义"""
        return [{
            "type": "function",
            "function": {
                "name": "decide_topic",
                "description": "根据最近对话内容判断当前话题，从枚举中选择一个",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "enum": self.TOPICS, "description": "当前话题"}
                    },
                    "required": ["topic"]
                }
            }
        }]

    def force_topic_tool_choice(self) -> Dict:
        """构建强制使用话题决策工具的 tool_choice"""
        return {"type": "function", "function": {"name": "decide_topic"}}

    def build_tags_attachment(self) -> str:
        """构建已有 tags 附件文本"""
        tags = self.tag_store.load()
        if not tags:
            return "【已有tags附件】暂无已有tags，请新建精炼短语。"
        return "【已有tags附件】优先从以下已有tags中选择，完全没有贴合内容时才新建：\n" + "、".join(tags)
