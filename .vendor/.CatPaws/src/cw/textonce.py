"""同一段文字只写一次：挡住 OCR 误判、换工具重试造成的重复输入。

只按文本内容记，不认控件、不看界面：已经成功写进输入框的文字，短时间内再写
就跳过。清空（delete）、发送（return）、换界面（home/launch_app/activate_app/
terminate_app）都会让记录失效，所以「发完同一句话再发一次」「换个 App 打同样
的字」不受影响。设备端执行失败不记账，下次合法重试仍然放行。
"""

import re
import threading
import time

DEFAULT_TTL_SEC = 30.0
WRITE_ACTIONS = ("paste_text", "type_text")
CLEAR_KEYS = ("delete", "return", "home")
RESET_ACTIONS = ("launch_app", "activate_app", "terminate_app")
_PRUNE_EVERY_SEC = 1.0

_lock = threading.Lock()
_seen = {}
_last_prune = [0.0]


def key_of(text):
    """归一化：去掉所有空白，避免换行/空格差异漏判"""
    return re.sub(r"\s+", "", str(text or ""))


def _prune(now, ttl):
    for key, at in list(_seen.items()):
        if now - at > ttl:
            _seen.pop(key, None)
    _last_prune[0] = now


def _fresh(now):
    if now - _last_prune[0] >= _PRUNE_EVERY_SEC:
        _prune(now, DEFAULT_TTL_SEC)


def seen(text, ttl=DEFAULT_TTL_SEC):
    """这段文字是不是刚刚已经成功写过"""
    key = key_of(text)
    if not key:
        return False
    now = time.time()
    with _lock:
        _fresh(now)
        at = _seen.get(key)
        return at is not None and now - at <= ttl


def mark(text):
    """记一笔「这段文字已经成功写进输入框」"""
    key = key_of(text)
    if not key:
        return
    now = time.time()
    with _lock:
        _seen[key] = now


def reset():
    """新一轮链路开始：清空，不跨任务记忆"""
    with _lock:
        _seen.clear()
        _last_prune[0] = 0.0


def filter_steps(steps, ttl=DEFAULT_TTL_SEC):
    """按顺序过一遍动作，剔除重复写入

    清空/发送/换界面会让已有记录失效；返回 (保留的步骤, 跳过数, 本次待记账的文本键)。
    待记账的键只在设备确认执行成功后才 mark，执行失败允许下次合法重试。
    """
    kept = []
    skipped = 0
    pending = []
    batch = set()
    now = time.time()
    with _lock:
        _fresh(now)
        for step in steps:
            name = str(step.get("action") or "")
            reset = (name == "press_key" and str(step.get("key") or "") in CLEAR_KEYS) \
                or name in RESET_ACTIONS
            if reset:
                _seen.clear()
                batch.clear()
                kept.append(step)
                continue
            if name in WRITE_ACTIONS:
                key = key_of(step.get("text"))
                if key:
                    at = _seen.get(key)
                    if (at is not None and now - at <= ttl) or key in batch:
                        skipped += 1
                        continue
                    batch.add(key)
                    pending.append(key)
            kept.append(step)
    return kept, skipped, pending


def mark_many(keys):
    now = time.time()
    with _lock:
        for key in keys or []:
            if key:
                _seen[key] = now
