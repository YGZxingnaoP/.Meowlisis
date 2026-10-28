# -*- coding: utf-8 -*-
# scripts/catpaws_meituan_test.py
# 手机操作链路真机测试：直接对接 CatPaws 服务端，不经过主项目（LLM/记忆/TTS 全部不启用）
#
# 用法：
#   runtime\311\python.exe scripts\catpaws_meituan_test.py                 # 默认目标：打开美团点外卖
#   runtime\311\python.exe scripts\catpaws_meituan_test.py --goal "打开美团，点一份麦当劳送到家"
#   runtime\311\python.exe scripts\catpaws_meituan_test.py --auto "没有了|先别写"   # 自动回答（按顺序）
#   runtime\311\python.exe scripts\catpaws_meituan_test.py --shots           # 每 15 秒存一张截图
#
# 前置：
#   1. 手机插 USB、解锁、信任本机；
#   2. .vendor\CatPaws\catpaws-launcher\start.cmd 已跑起来（status.cmd 看到 /cw/v1/ping -> 200）；
#   3. CatPaws 服务已启动（GUI 启动球「手机操作」或 python .vendor\CatPaws\src\cw\server.py）。
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "http://127.0.0.1:18110"
RUNNER_URL = "http://127.0.0.1:8100/cw/v1/ping"
DEFAULT_PROMPT = (
    "你在替主人操作这台 iPhone。主人就在旁边看着，也会随时插话。\n"
    "用平常的语气说话，不要报告格式、不要复述规则；不确定就问。"
)


def request(method, path, payload=None, timeout=20):
    url = BASE_URL + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return {"ok": False, "message": str(exc)}
    try:
        return json.loads(body)
    except ValueError:
        return {"ok": False, "message": body[:200]}


def runner_ready():
    try:
        with urllib.request.urlopen(RUNNER_URL, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def describe(item):
    kind = item.get("kind") or ""
    if kind == "assistant":
        return "[角色] " + str(item.get("text") or "")
    if kind == "tool_call":
        return "[工具] %s %s" % (item.get("tool"), json.dumps(item.get("args"), ensure_ascii=False))
    if kind in ("single", "sequence"):
        body = item.get("action") or " → ".join(item.get("steps") or [])
        ok = "成功" if item.get("ok") else "失败"
        return "[动作] %s %s %sms" % (body, ok, item.get("elapsed_ms") or 0)
    if kind == "observe":
        texts = (item.get("texts") or [])[:8]
        return "[观察] " + (" / ".join(texts) if texts else str((item.get("screen") or {}).get("pixel")))
    if kind == "phase":
        return "[阶段] " + str(item.get("phase")) + ("（%s）" % item.get("reason") if item.get("reason") else "")
    if kind == "task_done":
        return "[收尾] %s（主人回复：%s）" % (item.get("summary"), item.get("answer"))
    if kind == "write_confirm":
        return "[写脚本确认] %s（主人回复：%s）" % (item.get("title"), item.get("answer"))
    if kind in ("action_created", "action_updated"):
        return "[脚本] %s %s" % (kind, item.get("action_id"))
    if kind == "ask":
        return "[问] " + str(item.get("question"))
    if kind == "answer":
        return "[答] " + str(item.get("answer"))
    if kind in ("stop", "stop_request"):
        return "[停止] " + str(item.get("reason"))
    if kind == "error":
        return "[错误] %s %s" % (item.get("code"), item.get("message"))
    if kind == "instruction":
        return "[你] " + str(item.get("text"))
    return ""


def take_shot(tag):
    url = BASE_URL + "/cw/screenshot?max_edge=960"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            blob = resp.read()
    except Exception as exc:
        print("  （截图失败：%s）" % exc, flush=True)
        return ""
    target_dir = os.path.join(os.environ.get("TEMP", "."), "catpaws_test")
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, "%s_%s.png" % (time.strftime("%H%M%S"), tag))
    with open(path, "wb") as handle:
        handle.write(blob)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", default="打开美团，点一份外卖（随便一家能送的店，选一份不算贵的餐），送到家。")
    parser.add_argument("--user-message", default="")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--shots", action="store_true")
    parser.add_argument("--shot-every", type=int, default=15)
    parser.add_argument("--auto", default="")
    args = parser.parse_args()

    if not runner_ready():
        print("!! CatPawsRunner 没就绪：先跑 .vendor/CatPaws/catpaws-launcher/start.cmd，"
              "status.cmd 看到 /cw/v1/ping -> 200 再来。", flush=True)
        return 1
    status = request("GET", "/cw/status")
    if not status.get("ok"):
        print("!! CatPaws 服务没起：%s" % status.get("message", ""), flush=True)
        return 1
    device = status.get("device") or {}
    if device.get("mock"):
        print("!! 当前是 mock 设备，先用真机。", flush=True)
        return 1
    print("设备：%s" % json.dumps((device.get("info") or {}).get("screen") or {}, ensure_ascii=False),
          flush=True)

    payload = {"goal": args.goal, "system_prompt": args.prompt, "memory": [],
               "user_message": args.user_message or args.goal, "meowid": "test"}
    started = request("POST", "/cw/start", payload)
    if not started.get("ok"):
        print("!! 启动失败：%s" % json.dumps(started, ensure_ascii=False)[:400], flush=True)
        return 1
    print("链路已启动：%s\n" % args.goal, flush=True)

    auto = [x.strip() for x in args.auto.split("|") if x.strip()]
    auto_index = 0
    seq = 0
    last_shot = 0.0
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        status = request("GET", "/cw/status")
        if not status.get("ok"):
            print("!! 服务断开", flush=True)
            break
        replies = request("GET", "/cw/replies?since=%d&limit=200" % seq)
        for item in replies.get("items") or []:
            seq = max(seq, int(item.get("seq") or 0))
            line = describe(item)
            if line:
                print(line, flush=True)
        question = (status.get("pending_question") or {})
        if question.get("question"):
            print("\n❓ %s" % question.get("question"), flush=True)
            if auto:
                answer = auto[auto_index % len(auto)]
                auto_index += 1
                print("   （自动回答）%s" % answer, flush=True)
            else:
                try:
                    answer = input("   你的回答（直接回车=不回答）：").strip()
                except EOFError:
                    answer = ""
            request("POST", "/cw/answer", {"text": answer})
            continue
        session = status.get("session") or {}
        if args.shots and time.time() - last_shot >= args.shot_every:
            path = take_shot("op")
            if path:
                print("   （截图 %s）" % path, flush=True)
            last_shot = time.time()
        if session.get("phase") == "end" or (session.get("phase") == "idle" and not status.get("agent_busy")):
            print("\n链路结束：phase=%s reason=%s" % (session.get("phase"), session.get("reason")), flush=True)
            break
        time.sleep(1.2)
    else:
        print("\n!! 超时，主动停止", flush=True)
        request("POST", "/cw/stop", {"reason": "test_timeout"})

    final = request("GET", "/cw/status")
    print("\n最终结果：\n%s" % (final.get("final") or "（无）"), flush=True)
    if args.shots:
        path = take_shot("final")
        if path:
            print("收尾截图：%s" % path, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
