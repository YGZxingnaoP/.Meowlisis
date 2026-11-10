from typing import List, Dict


class MeowPsycheTool:
    TOOL_NAME = "note_inner"

    def build_tools(self) -> List[Dict]:
        """构建心理内容工具的 tools 定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "写下心里现在装着的东西：我正在干的那件事，和这件事现在什么样",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "theme": {
                            "type": "string",
                            "description": "我正在干的那件事，一句话，必须带对象（对什么人、什么东西、做什么）。"
                                           "说不出这种「在干的事」——只有聊天、说话、闲着、等着的——就填空字符串，不许编"
                        },
                        "content": {
                            "type": "string",
                            "description": "我现在心里冒出来的短句，像自言自语，不像写报告。"
                                           "最多三条，一条一行，用换行分开。"
                                           "可以是对别人的看法（醒脑片人真好／筱狐是不是生气了）、"
                                           "自己的打算（今天我要做可爱的小猫，谁骂我我都不生气）、"
                                           "吐槽（这人骂的好过分，讨厌ta喵）、不耐烦（不想听他说，他啥时候说完啊）、"
                                           "累了（累了，想睡觉）、心疼（主人好辛苦，再陪陪他吧）。"
                                           "可以提他/她，也可以说“我要…”，但必须是我的反应、想法或打算，"
                                           "不是复述剧情、不是写行动步骤。"
                                           "禁止“我等他软下来”“我要再别一会儿”“我准备看他反应”"
                                           "“我给他一点空间”“保持距离”这类剧情动作/试探计划/空泛策略。"
                                           "也不要把对主人说出口的安慰/哄劝/命令写成心理："
                                           "“别急别急，我在呢，慢慢来”“你缓着，我不催”是台词，不是心里话。"
                                           "禁止揣测用户：不写“主人肯定累了”“他其实想我留下”"
                                           "“主人心里舍不得”“主人是不是生气了”；"
                                           "第三方可以疑问，但不能用这种方式猜主人。"
                                           "主题留空时这里也留空"
                        }
                    },
                    "required": ["theme", "content"]
                }
            }
        }]

    def force_tool_choice(self) -> Dict:
        """构建强制使用心理内容工具的 tool_choice"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}
