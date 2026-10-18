# -*- coding: utf-8 -*-
# func/meowllm/memory.py
"""δ-mem「按用户记忆」的协议适配层（只服务本地 MeowLLM，不污染其它平台）。

设计目标（对应需求：自己写协议 + 各 port 只传用户）
--------------------------------------------------
1. **协议集中一处**：请求体里的字段名 `memory_owner`、uid 的合法性规则，
   都只在这个文件里定义。改协议只改这里。
2. **调用处只传 uid**：任何调用点写 `options=memory.as_options(uid)` 即可。
3. **不污染其它平台**：deepseek / aliyun / gemini 的 port 只读 `options["model"]`，
   它们根本不会读这个键。

解析顺序（谁先有就用谁）
------------------------
    显式 uid  >  options["memory_owner"]  >  本线程的当前 uid  >  None

**刻意不做"最近用户"兜底**：
`func/` 里有 40+ 处 LLM 实例化，绝大多数是工具/分析类任务（新闻、天气、情绪
更新、abmem 写入、弹幕、绘画…）。如果按"最近那个用户"猜，这些任务就会被动
带上那个人的记忆 —— 轻则串人，重则**自我污染**（负责写记忆的任务带着记忆去
写，越写越偏）。所以：**默认不带记忆，只有调用处显式传 uid（或本线程已标记）
才带。**

合法性（只认正式号）
--------------------
    `^\\d{6}$` 才传；`temp-*`、空、未知一律 None —— 引擎侧也会再判一次，
    这里是第一道闸，避免把临时会话写进长期记忆。
"""

from __future__ import annotations

import re
import threading
from typing import Dict, Optional

#: 协议字段名（唯一出处，改协议只改这里）
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
    """解析出本次请求该用谁的记忆。返回正式 uid 或 None（None = 不挂记忆）。

    解析顺序：
        1. 调用处显式传的 uid
        2. options["memory_owner"]
        3. **本线程的当前消息 uid**（由 llm_core 在处理一条消息时设置）
    """
    for candidate in (uid, (options or {}).get(FIELD), current_uid()):
        if is_formal(candidate):
            return str(candidate).strip()
    return None


def as_options(uid=None, options: Optional[Dict] = None) -> Optional[Dict]:
    """给调用处用：`options=memory.as_options(uid)`。

    - 已有 options 时合并（不覆盖原键）；
    - 解析不到正式 uid 时返回 None（调用方原样传 None 即可）。
    """
    owner = owner_for(uid, options)
    if not owner:
        return None
    merged = dict(options or {})
    merged[FIELD] = owner
    return merged
