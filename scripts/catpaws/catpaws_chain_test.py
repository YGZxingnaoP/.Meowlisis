"""CatPaws 旧版联调脚本（已过时，仅留档）。

2026-10 重写了 func/catpaws 与 .vendor/.CatPaws（配置真值迁到 .vendor/.CatPaws/config.yml、
触发词改为「喵呜我要点外卖」+「手机」意图判断、角色回复走自有 port），本脚本里的
「操作手机：…」前缀与旧流程已不再生效。新的回归与真机脚本：

    scripts\\catpaws_bridge_test.py     # 不需要手机：触发→操作→追问→反思→end 的桥接回归（mock 设备）
    scripts\\catpaws_meituan_test.py    # 真机：美团点外卖（不经过主项目）
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.abspath(os.getcwd()) != ROOT:
    os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import func.log.default_log as _logmod

try:
    _logmod.DefaultLog()
except Exception:
    class _ConsoleLog:
        def __init__(self, *args, **kwargs):
            pass

        def getLogger(self):
            logger = logging.getLogger("catpaws_test")
            if not logger.handlers:
                handler = logging.StreamHandler(sys.stdout)
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                logger.addHandler(handler)
                logger.setLevel(logging.INFO)
            return logger

    _logmod.DefaultLog = _ConsoleLog
    print("[日志] logs/ 不可写，改走控制台")

if "--verbose" not in sys.argv:
    logging.disable(logging.INFO)

from func.catpaws.config import CWCatPawsConfig
from func.catpaws.client import CWCatPawsClient
from func.catpaws.core import CWCatPawsCore
from func.pipeline.msg_catpaws import MsgCatPawsBridge

SERVICE = os.path.join(ROOT, ".vendor", ".CatPaws", "src", "cw", "server.py")
LAUNCHER = os.path.join(ROOT, ".vendor", ".CatPaws", "catpaws-launcher", "start.cmd")
SHOT_DIR = os.path.join(os.environ.get("TEMP", ROOT), "catpaws_test")
LOG_DIR = SHOT_DIR

log = _logmod.DefaultLog().getLogger()
cfg = CWCatPawsConfig()
client = CWCatPawsClient(cfg)


def wait_service(seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if client.health().get("ok"):
            return True
        time.sleep(0.5)
    return False


def ensure_service(start):
    if wait_service(2):
        return True
    if not start:
        return False
    print("[服务] 未运行，启动 %s" % SERVICE)
    subprocess.Popen([sys.executable, SERVICE], cwd=ROOT,
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    return wait_service(30)


def status():
    print("[配置] %s  enabled=%s  poll=%ss  max_run=%ss  notify=%s"
          % (cfg.base_url(), cfg.enabled, cfg.poll_sec, cfg.max_run_sec, cfg.notify))
    remote = client.status()
    if not remote.get("ok"):
        print("[服务] 不可用：%s" % remote.get("message", ""))
        print("[提示] 控制台服务：%s" % SERVICE)
        return False
    device = remote.get("device") or {}
    info = device.get("info") or {}
    screen = info.get("screen") or {}
    session = remote.get("session") or {}
    print("[服务] ok")
    print("[设备] mock=%s  pixel=%s  scale=%s  error=%s"
          % (device.get("mock"), screen.get("pixel"), screen.get("scale"),
             device.get("error", "")))
    print("[链路] phase=%s  session=%s  busy=%s"
          % (session.get("phase"), session.get("session"), remote.get("agent_busy")))
    final = (remote.get("final") or "").strip()
    if final:
        print("[上次] %s" % final[:300])
    if device.get("mock") or device.get("error"):
        print("[提示] 设备没连上：先跑 %s，看到 /cw/v1/ping 200 再回来" % LAUNCHER)
        return False
    return True


def shot(tag):
    png, error = client.shot(720)
    if not png:
        print("[截图] 失败：%s" % error)
        return ""
    try:
        os.makedirs(SHOT_DIR, exist_ok=True)
        path = os.path.join(SHOT_DIR, "%s_%s.png" % (tag, time.strftime("%Y%m%d_%H%M%S")))
        with open(path, "wb") as handle:
            handle.write(png)
    except Exception as exc:
        print("[截图] 保存失败：%s" % exc)
        return ""
    print("[截图] %s" % path)
    return path


_PENDING = []
_PENDING_LOCK = threading.Lock()
_CLOG = None


class _ChatLog:
    def __init__(self, path):
        self.path = path
        self.handle = open(path, "w", encoding="utf-8", buffering=1)

    def write(self, text):
        try:
            self.handle.write(str(text) + "\n")
            self.handle.flush()
        except Exception:
            pass

    def start_window(self):
        command = ("chcp 65001 > $null; "
                   "Write-Host '== CatPaws 手机操作过程（只读，不要在这个窗口打字）==' -ForegroundColor Cyan; "
                   "Get-Content -LiteralPath '%s' -Encoding UTF8 -Wait -Tail 300" % self.path)
        subprocess.Popen(["powershell", "-NoExit", "-Command", command],
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def emit(text):
    if not text:
        return
    if _CLOG is not None:
        _CLOG.write(text)
        return
    with _PENDING_LOCK:
        _PENDING.append(str(text))


def announce(text):
    print(text, flush=True)
    if _CLOG is not None:
        _CLOG.write(text)


def flush_pending():
    with _PENDING_LOCK:
        items = list(_PENDING)
        del _PENDING[:]
    for line in items:
        print(line, flush=True)


def format_item(item):
    kind = item.get("kind")
    ts = str(item.get("ts", ""))[-12:]
    if kind == "tool_call":
        args = json.dumps(item.get("args") or {}, ensure_ascii=False)
        return "  %s 工具 %s %s" % (ts, item.get("tool"), args[:240])
    if kind in ("single", "sequence"):
        steps = item.get("steps") or []
        return "  %s 执行 %sms %s" % (ts, item.get("elapsed_ms"),
                                     item.get("action") or "；".join(steps)[:200])
    if kind == "observe":
        texts = item.get("texts") or []
        return "  %s 观察 %s %d条 %s" % (ts, item.get("mode"), len(texts),
                                        "、".join(texts[:8]))
    if kind == "assistant":
        return "  %s 模型 %s" % (ts, (item.get("text") or "")[:240])
    if kind in ("error", "tool_error"):
        return "  %s 错误 %s %s" % (ts, item.get("code"), item.get("message"))
    if kind == "phase":
        lines = str(item.get("goal") or "").splitlines()
        goal = lines[0][:60] if lines else ""
        return "  %s 阶段 %s %s" % (ts, item.get("phase"), item.get("reason") or goal)
    if kind == "stop":
        return "  %s 停止 %s" % (ts, item.get("reason"))
    return ""


def show(item):
    line = format_item(item)
    if line:
        print(line)


def watch(core, started, timeout):
    items = client.ops(500).get("items") or []
    seen = len(items)
    last = 0.0
    while time.time() - started < timeout:
        snapshot = core.state.snapshot()
        session = str(snapshot.get("session") or "")
        items = client.ops(500).get("items") or []
        if len(items) < seen:
            seen = 0
        for item in items[seen:]:
            if session and item.get("session") != session:
                continue
            show(item)
        seen = len(items)
        now = time.time()
        if now - last >= 10:
            print("  ... %d 秒 phase=%s" % (int(now - started), snapshot.get("phase")))
            last = now
        if not snapshot.get("active") and float(snapshot.get("updated_at") or 0) >= started:
            return snapshot
        time.sleep(1.5)
    print("[超时] 到点仍未结束，发停止")
    core.stop("timeout")
    return core.state.snapshot()


def finish(snapshot, started):
    elapsed = int(time.time() - started)
    print("")
    print("[结果] ok=%s  reason=%s  耗时=%ss"
          % (snapshot.get("ok"), snapshot.get("reason"), elapsed))
    print("[结论] %s" % (str(snapshot.get("final") or "").strip()[:600] or "（无正文）"))
    shot("result")


def _make_llm():
    from func.llm.config import LLMConfig
    conf = LLMConfig()
    kind = conf.local_llm_type
    if kind == "meowllm":
        from func.llm.port.meowllm import MeowLLMLLM
        return MeowLLMLLM(conf)
    if kind == "gemini":
        from func.llm.port.gemini import GeminiLLM
        return GeminiLLM(conf)
    if kind == "aliyun":
        from func.llm.port.aliyun import AliyunLLM
        return AliyunLLM(conf)
    from func.llm.port.deepseek import DeepSeekLLM
    return DeepSeekLLM(conf)


class _StreamFilter:
    def __init__(self):
        self._tag = ""
        self._in_think = False
        self._bracket = 0
        self._paren = 0

    def feed(self, char):
        if self._tag:
            self._tag += char
            if "<think>".startswith(self._tag) or "</think>".startswith(self._tag):
                if self._tag == "<think>":
                    self._in_think = True
                    self._tag = ""
                elif self._tag == "</think>":
                    self._in_think = False
                    self._tag = ""
                return ""
            tag, self._tag = self._tag, ""
            return "".join(self.feed(item) for item in tag)
        if char == "<":
            self._tag = "<"
            return ""
        if self._in_think:
            return ""
        if char == "【":
            self._bracket += 1
            return ""
        if char == "】":
            if self._bracket > 0:
                self._bracket -= 1
            return ""
        if self._bracket > 0:
            return ""
        if char in "（(":
            self._paren += 1
            return ""
        if char in "）)":
            if self._paren > 0:
                self._paren -= 1
            return ""
        if self._paren > 0:
            return ""
        return char


class _Chat:
    def __init__(self, meowid, ltmem=False):
        from func.config.app_config import AppConfig
        from func.llm.config import LLMConfig
        from func.llm.message_builder import MessageBuilder
        from func.llm.prompt_get import PromptGet
        from func.pipeline.llm_toolbox import LLMToolboxBridge

        self.meowid = meowid
        self.ai_name = AppConfig().ai_name or "AI"
        self.llm = _make_llm()
        self.prompt = PromptGet()
        self.builder = MessageBuilder(LLMConfig().short_term_rounds)
        self.tb = LLMToolboxBridge()
        self.merge = self.tb.merge_enabled()
        self.tools = self.tb.get_schemas() if self.merge else []
        self.ltmem = None
        if ltmem:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            self.ltmem = MeowLLMLtMemBridge()
        self._turn_lock = threading.Lock()

    def turn(self, text):
        with self._turn_lock:
            self._turn(text)

    def _turn(self, text):
        from func.llm.output import Output
        from func.pipeline.id_signup import display_name
        from func.pipeline.llm_toolbox import ToolCallAccumulator

        if self.ltmem is not None:
            try:
                self.ltmem.record_user_message(self.meowid, text)
            except Exception:
                pass

        plan = self.tb.pre_route_plan(text, self.meowid) if self.merge else None
        if plan is not None:
            name, arguments = plan
            if name:
                threading.Thread(target=self.tb.handle_tool_calls,
                                 args=([{"name": name, "arguments": arguments}],
                                       self.meowid, text), daemon=True).start()
            self.builder.add_user_message(self.meowid, text)
            print("（本地规则硬触发：%s，跳过主回复）" % (name or "插件会话拦截"))
            return

        system_prompt = self.prompt.get_system_prompt(display_name(self.meowid), text)
        if self.merge and self.tools:
            system_prompt = self.tb.attach_tool_hint(system_prompt)
        messages = self.builder.build_messages(self.meowid, system_prompt, text)

        acc = ToolCallAccumulator()
        stream = self.llm.chat_stream(messages, tools=self.tools or None,
                                      tool_choice="auto", enable_thinking=False)
        content = ""
        live = _StreamFilter()
        print("%s> " % self.ai_name, end="", flush=True)
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                content += piece
                visible = "".join(live.feed(item) for item in piece)
                if visible:
                    print(visible, end="", flush=True)
            if self.merge and getattr(delta, "tool_calls", None):
                acc.add(delta.tool_calls)
        print(flush=True)

        cleaned = Output.clean_text(content)
        self.builder.add_user_message(self.meowid, text)
        if cleaned:
            self.builder.add_assistant_message(self.meowid, cleaned, self.ai_name)
            if self.ltmem is not None:
                try:
                    self.ltmem.record_ai_message(self.meowid, self.ai_name, cleaned)
                except Exception:
                    pass
        else:
            print("（这次没有正文%s）" % ("，只回了工具调用" if acc.has_calls() else ""))
        if self.merge and acc.has_calls():
            threading.Thread(target=self.tb.handle_tool_calls,
                             args=(acc.payload(), self.meowid, text), daemon=True).start()

    def ack(self, text):
        from func.llm.output import Output
        from func.pipeline.id_signup import display_name
        with self._turn_lock:
            system_prompt = self.prompt.get_system_prompt(display_name(self.meowid), text)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    "主人刚给你一条补充指令：%s\n"
                    "用你自己的口吻回一句，表示你收到了、并且照这个来；一句话，不要客套，不要复述。" % text
                )},
            ]
            content = ""
            live = _StreamFilter()
            print("%s> " % self.ai_name, end="", flush=True)
            for chunk in self.llm.chat_stream(messages, enable_thinking=False):
                if not getattr(chunk, "choices", None):
                    continue
                piece = getattr(chunk.choices[0].delta, "content", None)
                if piece:
                    content += piece
                    visible = "".join(live.feed(item) for item in piece)
                    if visible:
                        print(visible, end="", flush=True)
            print(flush=True)


def _watch_chain(core, conv, stop_flag, started, quiet=False):
    seen = len(client.ops(500).get("items") or [])
    last_done = started
    last_phase = ""
    last_note = 0.0
    while not stop_flag.wait(1.5):
        try:
            snapshot = core.state.snapshot()
            session = str(snapshot.get("session") or "")
            if snapshot.get("active"):
                items = client.ops(500).get("items") or []
                if len(items) < seen:
                    seen = 0
                for item in items[seen:]:
                    if session and item.get("session") != session:
                        continue
                    if not quiet:
                        emit(format_item(item))
                seen = len(items)
                phase = str(snapshot.get("phase") or "")
                now = time.time()
                if not quiet and (phase != last_phase or now - last_note > 30):
                    emit("  ... 手机操作中（%s，已 %.0f 秒）"
                         % (phase, now - float(snapshot.get("started_at") or now)))
                    last_phase = phase
                    last_note = now
                continue
            done_at = float(snapshot.get("updated_at") or 0)
            if not snapshot.get("goal") or done_at <= last_done:
                continue
            last_done = done_at
            body = str(snapshot.get("final") or snapshot.get("reason") or "").strip()
            announce("[手机] %s · ok=%s · reason=%s · %s 秒"
                     % ("完成" if snapshot.get("ok") else "失败", snapshot.get("ok"),
                        snapshot.get("reason"),
                        int(done_at - float(snapshot.get("started_at") or done_at))))
            announce("[手机] 结论：%s" % body[:600])
            shot("result")
            conv.turn("（手机那边回来了，%s：%s）"
                      % ("成了" if snapshot.get("ok") else "没成", body or "没有结果正文"))
        except Exception as exc:
            emit("  [watcher] %s: %s" % (type(exc).__name__, exc))


def chat(meowid, ltmem=False, auto_confirm=False, quiet=False, split=True):
    global _CLOG
    if split and not quiet:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            path = os.path.join(LOG_DIR, "chat_ops_%s.log" % time.strftime("%Y%m%d_%H%M%S"))
            _CLOG = _ChatLog(path)
            _CLOG.start_window()
            print("[日志] 操作过程在另一个窗口显示：%s" % path)
        except Exception as exc:
            _CLOG = None
            print("[日志] 独立窗口开不了（%s），操作过程留在本窗口" % exc)
    if not ensure_service(True):
        print("[手机] 控制台服务起不来：%s" % SERVICE)
    remote = client.status()
    device = remote.get("device") or {}
    ready = bool(remote.get("ok")) and not device.get("mock") and not device.get("error")
    if ready:
        print("[手机] 链路就绪 %s" % cfg.base_url())
    else:
        print("[手机] 链路不可用：%s（对话仍可用，触发词不会下发）"
              % (remote.get("message") or device.get("error") or "设备未连接"))
        print("[手机] 设备侧没连上就先跑：%s" % LAUNCHER)

    conv = _Chat(meowid, ltmem=ltmem)
    core = CWCatPawsCore()
    core.set_notify(False)
    core.voice.bind_console(True, auto_confirm=auto_confirm)
    stop_flag = threading.Event()
    if ready:
        threading.Thread(target=_watch_chain,
                         args=(core, conv, stop_flag, time.time()), daemon=True).start()

    print("[对话] 文字版主链路；身份 %s；输入 q 退出" % meowid)
    print("[对话] 触发词示例：操作手机：打开QQ，给我的电脑发一条消息：测试")
    print("[对话] 手机有问题会由角色来问你，直接打字回答")
    while True:
        flush_pending()
        try:
            text = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            break
        flush_pending()
        if text in ("q", "quit", "exit", "退出"):
            break
        if not text:
            continue

        if core.voice.route_console(text):
            print("（已作为手机提问的回答送过去）")
            continue

        from func.toolbox.excuse import TBExcuse
        if TBExcuse().route_text(text, meowid):
            print("（已作为提问的回答送过去）")
            continue

        if core.state.is_active():
            if core.say(text):
                print("（已作为补充指令送给手机）")
                conv.ack(text)
            else:
                print("（补充指令没送出去）")
            continue

        hit, goal = core.if_start.decide(text)
        if hit:
            if core.state.is_active():
                print("（上一轮手机操作还在跑；要打断就说「停止操作」）")
            else:
                ok, message = core.start(goal, meowid, "chat")
                if not ok:
                    print("（手机链路没启动：%s）" % message)

        conv.turn(text)

    stop_flag.set()
    if core.state.is_active():
        core.stop("exit")
    print("[对话] 结束")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="status",
                        choices=["status", "device", "run", "goal", "stop", "ops", "chat"])
    parser.add_argument("text", nargs="?", default="")
    parser.add_argument("--meowid", default="")
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--service", action="store_true")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--ltmem", action="store_true")
    parser.add_argument("--auto-confirm", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--inline", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.command == "chat":
        return chat(args.meowid or "000001", ltmem=args.ltmem,
                    auto_confirm=args.auto_confirm, quiet=args.quiet,
                    split=not args.inline)

    if not ensure_service(args.service):
        status()
        return 1

    if args.command == "status":
        status()
        return 0

    if args.command == "ops":
        for item in client.ops(80).get("items") or []:
            show(item)
        return 0

    if args.command == "stop":
        core = CWCatPawsCore()
        print("[停止] %s" % core.stop("script"))
        return 0

    if not status():
        return 1

    if args.command == "device":
        shot("device")
        return 0

    core = CWCatPawsCore()
    core.set_notify(bool(args.notify))
    timeout = args.timeout or (cfg.max_run_sec + 30)
    started = time.time()

    if args.command == "run":
        if not args.text.strip():
            print("用法：run \"操作手机：打开QQ，给我的电脑发一条消息：测试\"")
            return 1
        MsgCatPawsBridge().send_to_catpaws(args.text, args.meowid, "script")
        if not core.state.is_active():
            print("[未启动] 触发词没命中，或设备/服务不可用；看上面状态")
            return 2
    else:
        goal = args.text.strip() or input("目标：").strip()
        ok, message = core.start(goal, args.meowid, "script", notify=bool(args.notify))
        if not ok:
            print("[未启动] %s" % message)
            return 2

    print("[开始] %s" % (args.text.strip()[:120] or "(无)"))
    snapshot = watch(core, started, timeout)
    finish(snapshot, started)
    return 0 if snapshot.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
