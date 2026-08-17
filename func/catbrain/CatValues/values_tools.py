# -*- coding: utf-8 -*-
# func/catbrain/CatValues/values_tools.py
# 价值观 function-calling 工具定义（更新工具 + 审查工具）

from typing import List, Dict


class MeowValuesUpdateTool:
    """价值观更新工具：约束 LLM 输出固定结构的价值观（0204 绝对禁止修改）"""

    TOOL_NAME = "update_values"
    FIELDS = ["trust", "belief", "responsity", "honor", "tolerance"]
    # 绝对禁止修改的锁定字段（不进入 tool，由系统程序化回填）
    LOCK_FIELD = "0204"

    def build_tools(self) -> List[Dict]:
        """构建价值观更新工具的 tools 定义（不含主人的话，避免被修改）"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "更新角色的价值观（不含主人的话，该字段由系统固定保留，无需输出）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trust": {"type": "string", "description": "角色究竟什么情况下会真正信任你"},
                        "belief": {"type": "string", "description": "人生信条"},
                        "responsity": {"type": "string", "description": "做事的原则"},
                        "honor": {"type": "string", "description": "角色真心认可的事情"},
                        "tolerance": {"type": "string", "description": "角色的底线"}
                    },
                    "required": self.FIELDS
                }
            }
        }]

    def force_tool_choice(self) -> Dict:
        """构建强制使用价值观更新工具的 tool_choice（指定函数名）"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}


class MeowValuesReviewTool:
    """价值观审查工具：约束审查 LLM 输出通过与否及修改意见"""

    TOOL_NAME = "review_values"

    def build_tools(self) -> List[Dict]:
        """构建价值观审查工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "审查价值观更新结果是否合理、是否符合角色设定，输出审查结论",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pass": {"type": "boolean", "description": "审查是否通过"},
                        "feedback": {"type": "string", "description": "不通过时给出具体修改意见，通过时留空"}
                    },
                    "required": ["pass", "feedback"]
                }
            }
        }]

    def force_tool_choice(self) -> Dict:
        """构建强制使用审查工具的 tool_choice（指定函数名）"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}
