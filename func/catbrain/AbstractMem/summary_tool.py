# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/summary_tool.py
# 记忆摘要 function-calling 工具定义（含 tags、joint 字段）

from typing import List, Dict

from func.catbrain.AbstractMem.tag_store import MeowTagStore


class MeowSummaryTool:
    """摘要工具：约束 LLM 输出固定结构的记忆概括（tags 以附件形式注入）"""

    TOOL_NAME = "save_memory_summary"
    TOPICS = ["日常", "爱好", "哲思", "闲聊", "情感"]

    def __init__(self):
        self.tag_store = MeowTagStore()

    def build_tools(self) -> List[Dict]:
        """构建摘要工具的 tools 定义（tags 上限5个、joint 记录参与用户）"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "以第一人称客观概括对话记忆并输出固定格式",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "第一人称客观概括文本"},
                        "concentration": {"type": "number", "description": "基于话题统一度的打分", "minimum": 0, "maximum": 10},
                        "importance": {
                            "type": "number",
                            "description": "记忆重要程度打分，满分10分，涉及价值观、用户爱好习惯等内容分数偏高",
                            "minimum": 0,
                            "maximum": 10
                        },
                        "topic": {
                            "type": "string",
                            "enum": self.TOPICS,
                            "description": "话题，从枚举中选择最主要的一个"
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "记忆标签短语列表，上限5个，按重点从大到小排列。优先从已有tags附件中选择，完全没有贴合内容时才新建精炼短语",
                            "maxItems": 5
                        },
                        "joint": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "参与对话的用户名列表（不含AI自己的名称），可多人"
                        }
                    },
                    "required": ["text", "concentration", "importance", "topic", "tags", "joint"]
                }
            }
        }]

    def force_tool_choice(self) -> str:
        """构建强制使用摘要工具的 tool_choice"""
        return "required"

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
        """构建已有 tags 附件文本（随消息注入，供 AI 优先选择打标）"""
        tags = self.tag_store.load()
        if not tags:
            return "【已有tags附件】暂无已有tags，请新建精炼短语。"
        return "【已有tags附件】优先从以下已有tags中选择，完全没有贴合内容时才新建：\n" + "、".join(tags)
