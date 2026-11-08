# -*- coding: utf-8 -*-
"""短时真机演示：启动 Agent 后真的玩，前台打印主动说话/分享/交流结果。

不需要 TTS/QQ；这是给“我想看到角色正常玩”的最小验证。
"""

import os
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
from plugins.stardew_agent.records import plans, store as store_mod  # noqa: E402
from plugins.stardew_agent.runner.agent import Agent  # noqa: E402


class Ctx:
    class _Log:
        def info(self, message):
            print("[插件]", message, flush=True)

        def warning(self, message):
            print("[警告]", message, flush=True)

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="stardew_demo_")
        self.config = {}
        self.log = Ctx._Log()

    def data_dir(self, per_user=None):
        return self.dir

    def ai_name(self):
        return "测试角色"

    def llm(self):
        return None


def main():
    bridge = Bridge("http://127.0.0.1:8765", 5)
    state = bridge.state()
    if not state.get("ok"):
        print("游戏没读档：", state.get("reason"), flush=True)
        return 1

    def say(text):
        print("\n[角色主动说话] %s" % text, flush=True)

    def share(text, image=""):
        print("\n[角色主动分享] %s%s" % (text, " [图]" if image else ""), flush=True)

    config = {
        "persona": "测试角色",
        "autonomy": {"enabled": True, "llm": False, "sleep_hour": 22,
                     "energy_floor": 8, "narrate_minutes": 0,
                     "long_term": "把农场经营好、多赚点钱、和镇上的人熟起来"},
        "plans": {"max_roots": 3, "max_leaves": 8},
        "feedback": {"enabled": True, "share_images": False},
        "naming": {"ask_user": True, "timeout_seconds": 60},
        "user_input": {"enabled": True, "timeout_seconds": 60},
        "traits": {"diligence": 0.6, "sociability": 0.5,
                   "curiosity": 0.6, "thrift": 0.5},
    }
    agent = Agent(Ctx(), bridge, config, on_say=say, on_share=share)
    agent.state = state
    agent._bind_world(state)
    agent.playing = True
    agent.pending_name = "黑老大"
    agent.day_stamp = store_mod.stamp(state)
    agent._start_day(state)
    agent.start()
    agent.start_play()

    print("\n[计划]", plans.day_text(plans.load_day(agent.store, agent.day_stamp))[:1200], flush=True)

    def status(tag):
        s = bridge.state()
        print("\n[%s] %s %s | 体力 %s | %s" % (
            tag, (s.get("game") or {}).get("time_string"),
            (s.get("player") or {}).get("location"),
            (s.get("player") or {}).get("energy"),
            (agent.current or {}).get("title") or "闲着"), flush=True)

    status("启动")
    for text, wait in [
        ("先去农场清理一下树和草", 25),
        ("把背包里的东西送进出货箱", 25),
        ("去镇上买点种子", 25),
        ("回家睡觉", 25),
    ]:
        print("\n[你] " + text, flush=True)
        result = agent.handle_request(text, by="主人", source="console")
        print("[角色回复] %s（mode=%s goal=%s）" % (
            result.get("reply"), result.get("mode"), result.get("goal")), flush=True)
        end = time.time() + wait
        while time.time() < end:
            time.sleep(2)
        status("进行中")

    agent.stop()
    print("\n[日志]\n" + "\n".join(
        "%s %s %s" % (row.get("time"), row.get("kind"), row.get("content"))
        for row in __import__("plugins.stardew_agent.records.journal",
                              fromlist=["read_day"]).read_day(agent.store, agent.day_stamp)[-30:]),
        flush=True)
    print("\n数据目录:", agent.store.root, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
