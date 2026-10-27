# -*- coding: utf-8 -*-
# scripts/catpaws_bridge_test.py
# func/catpaws ↔ .vendor/.CatPaws 桥接回归（不需要手机，服务端用 mock 设备 + 真模型）
#
# 验证链路：触发 → 启动（system_prompt/短期记忆/用户原话）→ 边说边操作 → 追问（走 TBExcuse）
#           → 收尾确认 → 反思 → end 释放；角色回复写 phone_control_response 并交给 TTS。
#
# 用法（在项目根目录）：
#   runtime\311\python.exe scripts\catpaws_bridge_test.py
#   runtime\311\python.exe scripts\catpaws_bridge_test.py --goal "打开设置看看有哪些选项" --auto "没有了|先别写"
# 说明：
#   * 会自己拉起一个 mock 的服务端（18110 已被占用则复用，结束时只关自己拉起的那个）；
#   * 会把 CWCatPawsConfig().allow_mock 临时置真，不改动任何配置文件；
#   * --home 可把运行时目录（logs/.temp）指到别处，便于在沙箱/临时目录里跑。
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, ".vendor", ".CatPaws", "src", "cw", "server.py")


def api(path, payload=None, timeout=10):
    url = "http://127.0.0.1:18110" + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def server_alive():
    return bool(api("/cw/status", timeout=2).get("ok"))


def start_server(wait_sec=25):
    """拉起 mock 服务端，返回 Popen 或 None"""
    proc = subprocess.Popen([sys.executable, "-u", SERVER, "--mock"],
                            cwd=os.path.join(ROOT, ".vendor", ".CatPaws"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if server_alive():
            return proc
        time.sleep(0.6)
    return proc


def resolve_meowid(given):
    if given:
        return given
    try:
        sys.path.insert(0, ROOT)
        from func.pipeline.id_signup import IdSignupBridge
        bridge = IdSignupBridge()
        for user in bridge.list_users():
            meowid = str(user.get("meowid") or "").strip()
            if meowid and not meowid.startswith("temp-"):
                return meowid
    except Exception:
        pass
    return ""


def short_memory_tail(kind, limit=60):
    """读近期短期记忆里某一类型的条目（角色回复/用户指导）"""
    path = os.path.join(".temp", "public_short_mem.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    items = [m for m in data if isinstance(m, dict) and m.get("type") == kind]
    return items[-limit:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", default="帮我用手机打开设置，看看第一屏有哪些选项，然后告诉我。")
    parser.add_argument("--meowid", default="")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--auto", default="没有了|先别写，就这样吧")
    parser.add_argument("--home", default="")
    args = parser.parse_args()

    if args.home:
        os.makedirs(args.home, exist_ok=True)
        os.chdir(args.home)
    os.makedirs("logs", exist_ok=True)
    os.makedirs(".temp", exist_ok=True)
    os.makedirs("character", exist_ok=True)

    sys.path.insert(0, ROOT)
    from func.catpaws.config import CWCatPawsConfig
    from func.catpaws.core import CWCatPawsCore
    from func.toolbox.excuse import TBExcuse

    spawned = None
    if not server_alive():
        spawned = start_server()
        if not server_alive():
            print("!! 服务端没起来，先手动启动 .vendor/CatPaws/src/cw/server.py --mock")
            return 1
    try:
        with urllib.request.urlopen("http://127.0.0.1:18110/cw/status", timeout=5) as resp:
            live = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        if not (live.get("device") or {}).get("mock"):
            print("!! 18110 上跑的是真机服务（device.mock=false），不是 mock 回归环境")
            print("   先停掉它（GUI 里 ■ 或结束 python 进程），再跑本回归")
            return 1
    except Exception as exc:
        print("!! 读不到 /cw/status：%s" % exc)
        return 1

    meowid = resolve_meowid(args.meowid) or "temp-000001"
    config = CWCatPawsConfig()
    config.allow_mock = True
    config.refresh(force=True)
    config.allow_mock = True

    core = CWCatPawsCore()
    print("meowid = %s" % meowid, flush=True)
    started = core.receive(args.goal, meowid, "test")
    print("receive -> %s（True=已接管）" % started, flush=True)
    if not started:
        print("!! 没被接管：检查触发词/意图判断/服务状态")
        return 1

    answers = [x.strip() for x in args.auto.split("|") if x.strip()]
    answer_index = 0
    seen_phase = ""
    seen_replies = 0
    started_at = time.time()
    excuse = TBExcuse()
    while time.time() - started_at < args.timeout:
        state = core.state.snapshot()
        if state.get("phase") and state["phase"] != seen_phase:
            seen_phase = state["phase"]
            print("[阶段] %s" % seen_phase, flush=True)
        replies = short_memory_tail("phone_control_response")
        if len(replies) > seen_replies:
            for item in replies[seen_replies:]:
                print("[角色] %s" % item.get("content", ""), flush=True)
            seen_replies = len(replies)
        if excuse.is_waiting(meowid):
            answer = answers[answer_index % len(answers)] if answers else ""
            answer_index += 1
            print("[追问] 回答：%s" % answer, flush=True)
            excuse.route_text(answer, meowid)
            time.sleep(0.8)
            continue
        if not state.get("active"):
            break
        time.sleep(0.8)

    state = core.state.snapshot()
    replies = short_memory_tail("phone_control_response")
    guides = short_memory_tail("phone_control_user")
    print("\n结束：active=%s phase=%s reason=%s" % (state.get("active"), state.get("phase"),
                                                  state.get("reason")), flush=True)
    print("角色回复条数=%d，用户指导条数=%d，回答次数=%d" % (len(replies), len(guides),
                                                     answer_index), flush=True)
    ok = (not state.get("active")) and len(replies) > 0
    print("RESULT %s" % ("OK" if ok else "FAIL"), flush=True)

    if spawned is not None:
        try:
            spawned.terminate()
            spawned.wait(timeout=8)
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
