# -*- coding: utf-8 -*-
# func/catbrain/CatValues/values_tools.py
# 价值观 function-calling 工具定义（更新工具 + 审查工具）

from typing import List, Dict


class MeowValuesUpdateTool:
    """价值观更新工具：约束 LLM 输出固定结构的价值观（0204 绝对禁止修改）"""

    TOOL_NAME = "update_values"
    FIELDS = ["universalism", "benevolence", "power", "achievement",
              "tradition", "self_direction", "stimulation"]
    # 绝对禁止修改的锁定字段（不进入 tool，由系统程序化回填）
    LOCK_FIELD = "0204"
    # 单条价值观字数上限（中文字符）
    MAX_LEN = 30

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
                        "universalism": {"type": "string", "description": "普世价值：对所有人福祉、公平与自然的普遍关怀"},
                        "benevolence": {"type": "string", "description": "仁爱：真诚关怀他人福祉、乐于助人"},
                        "power": {"type": "string", "description": "权力：追求影响力，用于推动正向改变而非支配"},
                        "achievement": {"type": "string", "description": "成就：欣赏努力与卓越，鼓励自我与他人的成长"},
                        "tradition": {"type": "string", "description": "传统：尊重历史经验、习俗与传承的智慧"},
                        "self_direction": {"type": "string", "description": "自我导向：坚持独立思考、鼓励创新与自由探索"},
                        "stimulation": {"type": "string", "description": "刺激：乐于迎接新奇与变化，谨慎评估风险"}
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
