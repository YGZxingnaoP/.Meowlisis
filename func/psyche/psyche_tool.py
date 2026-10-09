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
                            "description": "我自己心里装着的：现在什么情绪、在想什么想要什么、"
                                           "不敢做或不能做的是什么、接下来打算做什么。"
                                           "每条都从「我」出发，最多四条，一条一行，用换行分开。"
                                           "不许叙述他干了什么、刚才发生了什么。主题留空时这里也留空"
                        }
                    },
                    "required": ["theme", "content"]
                }
            }
        }]

    def force_tool_choice(self) -> Dict:
        """构建强制使用心理内容工具的 tool_choice"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}
