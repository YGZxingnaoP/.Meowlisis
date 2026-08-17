# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/userinfo_tool.py
# 用户信息更新 function-calling 工具定义

from typing import List, Dict


class MeowUserInfoTool:
    """用户信息工具：约束 LLM 输出固定结构的用户信息"""

    TOOL_NAME = "save_user_info"
    FIELDS = ["name", "gender", "character", "likes", "preference", "relation", "birthday"]

    def build_tools(self) -> List[Dict]:
        """构建用户信息工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "保存或更新指定用户的信息档案，未知信息填写 unknown",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "用户名称"},
                        "gender": {"type": "string", "description": "用户性别，不知道则填写 unknown"},
                        "character": {"type": "string", "description": "用户性格"},
                        "likes": {"type": "string", "description": "用户喜欢的东西（物品）"},
                        "preference": {"type": "string", "description": "用户喜欢的事情（区别于喜欢的东西）"},
                        "relation": {"type": "string", "description": "用户和角色的关系"},
                        "birthday": {"type": "string", "description": "用户的生日，不知道则填写 unknown"},
                        "changed": {"type": "boolean", "description": "本次是否有字段发生实际变化（分析更新时使用，首次猜测固定为 true）"}
                    },
                    "required": self.FIELDS
                }
            }
        }]

    def force_tool_choice(self) -> str:
        """构建强制使用用户信息工具的 tool_choice"""
        return "required"
