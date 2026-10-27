# -*- coding: utf-8 -*-
# scripts/catpaws_device_test.py
# 真机测试：走主链路模块（真提示词 + 真短期记忆），但不起主程序、不开 HTTP 服务
#
# 和主程序完全同一条链路：
#   func.catpaws.core.CWCatPawsCore   启动链路 / 消费回复 / 写入记忆
#   func.catpaws.prompt.CWCatPawsPrompt  动态 system_prompt（pipeline/system_prompt 桥）+ 短期记忆
#   func.toolbox.excuse.TBExcuse.route_text  回答/插话（与 api.py 的 /msg、sensevoice 同一入口）
#
# 用法：scripts\catpaws_device_test.bat（对话 + 流水两个窗口）
import argparse
import datetime
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, ".vendor", ".CatPaws", "src")
VENDOR = os.path.join(ROOT, ".vendor", ".CatPaws")
PYTHON = os.path.join(ROOT, "runtime", "311", "python.exe")
API = "http://127.0.0.1:18110"
RUNNER = "http://127.0.0.1:8100/cw/v1/ping"


def http_json(url, payload=None, timeout=10):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data,
                                     method="POST" if data is not None else "GET",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return {"ok": False, "message": "HTTP %s" % exc.code}
    except Exception as exc:
        return {"ok": False, "offline": True, "message": str(exc)}


def ensure_service(log_path):
    """只要 CatPaws 服务（18110），主程序不启动"""
    status = http_json(API + "/cw/status", timeout=3)
    if status.get("ok"):
        return None
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    try:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        handle = open(log_path, "a", encoding="utf-8", errors="replace")
    except Exception:
        handle = None
    if handle is None:
        print(" ✗ 服务没起，而且日志目录不可写：先自己起一次服务再跑")
        return False
    subprocess.Popen([PYTHON, "-X", "utf8", os.path.join(SRC, "cw", "server.py")],
                     cwd=VENDOR, env=env, stdout=handle, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    print(" · 已拉起 CatPaws 服务，日志：%s" % log_path)
    return True


def wait_ready(deadline=45.0):
    """等服务就绪并等设备连上（服务端会自己每 5 秒重连一次）"""
    started = time.time()
    note = "服务 45 秒内没起来"
    while time.time() - started < deadline:
        status = http_json(API + "/cw/status", timeout=3)
        if status.get("ok"):
            device = status.get("device") or {}
            if device.get("mock"):
                return False, "服务拿的是 mock 假设备：手机就绪后重启服务"
            if device.get("online"):
                return True, status
            note = "设备还没连上：%s（正在自动重连…）" % (device.get("error") or "检查 8100")
        time.sleep(1.0)
    return False, note


class Terminal:
    """把链路里的角色发言、提问、阶段都打到终端（数据来自真实短期记忆）"""

    def __init__(self, core, memory_cls):
        self.core = core
        self.memory_cls = memory_cls
        self.seen = 0
        self.phase = ""
        self.running = True
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="cw-term").start()

    def _loop(self):
        while self.running:
            try:
                items = self.memory_cls().load()
            except Exception:
                items = []
            with self.lock:
                if len(items) > self.seen:
                    for item in items[self.seen:]:
                        self._show(item)
                    self.seen = len(items)
            try:
                snapshot = self.core.state.snapshot() or {}
            except Exception:
                snapshot = {}
            phase = str(snapshot.get("phase") or "")
            if phase and phase != self.phase:
                self.phase = phase
                label = {"control": "开始操作手机", "recording": "进入反思",
                         "end": "链路结束", "idle": "空闲"}.get(phase, phase)
                print("\n\033[90m── %s ──\033[0m" % label)
            time.sleep(0.7)

    def _show(self, item):
        role = str(item.get("role") or "")
        kind = str(item.get("type") or "")
        text = str(item.get("content") or "").strip()
        if not text:
            return
        if kind == "phone_control_response":
            print("\n\033[95m[角色]\033[0m %s" % text)
            print("\033[90m你> \033[0m", end="", flush=True)
        elif kind == "phone_control_user":
            print("\n\033[94m[你·已写记忆]\033[0m %s" % text)


def item_type(item):
    return str((item or {}).get("type") or "")


