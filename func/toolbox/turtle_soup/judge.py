# -*- coding: utf-8 -*-
# func/toolbox/turtle_soup/judge.py
# 判定用户消息：solved（猜中）/ give_up（放弃）/ repeat（重报汤面）
# LLM 自然判断为主，严格把控，模糊不算对；异常降级为全 False

import json

from func.log.default_log import DefaultLog
from func.toolbox.get_prompt import TBoxGetPrompt


def _llm():
    from func.toolbox.config import TBoxConfig
    cfg = TBoxConfig()
    if cfg.llm_type == "aliyun":
        from func.toolbox.port.aliyun import TBoxAliyunLLM
        return TBoxAliyunLLM(cfg)
    from func.toolbox.port.deepseek import TBoxDeepSeekLLM
    return TBoxDeepSeekLLM(cfg)


def judge(puzzle: dict, username: str, text: str, history: list) -> dict:
    """返回 {"solved": bool, "give_up": bool, "repeat": bool}；异常降级为全 False"""
    result = {"solved": False, "give_up": False, "repeat": False}
    llm = _llm()
    if not llm or not llm.client:
        return result

    title = (puzzle.get("title") or "").strip()
    surface = (puzzle.get("surface") or "").strip()
    answer = (puzzle.get("answer") or "").strip()

    system = TBoxGetPrompt().get_tool_prompt(username, text) or ""
    system += (
        "\n\n【海龟汤判定】你是主持人，当前汤底如下（绝不可透露给用户）：\n"
        f"标题：{title}\n汤面：{surface}\n汤底：{answer}\n"
        "请判断用户这条消息属于哪种情况：\n"
        "- solved：用户准确说出了汤底的核心事实/关键真相；\n"
        "- give_up：用户明确表示不玩了、放弃、结束游戏或要求揭晓答案；\n"
        "- repeat：用户要求再说一遍汤面/谜面；\n"
        "严格规则：模糊、擦边、只说部分、复述汤面都不算 solved，必须命中核心真相。"
    )
    tools = [{
        "type": "function",
        "function": {
            "name": "judge_turtle_soup",
            "description": "判定用户消息属于猜中/放弃/重报中的哪一种",
            "parameters": {
                "type": "object",
                "properties": {
                    "solved": {"type": "boolean"},
                    "give_up": {"type": "boolean"},
                    "repeat": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["solved", "give_up", "repeat"],
            },
        },
    }]
    messages = [{"role": "system", "content": system}]
    for m in history or []:
        if isinstance(m, dict) and m.get("content"):
            messages.append({"role": m.get("role", "user"), "content": str(m["content"])})
    messages.append({"role": "user", "content": text})

    resp = llm.chat(
        messages,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "judge_turtle_soup"}},
    )
    if not resp or not resp.choices:
        return result
    msg = resp.choices[0].message
    for tc in (msg.tool_calls or []):
        if tc.function.name == "judge_turtle_soup":
            try:
                data = json.loads(tc.function.arguments or "{}")
                return {
                    "solved": bool(data.get("solved")),
                    "give_up": bool(data.get("give_up")),
                    "repeat": bool(data.get("repeat")),
                }
            except Exception:
                return result
    return result
