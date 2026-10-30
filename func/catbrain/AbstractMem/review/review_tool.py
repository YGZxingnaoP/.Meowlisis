from typing import List, Dict


class MeowMemoryReviewTool:
    TOOL_NAME = "review_memories"
    KINDS = ["身份", "偏好", "习惯", "关系", "约定", "价值观", "经历"]
    ACCURACY_VALUES = [1, 3, 5]

    def build_tools(self) -> List[Dict]:
        """构建记忆审查工具的 tools 定义，逐条给出通过结论"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "逐条审查候选记忆是否可写入长期记忆，并给出归类与置信度",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "results": {
                            "type": "array",
                            "description": "与候选记忆一一对应的审查结论",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "index": {"type": "integer", "description": "候选记忆的编号"},
                                    "pass": {"type": "boolean", "description": "是否合格可写入"},
                                    "kind": {"type": "string", "enum": self.KINDS, "description": "合格记忆的归类"},
                                    "accuracy": {"type": "integer", "enum": self.ACCURACY_VALUES, "description": "合格记忆的置信度，存在任何不确定时不得为5"},
                                    "reason": {"type": "string", "description": "不合格时写明命中的条件编号，合格时留空"}
                                },
                                "required": ["index", "pass", "reason"]
                            }
                        }
                    },
                    "required": ["results"]
                }
            }
        }]

    def force_tool_choice(self) -> Dict:
        """构建强制使用记忆审查工具的 tool_choice"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}
