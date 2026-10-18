# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/identity/dmem_owner.py
"""δ-mem「按用户记忆」的**策略层**：谁算正式用户、这一次请求用谁的记忆。

它不关心平台（deepseek / aliyun / gemini / meowllm 都适用），只回答两件事：
    1. 这个 uid 值不值得长期记忆（`^\\d{6}$` 才算，`temp-*` 不算）
    2. 这一轮该把 `memory_owner` 设成谁

协议字段名也在这里（`FIELD`）—— 它是"请求里那个键叫什么"的唯一出处。
服务端要改字段名时，改这里一处 + 各端口 `_build_params` 里那一行。

解析顺序（谁先有就用谁）
------------------------
    显式 uid  >  options["memory_owner"]  >  本线程的当前 uid  >  None

**刻意不做"最近用户"兜底**：
`func/` 里有 40+ 处 LLM 实例化，绝大多数是工具/分析类任务（新闻、天气、情绪更新、
abmem 写入、弹幕、绘画…）。如果按"最近那个用户"猜，这些任务就会被动带上那个人的
记忆 —— 轻则串人，重则**自我污染**（负责写记忆的任务带着记忆去写，越写越偏）。
所以：**默认不带记忆，只有调用处显式传 uid（或本线程已标记）才带。**
"""

from __future__ import annotations

import re
import threading
from typing import Dict, Optional

#: 协议字段名（唯一出处）
FIELD = "memory_owner"

_FORMAL = re.compile(r"^\d{6}$")

#: 线程级"当前消息的用户"。**不进新线程** —— 这正是我们要的隔离：
#: 主回复线程带 uid（能挂记忆），后台工具线程拿不到（天然不污染）。
_CTX = threading.local()


def set_current_uid(uid) -> None:
    """在"处理某条用户消息"的线程入口调用一次。用完记得 clear。"""
    _CTX.uid = str(uid).strip() if is_formal(uid) else ""


def clear_current_uid() -> None:
    """处理完一条消息后清掉，避免线程复用/线程池时继承上一个人的 uid。"""
    _CTX.uid = ""


def current_uid() -> Optional[str]:
    uid = getattr(_CTX, "uid", "")
    return uid or None


def is_formal(uid) -> bool:
    """是不是"该长期记忆的人"。与引擎侧 `DmemRegistry.is_formal()` 同规则。"""
    text = str(uid or "").strip()
    if not text or text.lower().startswith("temp"):
        return False
    return bool(_FORMAL.match(text))


def owner_for(uid=None, options: Optional[Dict] = None) -> Optional[str]:
    """解析出本次请求该用谁的记忆。返回正式 uid 或 None（None = 不挂记忆）。"""
    for candidate in (uid, (options or {}).get(FIELD), current_uid()):
        if is_formal(candidate):
            return str(candidate).strip()
    return None


def as_options(uid=None, options: Optional[Dict] = None) -> Optional[Dict]:
    """给调用处用：`options=as_options(uid)`。

    - 已有 options 时合并（不覆盖原键）；
    - 解析不到正式 uid 时返回 None（调用方原样传 None 即可）。
    """
    owner = owner_for(uid, options)
    if not owner:
        return None
    merged = dict(options or {})
    merged[FIELD] = owner
    return merged
