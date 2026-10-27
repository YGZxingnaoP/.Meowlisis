# -*- coding: utf-8 -*-
# scripts/catpaws_live_dialog.py
# 真机联调·对话框：像平时聊天一样打字，走主项目链路（角色回复 + TTS + 记忆 + 手机操作）
#
# 配套：scripts/catpaws_live.bat 会同时开两个窗口（本对话框 + 日志）
# 前置：
#   1. 主程序（api.py，1800）在跑；
#   2. CatPaws 服务（18110）在跑，且 /cw/status 里 device.mock = false；
#   3. CatPawsRunner（8100）就绪（catpaws-launcher 的 start.cmd）。
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MAIN = "http://127.0.0.1:1800"
CATPAWS = "http://127.0.0.1:18110"
RUNNER = "http://127.0.0.1:8100/cw/v1/ping"


def _json(url, payload=None, timeout=10):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace") or "{}"
        return json.loads(body)
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return {"status": "error", "message": "HTTP %s" % exc.code}
    except Exception as exc:
        return {"status": "error", "message": str(exc), "offline": True}


def preflight():
    """开测前三项体检，返回 (ok, 说明列表)"""
    notes = []
    ok = True

    main = _json(MAIN + "/catpaws/status", timeout=5)
    if main.get("status") != "ok":
        ok = False
        notes.append("✗ 主程序（1800）没起来：先启动主程序，否则没有角色回复/TTS/记忆")
    else:
        notes.append("✓ 主程序在线（角色回复、TTS、记忆都在这边）")

    status = _json(CATPAWS + "/cw/status", timeout=5)
    if not status.get("ok"):
        ok = False
        notes.append("✗ CatPaws 服务（18110）没起来：启动球「手机操作」或日志中心点 ▶")
    else:
        device = status.get("device") or {}
        if device.get("mock"):
            ok = False
            notes.append("✗ CatPaws 服务现在拿的是 mock 假设备：手机就绪后重启一次服务")
        elif device.get("error"):
            ok = False
            notes.append("✗ 设备异常：%s" % device.get("error"))
        else:
            screen = (device.get("info") or {}).get("screen") or {}
            notes.append("✓ 真机在线：%s" % ("x".join(str(v) for v in screen.get("pixel") or [])))
        relay = status.get("relay") or {}
        notes.append("%s 视频中继：%s" % ("✓" if relay.get("device_online") else "·",
                                       "手机已连" if relay.get("device_online") else "手机未连（只影响画面，不影响操作）"))

    ping = _json(RUNNER, timeout=4)
    if ping.get("ok"):
        notes.append("✓ CatPawsRunner 就绪（%s）" % ((ping.get("data") or {}).get("version") or "?"))
    else:
        ok = False
        notes.append("✗ CatPawsRunner 没就绪：跑 .vendor/CatPaws/catpaws-launcher/start.cmd")
    return ok, notes


def resolve_meowid(given):
    if given:
        return given
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from func.pipeline.id_signup import IdSignupBridge
        for user in IdSignupBridge().list_users():
            meowid = str(user.get("meowid") or "").strip()
            if meowid and not meowid.startswith("temp-"):
                return meowid
    except Exception:
        pass
    return ""


def show_phase():
    status = _json(CATPAWS + "/cw/status", timeout=4)
    session = status.get("session") or {}
    phase = session.get("phase") or "?"
    label = {"control": "操作中", "recording": "反思中", "end": "已结束", "idle": "空闲"}.get(phase, phase)
    print("    [链路] %s %ss" % (label, session.get("elapsed_sec") or 0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meowid", default="")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ok, notes = preflight()
    print("=" * 64)
    print(" CatPaws 真机联调 · 对话框")
    print("=" * 64)
    for line in notes:
        print(" " + line)
    meowid = resolve_meowid(args.meowid)
    print(" 身份 meowid：%s" % (meowid or "（没找到，用 --meowid 指定）"))
    print("=" * 64)
    if not ok or not meowid:
        print(" 先按上面的 ✗ 修好再开测。")
        return 1

    print(" 直接像平时一样说话。示例：")
    print("   喵呜我要点外卖 我想吃麦当劳，别下单，走到确认页就行")
    print("   手机还我            （立刻停手）")
    print("   /status  看链路     /stop  强制停止     /quit 退出")
    print("=" * 64)

    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            return 0
        if not text:
            continue
        if text in ("/quit", "/exit", "quit", "exit"):
            print("再见")
            return 0
        if text == "/status":
            show_phase()
            continue
        if text == "/stop":
            print("   ", _json(MAIN + "/catpaws/stop", {}, timeout=10))
            continue
        result = _json(MAIN + "/msg", {"msg": text, "meowid": meowid, "source": "api"}, timeout=20)
        if result.get("catpaws"):
            print("    → 已交给手机操作链路（角色会边做边说，日志窗口能看到每一步）")
        elif result.get("status") == "成功":
            print("    → 已发给角色（这条没进手机链路）")
        else:
            print("    → 发送失败：%s" % (result.get("message") or result))
        time.sleep(0.6)
        show_phase()


if __name__ == "__main__":
    sys.exit(main())
