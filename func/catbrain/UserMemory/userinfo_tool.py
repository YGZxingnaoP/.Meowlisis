# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/userinfo_tool.py
# 用户信息更新 function-calling 工具定义

from typing import List, Dict

from func.catbrain.AbstractMem.tag_store import MeowTagStore


class MeowUserInfoTool:
    """用户信息工具：约束 LLM 输出固定结构的用户信息（tags_preference 仅从已有 tags 中选择）"""

    TOOL_NAME = "save_user_info"
    FIELDS = ["name", "gender", "character", "likes", "preference", "relation", "birthday",
              "favorite_songs", "favorite_shows", "favorite_foods", "tags_preference", "affinity"]

    def __init__(self):
        self.tag_store = MeowTagStore()

    def build_tools(self) -> List[Dict]:
        """构建用户信息工具的 tools 定义"""
        existing_tags = self.tag_store.load()
        tag_items = {"type": "string", "enum": existing_tags} if existing_tags else {"type": "string"}
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
                        "character": {"type": "string", "description": "几句话简单描述用户性格，**严格控制在100字以内**，禁止出现任何事件"},
                        "likes": {"type": "string", "description": "用户喜欢的东西，必须用户多次明确表达喜欢，才确认填写。"},
                        "preference": {"type": "string", "description": "用户喜欢的事情，必须用户多次明确表达喜欢，才确认填写。"},
                        "relation": {"type": "string", "description": "用户和角色的关系"},
                        "birthday": {"type": "string", "description": "用户的公历生日，格式如 4月23日，不知道则填写 unknown"},
                        "favorite_songs": {"type": "string", "description": "用户喜欢的歌曲，必须用户多次明确表达喜欢，才确认填写。不知道则填写 unknown"},
                        "favorite_shows": {"type": "string", "description": "用户喜欢的影视作品，必须用户多次明确表达喜欢，才确认填写。不知道则填写 unknown"},
                        "favorite_foods": {"type": "string", "description": "用户喜欢的食物，必须用户多次明确表达喜欢，才确认填写。不知道则填写 unknown"},
                        "tags_preference": {
                            "type": "array",
                            "items": tag_items,
                            "description": "用户喜欢的话题标签，仅从已有tags附件中选择，禁止新建；没有把握时留空数组"
                        },
                        "affinity": {"type": "integer", "description": "用户好感度，范围 -10 到 10，初始为 0", "minimum": -10, "maximum": 10},
                        "changed": {"type": "boolean", "description": "本次是否有字段发生实际变化（分析更新时使用，首次猜测固定为 true）"}
                    },
                    "required": self.FIELDS
                }
            }
        }]

    def build_tags_attachment(self) -> str:
        """构建已有 tags 附件文本（供用户记忆 LLM 选择 tags_preference，禁止新建）"""
        tags = self.tag_store.load()
        if not tags:
            return "【已有tags附件】暂无已有tags，请将 tags_preference 设为空数组 []。"
        return "【已有tags附件】tags_preference 仅从以下已有tags中选择，禁止新建：\n" + "、".join(tags)

    def force_tool_choice(self) -> str:
        """构建强制使用用户信息工具的 tool_choice"""
        return "required"
