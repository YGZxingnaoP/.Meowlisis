# -*- coding: utf-8 -*-
"""摘要独立 LLM 端口与强制工具调用辅助"""


def force_tool_call(llm, messages, tools, tool_name, max_attempts=3, temperature=None, max_tokens=None):
    """开思考循环强制调用指定工具，返回首次出现 tool_calls 的响应"""
    extra = {}
    if temperature is not None:
        extra["temperature"] = temperature
    if max_tokens is not None:
        extra["max_tokens"] = max_tokens
    for _ in range(max_attempts):
        resp = llm.chat(messages, tools=tools, **extra)
        if not resp or not resp.choices:
            return None
        msg = resp.choices[0].message
        if msg.tool_calls:
            return resp
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "reasoning_content": getattr(msg, "reasoning_content", "") or ""
        })
        messages.append({"role": "user", "content": f"你必须调用 {tool_name} 工具输出结果，不要用文字代替。"})
    return None
