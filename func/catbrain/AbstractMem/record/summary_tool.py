# -*- coding: utf-8 -*-
import json
import re
from typing import List, Dict

from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.process.tag_store import MeowTagStore


class MeowSummaryTool:
    """摘要工具定义类"""

    TOOL_NAME = "save_memory_summary"
    GREP_TOOL_NAME = "grep_memories"
    JUDGE_TOOL_NAME = "judge_memory_relation"
    RECALL_TOOL_NAME = "decide_abmem_recall"
    TOPICS = ["日常", "爱好", "哲思", "闲聊", "情感"]
    ACCURACY_VALUES = [1, 3, 5]
    ACTIONS = ["strengthen", "weaken", "new"]

    def __init__(self):
        """初始化 tag 存储与配置"""
        self.tag_store = MeowTagStore()
        self.config = MeowCatBrainConfig()

    @staticmethod
    def parse_arguments(text, default=None):
        """容错解析工具参数 JSON，失败返回默认值"""
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
        """构建事件归类工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "概括一条事件记忆并给出其话题与标签，每次调用只输出一个事件，可多次调用；系统会返回该话题与标签范围内的已有记忆",
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

    def build_grep_tool(self) -> List[Dict]:
        """构建候选记忆检索工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.GREP_TOOL_NAME,
                "description": "在当前话题与标签范围内按关键词检索已有记忆内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "要检索的关键词"}
                    },
                    "required": ["keyword"]
                }
            }
        }]

    def build_judge_tool(self) -> List[Dict]:
        """构建记忆关系判定工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.JUDGE_TOOL_NAME,
                "description": "指认该事件关联的已有记忆编号与处理动作，有相关记忆则加强，矛盾则削弱，无相关则新建",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_id": {"type": "string", "description": "关联的已有记忆编号，action 为 new 时留空"},
                        "action": {
                            "type": "string",
                            "enum": self.ACTIONS,
                            "description": "strengthen加强/weaken削弱/new新建"
                        }
                    },
                    "required": ["action"]
                }
            }
        }]

    def build_recall_tool(self) -> List[Dict]:
        """构建记忆回忆判定工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.RECALL_TOOL_NAME,
                "description": "判断用户消息是否需要加强回忆过往记忆，需要时给出时间窗口（整年同月，最多3个月）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "need_recall": {
                            "type": "boolean",
                            "description": "是否需要加强回忆；看不出时间窗口时一律为 false"
                        },
                        "months": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "时间窗口月份列表，格式 YYYY-MM，最多3个；看不出时间窗口时留空",
                            "maxItems": 3
                        },
                        "label": {"type": "string", "description": "时间窗口的中文描述，如 一年前"}
                    },
                    "required": ["need_recall", "months"]
                }
            }
        }]

    def build_topic_tool(self) -> List[Dict]:
        """构建话题决策工具的 tools 定义"""
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

    def build_tags_attachment(self) -> str:
        """构建已有 tags 附件文本"""
        tags = self.tag_store.load()
        if not tags:
            return "【已有tags附件】暂无已有tags，请新建精炼短语。"
        return "【已有tags附件】优先从以下已有tags中选择，完全没有贴合内容时才新建：\n" + "、".join(tags)
