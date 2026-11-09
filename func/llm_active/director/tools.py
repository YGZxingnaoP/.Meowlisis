# -*- coding: utf-8 -*-
# func/llm_active/director/tools.py
# 导演模块的三个工具定义：规划 / 折叠监工 / 无聊判官

PLAN_TOOL_NAME = "director_plan"
STEP_TOOL_NAME = "director_step"
JUDGE_TOOL_NAME = "judge_bored"
ACT_TOOL_NAME = "director_act"


def act_tool(catalog=None):
    """主动触发父级工具：只给白名单入口，instruction 交给子链路自己决策

    catalog：[{"name": ..., "description": ...}]；为空时返回 None（表演回合不挂工具）。
    """
    rows = [row for row in (catalog or []) if row.get("name")]
    if not rows:
        return None
    names = [str(row.get("name")) for row in rows]
    hints = "\n".join(f"- {row.get('name')}：{row.get('description', '')}" for row in rows)
    return {
        "type": "function",
        "function": {
            "name": ACT_TOOL_NAME,
            "description": (
                "你主动想做一件事时调用：只触发父级模块入口，不直接调用它的内部子工具。\n"
                "instruction 写清你要它做什么（例如画什么、唱什么、看屏幕时关注什么），"
                "父级链路会自己决定具体提示词/歌曲/画面。\n"
                "说完这一句再调用；同一场不要重复触发同一种动作。\n"
                f"可用入口：\n{hints}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": names,
                        "description": "要触发的父级入口",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "给这个入口的指令：要做什么、重点是什么（不是台词）",
                    },
                    "why": {
                        "type": "string",
                        "description": "为什么现在想做这件事（一句话）",
                    },
                },
                "required": ["tool", "instruction"],
            },
        },
    }


def plan_tool():
    """启动规划：要不要开始导演 + 一份只含行为与思路的表演清单"""
    return {
        "type": "function",
        "function": {
            "name": PLAN_TOOL_NAME,
            "description": (
                "决定要不要开始导演，并写出这一场的表演清单。\n"
                "清单只写行为与思路：这一步要干什么、猜他会怎么接、他不接时怎么拉回来；"
                "禁止写死台词，禁止冷笑话。\n"
                "start=true 只用于：主人明显没意思了 / 聊天明确没有话题了 / 我想主动问最近有什么好玩的视频。\n"
                "主人有明确话题、正在忙、或你们正聊得起劲时，start=false。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {
                        "type": "boolean",
                        "description": "要不要开始导演；主人有明确话题时必须 false",
                    },
                    "reason": {
                        "type": "string",
                        "description": "判断依据，引用对话里的原话片段",
                    },
                    "steps": {
                        "type": "array",
                        "description": "表演清单；步数自己定，够演完就行（不设上限）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "goal": {"type": "string",
                                         "description": "这一步要达成什么（行为或心理，不是台词）"},
                                "move": {"type": "string",
                                         "description": "用哪一招：让他猜东西/猜他下一句/关心地问他的情况/"
                                                        "考他记不记得/调戏他/卖关子/故意说错等他纠正/"
                                                        "把话头递给他（你不觉得……吗）；不局限这些"},
                                "expect": {"type": "string",
                                           "description": "猜他会怎么接"},
                                "if_not": {"type": "string",
                                           "description": "他没这么接时，怎么把他拉回我的思路"},
                                "tool": {"type": "string",
                                         "description": "这一步如果要做一件事，填父级入口名（可空）"},
                                "instruction": {"type": "string",
                                                "description": "给父级入口的指令，写做什么/重点是什么（可空）"},
                            },
                            "required": ["goal", "move", "expect", "if_not"],
                        },
                    },
                },
                "required": ["start", "reason", "steps"],
            },
        },
    }


def step_tool():
    """折叠监工：每次开口同一次生成里交回进度"""
    return {
        "type": "function",
        "function": {
            "name": STEP_TOOL_NAME,
            "description": (
                "交回这一次表演的进度。每说完一句话都必须调用。\n"
                "completed 填这一轮已经说出口的步骤序号——只要这一步你说出口了就算完成，"
                "他没接不算没完成（用 adjust / if_not 决定下一步怎么说）；"
                "current 填下一轮要推进的步骤；reaction 写他这一下的反应；clear 表示导演到此结束。\n"
                "他说不要打扰、不想听，或者内容已经全部演完，就 clear=true。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "completed": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "这一轮真正走完的步骤序号（没有就空数组）",
                    },
                    "current": {
                        "type": "integer",
                        "description": "下一轮要推进的步骤序号（不许跳过没完成的前一步）",
                    },
                    "reaction": {
                        "type": "string",
                        "description": "他这一下的反应，一句话（他说了什么/没接住/跑题了），给下一步用",
                    },
                    "adjust": {
                        "type": "array",
                        "description": "要改或新增的步骤（可选，只写要变的）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer",
                                       "description": "要改的步骤序号；新增时留空"},
                                "goal": {"type": "string"},
                                "move": {"type": "string"},
                                "expect": {"type": "string"},
                                "if_not": {"type": "string"},
                            },
                            "required": ["goal"],
                        },
                    },
                    "yield_to_user": {
                        "type": "boolean",
                        "description": "他有明确话题时置 true：这一步先挂起，先跟他的话题（不结束导演）",
                    },
                    "clear": {
                        "type": "boolean",
                        "description": "导演是否到此结束",
                    },
                    "clear_reason": {
                        "type": "string",
                        "enum": ["全部完成", "主人说不要打扰", "主人不想听了",
                                 "主人有明确话题", "没意思了"],
                        "description": "clear=true 时填原因",
                    },
                },
                "required": ["completed", "reaction", "clear"],
            },
        },
    }


def judge_tool():
    """每轮异步无聊判官"""
    return {
        "type": "function",
        "function": {
            "name": JUDGE_TOOL_NAME,
            "description": (
                "判断主人现在是不是没意思了、聊天是不是明确断了。只做判断，不写回复。\n"
                "判 true 要有证据：他越来越敷衍、话题接不下去、或明确说无聊。\n"
                "他在讲自己的事、在问你问题、在认真回你、或刚说要去忙，都不要判 true。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bored": {
                        "type": "boolean",
                        "description": "主人是不是明显没意思了、在敷衍",
                    },
                    "no_topic": {
                        "type": "boolean",
                        "description": "聊天是不是明确没有话题了",
                    },
                    "reason": {
                        "type": "string",
                        "description": "必须引用他原话里的片段；没有原话证据就别判 true",
                    },
                    "next": {
                        "type": "string",
                        "description": "我想干什么：起话题/逗他/问他/关心他/不说",
                    },
                },
                "required": ["bored", "reason"],
            },
        },
    }
