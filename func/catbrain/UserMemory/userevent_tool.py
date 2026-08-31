# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/userevent_tool.py
# 用户近期事件 function-calling 工具定义

from typing import List, Dict


class MeowUserEventTool:
    """近期事件工具：约束 LLM 用两三句话概括用户最近在忙什么、在研究什么"""

    TOOL_NAME = "save_user_event"
    FIELDS = ["recent_events"]

    def build_tools(self) -> List[Dict]:
        """构建近期事件工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "保存用户近期事件概括：用两三句话概括该用户最近在忙什么、在研究什么，概括不出时填写 leisure",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "recent_events": {
                            "type": "string",
                            "description": "**两三句话**概括用户最近在忙什么、在研究什么；概括不出时填写 leisure"
                        }
                    },
                    "required": self.FIELDS
                }
            }
        }]

    def force_tool_choice(self) -> Dict:
        """构建强制使用近期事件工具的 tool_choice（指定函数名）"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}