def resolve_identity():
    """找可用身份：先走 IdSignupBridge，失败就直接扫 character/userinfo"""
    try:
        from func.pipeline.id_signup import IdSignupBridge
        for user in IdSignupBridge().list_users():
            meowid = str(user.get("meowid") or "").strip()
            if meowid and not meowid.startswith("temp-"):
                return meowid
    except Exception:
        pass
    root = os.path.join(ROOT, "character", "userinfo")
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return ""
    real = [name for name in names if len(name) == 6 and name.isdigit()]
    temp = [name for name in names if name.startswith("temp-")]
    return (real or temp or [""])[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meowid", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--no-autostart", action="store_true")
    parser.add_argument("--log", default="")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    os.chdir(ROOT)
    sys.path.insert(0, ROOT)

    today = datetime.date.today().strftime("%Y-%m-%d")
    log_path = args.log or os.path.join(ROOT, "logs", "svc_catpaw_%s.log" % today)

    print("=" * 70)
    print(" CatPaws 真机测试（主链路模块，不启动主程序）")
    print("=" * 70)
    ping = http_json(RUNNER, timeout=4)
    if not ping.get("ok"):
        print(" ✗ CatPawsRunner 没就绪：先跑 .vendor/CatPaws/catpaws-launcher/start.cmd")
        return 1
    print(" ✓ 手机就绪：CatPawRunner %s" % ((ping.get("data") or {}).get("version") or "?"))

    if not args.no_autostart:
        ensure_service(log_path)

    ok, note = wait_ready()
    if not ok:
        print(" ✗ %s" % note)
        return 1
    status = note if isinstance(note, dict) else {}
    device = status.get("device") or {}
    screen = (device.get("info") or {}).get("screen") or {}
    print(" ✓ 真机在线：%s  %s" % ((device.get("info") or {}).get("system", {}).get("model", "?"),
                                 "x".join(str(v) for v in (screen.get("pixel") or []))))

    from func.catpaws.config import CWCatPawsConfig
    from func.catpaws.core import CWCatPawsCore
    from func.catpaws.prompt import CWCatPawsPrompt
    from func.pipeline.short_memory import ShortMemory
    from func.pipeline.id_signup import IdSignupBridge
    from func.toolbox.excuse import TBExcuse

    meowid = args.meowid.strip() or resolve_identity()
    if not meowid:
        print(" ✗ 没有可用身份：先用 --meowid 指定一个六位编号")
        return 1

    config = CWCatPawsConfig()
    if not config.enabled:
        print(" ✗ config.yml 里 catpaws 没启用")
        return 1
    core = CWCatPawsCore()
    prompt = CWCatPawsPrompt()
    excuse = TBExcuse()

    print(" ✓ 身份：%s" % meowid)
    print(" · 提示词来自 pipeline 动态构建，记忆来自 public_short_memory")
    print("-" * 70)
    print(" 直接说话就是目标；链路忙时你说的话＝回答/补充指令")
    print(" /stop 立刻停   /status 看阶段   /prompt 看本次提示词   /quit 退出")
    print("-" * 70)

    terminal = Terminal(core, ShortMemory)
    terminal.start()

    def run_goal(text):
        payload = prompt.build(text, meowid, text)
        print("\033[90m[提示词] %d 字｜记忆 %d 条｜用户原话 %d 字\033[0m"
              % (len(payload.get("system_prompt") or ""), len(payload.get("memory") or []),
                 len(payload.get("user_message") or "")))
        print("\033[90m[提示词开头] %s…\033[0m" % (payload.get("system_prompt") or "")[:80])
        started = core.start_task(text, meowid, text, "device_test")
        print(" → %s" % ("链路已启动" if started else "启动失败（看上面日志/服务状态）"))

    if args.goal:
        run_goal(args.goal)

    while True:
        try:
            text = input("\n\033[90m你> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出")
            break
        if not text:
            continue
        if text in ("/quit", "/exit", "quit", "exit"):
            break
        if text == "/stop":
            core.stop("user")
            print(" → 已请求停止")
            continue
        if text == "/status":
            snapshot = core.state.snapshot() or {}
            print(" → 阶段 %s / 忙 %s" % (snapshot.get("phase"), core.is_active()))
            continue
        if text == "/prompt":
            payload = prompt.build("（预览）", meowid, "")
            memory = payload.get("memory") or []
            print("\033[90m[提示词] %d 字｜带入短期记忆 %d 条\033[0m"
                  % (len(payload.get("system_prompt") or ""), len(memory)))
            for item in memory[-6:]:
                print("\033[90m  · %s: %s\033[0m"
                      % (item.get("role"), str(item.get("content"))[:60]))
            print("\033[90m%s\033[0m" % (payload.get("system_prompt") or "")[:1200])
            continue
        if excuse.route_text(text, meowid):
            print(" → 作为回答送给角色了")
            continue
        if core.is_active():
            core.send_text(text, meowid)
            print(" → 作为补充指令送进去了")
            continue
        run_goal(text)

    terminal.running = False
    core.stop("test_end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
