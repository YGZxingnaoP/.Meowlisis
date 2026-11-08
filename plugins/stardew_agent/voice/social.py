# -*- coding: utf-8 -*-
"""角色间社交总线：一个 JSONL 文件，多个 AI 角色 / 多个实例都能读写。

用途：没有联机时也能「互相看见」——每个角色把自己的一句话和状态追加上去，
其它角色读最近 N 条，在自己的日记 / 群回复里回应。
"""

import json
import os
import time

MAX_KEEP = 500
TRIM_AT = 900


def _path(ctx):
    root = ctx.data_dir(per_user="")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "social.jsonl")


def post(ctx, speaker, text, kind="say", meta=None):
    """追加一条社交消息。"""
    record = {
        "ts": int(time.time()),
        "speaker": str(speaker or ""),
        "kind": str(kind or "say"),
        "text": str(text or ""),
        "meta": meta or {},
    }
    path = _path(ctx)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    _trim(path)
    return record


def read(ctx, limit=50, exclude=None, since_ts=0):
    """读最近 limit 条，可按 speaker 排除自己、按时间过滤。"""
    path = _path(ctx)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()[-MAX_KEEP:]

    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if exclude and record.get("speaker") == exclude:
            continue
        try:
            if int(record.get("ts") or 0) <= int(since_ts or 0):
                continue
        except (TypeError, ValueError):
            pass
        out.append(record)
    return out[-limit:]


def digest(ctx, speaker, limit=8):
    """给提示词用的一小段「别人最近在干嘛」。"""
    others = read(ctx, limit=limit, exclude=speaker)
    if not others:
        return ""
    lines = ["【农场社交】最近其它角色的话："]
    for record in others[-limit:]:
        stamp = time.strftime("%H:%M", time.localtime(int(record.get("ts") or 0)))
        lines.append("- %s %s：%s" % (stamp, record.get("speaker") or "?", record.get("text") or ""))
    return "\n".join(lines)


def last_ts(ctx):
    records = read(ctx, limit=1)
    try:
        return int(records[-1].get("ts") or 0) if records else 0
    except (TypeError, ValueError, IndexError):
        return 0


def _trim(path):
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
        if len(lines) <= TRIM_AT:
            return
        keep = lines[-MAX_KEEP:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.writelines(keep)
        os.replace(tmp, path)
    except Exception:
        pass
