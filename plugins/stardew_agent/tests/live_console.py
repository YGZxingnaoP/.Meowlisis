# -*- coding: utf-8 -*-
"""前台模拟启动：真的进游戏玩，但 QQ / TTS 不真发，只打印在控制台。

用法：
    # 游戏已经开着并读档
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_console.py

    # 脚本帮你启动 SMAPI（默认路径，可用 --game 覆盖）
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_console.py --launch --load

    # 指定存档数据目录（默认系统临时目录，不污染正式数据）
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_console.py --data D:\\some\\dir

进入后：
    直接输入话 = 和她交流（会走 QQ 建议判断、命名回复、待办/计划）
    /状态 /计划 /长线 /待办 /日记 /日志 /记忆 /习惯 /停止 /退出

设计原则：
- on_say / on_share 只打印，不调用 napcat、不调用 TTS；
- 主动说话、主动分享、回答用户都会在前台显示；
- 命名字段会暂停操作等回复，超时由角色按记忆自己决定。
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from plugins.stardew_agent.core.bridge import Bridge  # noqa: E402
from plugins.stardew_agent.records import diary, habits, journal, memtips, plans, todos  # noqa: E402
from plugins.stardew_agent.records import store as store_mod  # noqa: E402
from plugins.stardew_agent.runner.agent import Agent  # noqa: E402


class Ctx:
    class _Log:
        def info(self, message):
            print("[插件]", message, flush=True)

        def warning(self, message):
            print("[警告]", message, flush=True)

        def exception(self, message):
            print("[异常]", message, flush=True)

    def __init__(self, data_dir):
        self._data_dir = data_dir
        self.config = {}
        self.log = Ctx._Log()

    def data_dir(self, per_user=None):
        os.makedirs(self._data_dir, exist_ok=True)
        return self._data_dir

    def ai_name(self):
        return "测试角色"

    def llm(self):
        return None


def wait_bridge(bridge, seconds=90):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            info = bridge.ping()
            if info.get("ok"):
                return info
        except Exception:
            pass
        time.sleep(2)
    return {}


def maybe_launch(args):
    if not args.launch:
        return
    game = args.game or os.environ.get("STARDEW_GAME") or \
        r"D:\.MYGames\StardewValley\X0015_v1.6.15.0\X0015\game\Stardew Valley"
    exe = os.path.join(game, "StardewModdingAPI.exe")
    if not os.path.isfile(exe):
        print("[启动] 找不到：", exe, flush=True)
        return
    print("[启动] 启动 SMAPI：", exe, flush=True)
    subprocess.Popen([exe], cwd=game)
    time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--data", default="")
    parser.add_argument("--persona", default="测试角色")
    parser.add_argument("--launch", action="store_true", help="自动启动 SMAPI")
    parser.add_argument("--load", action="store_true", help="自动 load_save")
    parser.add_argument("--game", default="", help="游戏目录")
    parser.add_argument("--cat-name", default="黑老大", help="起名菜单出现时使用的名字")
    args = parser.parse_args()

    maybe_launch(args)
    bridge = Bridge(args.url, 5)
    info = wait_bridge(bridge)
    if not info:
        print("桥接没起来：先启动游戏，或加 --launch", flush=True)
        return 1
    print("[桥接]", info, flush=True)
    if args.load:
        try:
            bridge.command("load_save")
        except Exception as exc:
            print("[读档]", exc, flush=True)

    data = args.data or tempfile.mkdtemp(prefix="stardew_live_")
    config = {
        "persona": args.persona,
        "autonomy": {"enabled": True, "llm": False, "sleep_hour": 22,
                     "energy_floor": 8, "narrate_minutes": 1,
                     "long_term": "把农场经营好、多赚点钱、和镇上的人熟起来"},
        "plans": {"max_roots": 3, "max_leaves": 8},
        "feedback": {"enabled": True, "share_images": False},
        "naming": {"ask_user": True, "timeout_seconds": 60},
        "user_input": {"enabled": True, "timeout_seconds": 60},
        "traits": {"diligence": 0.6, "sociability": 0.5,
                   "curiosity": 0.6, "thrift": 0.5},
    }

    def on_say(text):
        print("\n[角色主动说话] %s" % text, flush=True)

    def on_share(text, image=""):
        print("\n[角色主动分享] %s%s" % (text, " [图: %s]" % image if image else ""), flush=True)

    agent = Agent(Ctx(data), bridge, config, on_say=on_say, on_share=on_share)
    state = bridge.state()
    if not state.get("ok"):
        print("读不到游戏状态：", state.get("reason"), flush=True)
        return 1
    agent.state = state
    agent._bind_world(state)
    agent.playing = True
    agent.pending_name = str(args.cat_name or "").strip()
    agent.day_stamp = store_mod.stamp(state)
    agent._start_day(state)
    agent.start()
    agent.start_play()
    print("\n已进入游戏。直接输入话和她交流；输入 /帮助 看命令。\n", flush=True)

    def show(text):
        print("\n" + str(text) + "\n", flush=True)

    try:
        while True:
            try:
                text = input("你> ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text in ("/退出", "/quit", "/exit"):
                break
            if text in ("/帮助", "/help"):
                show("直接输入 = 交流；/状态 /计划 /长线 /待办 /日记 /日志 /记忆 /习惯 /停止 /退出")
                continue
            if text == "/状态":
                show(agent.status_text())
                continue
            if text == "/计划":
                show(agent._day_plan_text())
                continue
            if text == "/长线":
                show(plans.long_term_text(plans.load_long_term(
                    agent.store, agent.long_term_config, agent.max_roots)))
                continue
            if text == "/待办":
                show(todos.summary(agent.store, agent.day_stamp))
                continue
            if text == "/日记":
                day, data_item = diary.latest(agent.store)
                show(diary.render(data_item) if data_item else "还没有日记")
                continue
            if text == "/日志":
                show(journal.render(journal.read_day(agent.store, agent.day_stamp), max_rows=80))
                continue
            if text == "/记忆":
                show(memtips.render_store(agent.store, limit=20, current_stamp=agent.day_stamp))
                continue
            if text == "/习惯":
                show(habits.render(agent.store))
                continue
            if text == "/停止":
                agent.stop_play()
                print("已停止自主游玩。", flush=True)
                continue
            result = agent.handle_request(text, by="主人", source="console")
            print("\n[角色回复] %s" % (result.get("reply") or ""), flush=True)
            print("[判断] mode=%s reason=%s" % (
                result.get("mode"), result.get("reason")), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            agent.stop()
        except Exception:
            pass
        print("\n已退出。数据目录：", data, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
