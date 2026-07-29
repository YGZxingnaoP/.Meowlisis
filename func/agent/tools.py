# func/agent/tools.py
"""Agent 工具定义和格式化"""

tools_definition = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "搜索互联网获取最新信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_and_describe",
            "description": "截图并描述屏幕内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "关注重点（如'游戏画面'、'代码编辑器'）"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "change_scene",
            "description": "切换到指定场景",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_name": {
                        "type": "string",
                        "enum": ["粉色房间", "清晨房间", "神社", "花房", "海岸花坊"],
                        "description": "场景名称"
                    }
                },
                "required": ["scene_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "change_clothes",
            "description": "更换衣服",
            "parameters": {
                "type": "object",
                "properties": {
                    "clothes": {"type": "string", "description": "衣服名称（须在VTS中配置）"}
                },
                "required": ["clothes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sleep_reminder",
            "description": "提醒主人睡觉",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "meal_reminder",
            "description": "提醒主人吃饭（根据当前时间自动判断午饭或晚饭）",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "holiday_greeting",
            "description": "发送节日祝福",
            "parameters": {
                "type": "object",
                "properties": {
                    "holiday_name": {"type": "string", "description": "节日名称"}
                },
                "required": ["holiday_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "talk",
            "description": "发起普通对话",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "对话主题或具体问题"}
                },
                "required": ["topic"]
            }
        }
    }
]

def format_tools_for_prompt():
    """将工具列表格式化为文本，用于提示模型"""
    lines = []
    for t in tools_definition:
        func = t["function"]
        name = func["name"]
        desc = func["description"]
        params = func["parameters"]["properties"]
        param_str = ", ".join([f"{k}: {v['description']}" for k, v in params.items()])
        lines.append(f"- {name}: {desc} 参数: {param_str}")
    return "\n".join(lines)