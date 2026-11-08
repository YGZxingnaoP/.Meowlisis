# -*- coding: utf-8 -*-
"""文本模型的小封装：拿不到模型时一律退回空字符串，不阻塞主链路。"""

import re


def clean(text):
    text = re.sub(r"<think>[\s\S]*?</think>", "", str(text or ""), flags=re.IGNORECASE)
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"```[a-zA-Z]*", "", text)
    text = text.replace("```", "")
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def chat(ctx, messages, max_chars=1600):
    """调用主程序注入的文本模型；任何异常都当成「没有模型」。"""
    try:
        llm = ctx.llm()
        if llm is None or not getattr(llm, "client", None):
            return ""
        response = llm.chat(messages)
        if not response or not getattr(response, "choices", None):
            return ""
        content = getattr(response.choices[0].message, "content", "") or ""
        return clean(content)[:max_chars]
    except Exception as exc:
        try:
            ctx.log.warning("星露谷文本模型调用失败：%s" % exc)
        except Exception:
            pass
        return ""


def call_tools(ctx, messages, tools, tool_choice="auto"):
    """带工具的一次模型调用：返回 (正文, [{"id","name","arguments"}])。

    和 chat() 不同，这里失败直接抛错：动作循环不允许把模型故障当成“没听见”跳过。
    """
    llm = ctx.llm()
    if llm is None or not getattr(llm, "client", None):
        raise RuntimeError("没有可用的文本模型（llm.client 为空）")
    response = llm.chat(messages, tools=tools, tool_choice=tool_choice)
    if response is None or not getattr(response, "choices", None):
        raise RuntimeError("文本模型没有返回结果")
    message = response.choices[0].message
    content = clean(getattr(message, "content", "") or "")
    calls = []
    for call in (getattr(message, "tool_calls", None) or []):
        function = getattr(call, "function", None)
        if function is None:
            continue
        calls.append({
            "id": str(getattr(call, "id", "") or ""),
            "name": str(getattr(function, "name", "") or ""),
            "arguments": str(getattr(function, "arguments", "") or ""),
        })
    return content, calls


def extract_json(text):
    """从模型输出里抠出第一个 JSON 对象；失败返回 None。"""
    text = clean(text)
    if not text:
        return None
    start = text.find("{")
    while start >= 0:
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:index + 1]
                    try:
                        import json
                        return json.loads(candidate)
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None
