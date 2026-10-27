# -*- coding: utf-8 -*-
# scripts/catpaws_live_log.py
# 真机联调·日志窗口：同时跟三条流（主程序日志 / CatPaws 服务日志 / 操作流水），增量不刷屏
#
# 用法（一般由 scripts/catpaws_live.bat 一起拉起）：
#   runtime\311\python.exe scripts\catpaws_live_log.py
import datetime
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = datetime.date.today().strftime("%Y-%m-%d")
TEMP_CATPAWS = os.path.join(os.environ.get("TEMP", "."), "catpaws")

SOURCES = [
    ("主程序", os.path.join(ROOT, "logs", "log_%s.txt" % DAY), 0),
    ("服务", os.path.join(ROOT, "logs", "svc_catpaw_%s.log" % DAY), 0),
    ("流水", os.path.join(ROOT, "logs", "catpaws_ops", "ops_%s.jsonl" % DAY), 0),
    ("流水", os.path.join(TEMP_CATPAWS, "catpaws_ops", "ops_%s.jsonl" % DAY), 0),
    ("服务", os.path.join(TEMP_CATPAWS, "svc_catpaw_%s.log" % DAY), 0),
]


def _hms(now=None):
    return (now or datetime.datetime.now()).strftime("%H:%M:%S")


def describe_op(item):
    """把一条操作流水翻成一行中文"""
    kind = item.get("kind") or ""
    if kind == "assistant":
        return "[角色] %s" % str(item.get("text") or "")[:120]
    if kind == "tool_call":
        args = json.dumps(item.get("args") or {}, ensure_ascii=False)
        return "[工具] %s %s" % (item.get("tool"), args[:100])
    if kind in ("single", "sequence"):
        body = item.get("action") or " → ".join(item.get("steps") or [])
        return "[动作] %s %s %sms" % (body, "✓" if item.get("ok") else "✗ " + str(item.get("code") or ""),
                                     item.get("elapsed_ms") or 0)
    if kind == "observe":
        texts = (item.get("texts") or [])[:8]
        info = " / ".join(texts) if texts else str((item.get("screen") or {}).get("pixel"))
        return "[观察] %s" % info[:120]
    if kind == "phase":
        label = {"control": "操作中", "recording": "反思中", "end": "结束", "idle": "空闲"}.get(
            item.get("phase"), item.get("phase"))
        extra = "（%s）" % item.get("reason") if item.get("reason") else ""
        return "── 阶段：%s%s" % (label, extra)
    if kind == "ask":
        return "[提问] %s" % str(item.get("question") or "")[:120]
    if kind == "answer":
        return "[回答] %s" % (item.get("answer") or "（没回答）")
    if kind == "task_done":
        return "[收尾] %s ← %s" % (str(item.get("summary") or "")[:80], item.get("answer"))
    if kind == "write_confirm":
        return "[写脚本确认] %s ← %s" % (item.get("title"), item.get("answer"))
    if kind in ("action_created", "action_updated"):
        return "[脚本] %s %s" % (kind, item.get("action_id"))
    if kind == "keep_awake":
        return "[防息屏] 轻点一下"
    if kind == "device_locked":
        return "[锁屏] 等主人解锁"
    if kind == "error":
        return "[错误] %s %s" % (item.get("code") or "", str(item.get("message") or "")[:100])
    if kind in ("stop", "stop_request", "stop_request"):
        return "[停止] %s" % (item.get("reason") or "")
    if kind == "instruction":
        return "[插话] %s" % str(item.get("text") or "")[:100]
    if kind == "prompt":
        return "[提示词] 共 %s 字：%s…" % (item.get("chars"), str(item.get("head") or "")[:60])
    if kind == "task_done_forced":
        return "[收尾] 第 %s 次确认后直接结束（防止反复问）" % item.get("asks")
    if kind == "start_home":
        return "[动作] 回桌面 %s" % ("✓" if item.get("ok") else "✗")
    return ""


def read_new(path, offset):
    """从 offset 读到文件末尾，返回 (新行列表, 新 offset)"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], offset
    if size < offset:
        offset = 0
    if size == offset:
        return [], offset
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            blob = handle.read(size - offset)
    except OSError:
        return [], offset
    text = blob.decode("utf-8", "replace")
    if not text.endswith("\n"):
        cut = text.rfind("\n")
        if cut < 0:
            return [], offset
        text = text[:cut + 1]
    return text.splitlines(), offset + len(text.encode("utf-8"))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    print("=" * 64)
    print(" CatPaws 联调 · 日志（%s）" % DAY)
    print("=" * 64)
    for tag, path, _ in SOURCES:
        print(" [%s] %s %s" % (tag, "跟随" if os.path.exists(path) else "等待生成", path))
    print("=" * 64)

    seen = {}
    for _tag, path, _offset in SOURCES:
        try:
            seen[path] = os.path.getsize(path)
        except OSError:
            seen[path] = 0

    while True:
        for tag, path, _offset in SOURCES:
            offset = seen.get(path, 0)
            lines, offset = read_new(path, offset)
            seen[path] = offset
            for line in lines:
                body = line.strip()
                if not body:
                    continue
                if tag == "流水":
                    try:
                        item = json.loads(body)
                    except ValueError:
                        continue
                    text = describe_op(item)
                    if not text:
                        continue
                    stamp = str(item.get("ts") or "")[11:19] or _hms()
                    print("%s  %s" % (stamp, text))
                elif tag == "服务":
                    if not (body.startswith(("🐾", "🌐", "📺", "📱", "🖥", "🛑", "⚠")) or "已启动" in body):
                        continue
                    print("%s  [服务] %s" % (_hms(), body[:160]))
                else:
                    if "[CatPaws]" not in body:
                        continue
                    print("%s  [主程序] %s" % (_hms(), body[:160]))
        time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
