# -*- coding: utf-8 -*-
"""真机测试宿主：不依赖主程序加载插件，也能把面板和 Agent 真跑起来。

它做三件事：
    1. 用主程序同一个文本模型（ctx.llm()）给 Agent 用；
    2. 连接游戏内 mod 的 /state 与 /command（真的执行游戏动作）；
    3. 启动插件面板（默认 127.0.0.1:8760），浏览器打开就能输入指令测试。

用法（在项目根目录，游戏已启动并读档）：
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_host.py
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_host.py --port 8761 --autostart
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_host.py --ask "去农场浇地"

Ctrl+C 退出；退出会顺带停掉 Agent 的后台线程。
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from plugins.stardew_agent.core.bridge import Bridge  # noqa: E402
from plugins.stardew_agent.runner.agent import Agent  # noqa: E402
from plugins.stardew_agent.web import DashboardServer  # noqa: E402


class _Log:
    def info(self, message, *args):
        print("[信息] " + (message % args if args else str(message)), flush=True)

    def warning(self, message, *args):
        print("[警告] " + (message % args if args else str(message)), flush=True)

    def exception(self, message, *args):
        print("[异常] " + (message % args if args else str(message)), flush=True)


class LiveCtx:
    """和主程序插件上下文同名的最小实现。"""

    def __init__(self, config, data_dir=""):
        self.config = config
        self.log = _Log()
        self.dir = data_dir or os.path.join(
            os.environ.get("TEMP", os.path.expanduser("~")), "stardew_agent_live")
        os.makedirs(self.dir, exist_ok=True)

    def data_dir(self, per_user=None):
        os.makedirs(self.dir, exist_ok=True)
        return self.dir

    def ai_name(self):
        try:
            from func.config.app_config import AppConfig
            return AppConfig().ai_name
        except Exception:
            return "Meowlisis"

    def llm(self):
        try:
            from func.toolbox.config import TBoxConfig
            cfg = TBoxConfig()
            if cfg.llm_type == "meowllm":
                from func.toolbox.port.meowllm import TBoxMeowLLM
                return TBoxMeowLLM(cfg)
            if cfg.llm_type == "gemini":
                from func.toolbox.port.gemini import TBoxGeminiLLM
                return TBoxGeminiLLM(cfg)
            if cfg.llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                return TBoxAliyunLLM(cfg)
            from func.toolbox.port.deepseek import TBoxDeepSeekLLM
            return TBoxDeepSeekLLM(cfg)
        except Exception as exc:
            self.log.warning("拿不到主程序文本模型：%s" % exc)
            return None

    def napcat(self):
        raise RuntimeError("真机测试宿主没有 QQ 连接")

    def tts(self):
        raise RuntimeError("真机测试宿主没有 TTS")

    def state(self):
        class _NullState:
            def enter(self, **kwargs):
                return True

            def exit(self):
                return True

            def update(self, **kwargs):
                return True

        return _NullState()


class LivePlugin:
    """面板只用到 _agent 和 play_action。"""

    def __init__(self, ctx, bridge, config):
        self.ctx = ctx
        self._bridge = bridge
        self._agent = Agent(ctx, bridge, config, on_say=self._say)
        self._agent.start()

    def _say(self, text):
        print("[她说] " + str(text), flush=True)

    def play_action(self, action):
        action = str(action or "status").strip().lower()
        if action in ("start", "开始", "开始玩", "play"):
            state = self._bridge.state()
            if not state.get("ok"):
                return "游戏没开：%s" % (state.get("reason") or "")
            if not state.get("ready"):
                return "游戏在标题画面，还没读档。"
            self._agent.start_play()
            return ""
        if action in ("stop", "停", "停止", "别玩了"):
            self._agent.stop_play()
            return ""
        return self._agent.status_text()

    def stop(self):
        try:
            self._agent.stop()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument("--bridge", default="http://127.0.0.1:8765")
    parser.add_argument("--autostart", action="store_true", help="连上读档后直接开始玩")
    parser.add_argument("--ask", default="", help="启动后立刻发一条请求，然后退出")
    parser.add_argument("--data-dir", default="",
                        help="记录数据目录；留空用系统临时目录，避免沙箱写 character/plugin_data 被拒")
    parser.add_argument("--llm", action="store_true", default=True,
                        help="让模型参与计划/日记/记忆（默认开）")
    args = parser.parse_args()

    config = {
        "persona": "Meowlisis",
        "autonomy": {"enabled": True, "llm": bool(args.llm), "pace": "relaxed",
                     "sleep_hour": 22, "energy_floor": 8, "narrate_minutes": 2},
        "plans": {"max_roots": 3, "max_leaves": 10},
        "memory": {"recall": 8},
        "habits": {"enabled": True, "affect_plan": True},
        "tips": {"enabled": True},
        "feedback": {"enabled": True},
        "user_input": {"enabled": False},
        "naming": {"ask_user": False, "fallback": "小星"},
    }

    ctx = LiveCtx(config, args.data_dir)
    bridge = Bridge(args.bridge, 8)
    info = bridge.ping()
    print("mod：%s" % info, flush=True)
    state = bridge.state()
    if not state.get("ok"):
        print("连不上游戏：%s" % (state.get("reason") or ""), flush=True)
        return 1
    print("存档：%s · 读档=%s" % (state.get("save"), state.get("ready")), flush=True)

    plugin = LivePlugin(ctx, bridge, config)
    server = DashboardServer(plugin, args.port)
    server.start()
    print("面板：http://127.0.0.1:%d/" % args.port, flush=True)

    try:
        if args.autostart and state.get("ready"):
            plugin.play_action("start")
            print("已开始玩。", flush=True)
        if args.ask:
            result = plugin._agent.handle_request(args.ask, by="测试", source="dashboard")
            print("结果：%s" % result, flush=True)
            time.sleep(2)
            return 0
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n退出。", flush=True)
    finally:
        server.stop()
        plugin.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
