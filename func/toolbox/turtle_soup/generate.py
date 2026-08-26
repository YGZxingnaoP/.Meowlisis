# -*- coding: utf-8 -*-
# func/toolbox/turtle_soup/generate.py
# 生成海龟汤题目：toolbox LLM 非流式 + 强制工具，产出结构化字段

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


def generate(username: str, text: str, difficulty: str = "") -> dict:
    """生成一道海龟汤；失败返回 None"""
    llm = _llm()
    if not llm or not llm.client:
        DefaultLog().getLogger().error("[TurtleSoup] 生成 LLM 不可用")
        return None

    system = TBoxGetPrompt().get_tool_prompt(username, text) or ""
    diff_note = difficulty or "未指定，由你结合用户信息决定"
    system += (
        "\n\n【海龟汤生成】请生成一道海龟汤（情境谜题）。\n"
        "- title：题目标题；\n"
        "- surface：汤面（谜面，给玩家看的线索）；\n"
        "- answer：汤底（完整真相，玩家需要推理出的答案）；\n"
        "- difficulty：easy（低难度）或 hard（高难度）；\n"
        f"- 用户指定难度：{diff_note}；\n"
        "- 低难度汤面约20字，高难度汤面约40字；\n"
        "- 剧情合理、有反转、汤面不剧透答案。"
    )
    tools = [{
        "type": "function",
        "function": {
            "name": "generate_turtle_soup",
            "description": "生成海龟汤题目",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "surface": {"type": "string"},
                    "answer": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["easy", "hard"]},
                },
                "required": ["title", "surface", "answer", "difficulty"],
            },
        },
    }]
    resp = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": text}],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "generate_turtle_soup"}},
    )
    if not resp or not resp.choices:
        return None
    msg = resp.choices[0].message
    for tc in (msg.tool_calls or []):
        if tc.function.name == "generate_turtle_soup":
            try:
                return json.loads(tc.function.arguments or "{}")
            except Exception:
                return None
    return None
