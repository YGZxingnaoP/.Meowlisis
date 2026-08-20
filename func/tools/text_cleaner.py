# -*- coding: utf-8 -*-
# func/tools/text_cleaner.py
# 文本清理公共工具：去除全角方括号【】及其内容

import re

# 非嵌套的全角方括号内容匹配（【...】）
_BRACKET_RE = re.compile(r"【[^】]*】")


def strip_brackets(text: str) -> str:
    """去除文本中的全角方括号【】及其内部内容（非流式一次性清理用）"""
    if not text:
        return text
    return _BRACKET_RE.sub("", text).strip()


def clean_resp_content(resp):
    """清理 OpenAI 响应对象 message.content 中的【】内容（供非流式 chat 复用）"""
    try:
        if resp and getattr(resp, "choices", None):
            msg = resp.choices[0].message
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content:
                msg.content = strip_brackets(content)
    except Exception:
        pass
    return resp
