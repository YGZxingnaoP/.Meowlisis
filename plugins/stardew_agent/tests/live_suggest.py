# -*- coding: utf-8 -*-
"""真机：直接调用 stardew_suggest 工具，看角色怎么判断、待办怎么写。"""

import json
import os
import sys
import time

ROOT = r"D:\.Meowlisis"
sys.path.insert(0, ROOT)
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from plugins.stardew_agent.plugin import PLUGIN, StardewSuggestTool
from plugins.stardew_agent.tests.live_host import LiveCtx
from plugins.stardew_agent.records import todos


class ToolCtx:
    def __init__(self, history):
        self.history = history

    def request(self):
        return {"short_memory": self.history, "text": self.history[-1]["content"] if self.history else ""}


def main():
    config = {
        "persona": "Meowlisis",
        "autonomy": {"enabled": True, "llm": True, "narrate_minutes": 2,
                     "llm_timeout": 180, "long_term": "把农场经营好、多赚点钱、和镇上的人熟起来"},
        "plans": {"max_roots": 3, "max_leaves": 6},
        "memory": {"recall": 8},
        "habits": {"enabled": True, "affect_plan": True},
        "tips": {"enabled": True},
        "feedback": {"enabled": False},
        "user_input": {"enabled": False},
        "naming": {"ask_user": False},
        "dashboard": {"enabled": False},
    }
    ctx = LiveCtx(config, os.path.join(ROOT, "character", "plugin_data", "stardew_agent"))
    PLUGIN.setup(ctx)
    try:
        print("开始玩：", PLUGIN.play_action("start") or "(ok)", flush=True)
        time.sleep(2)
        tool = StardewSuggestTool()

        first = tool.handle({"request": "去把地浇了"}, ToolCtx([]))
        print("\n[第一句 用户] 去把地浇了")
        print("[角色回复]", first, flush=True)

        history = [
            {"role": "user", "content": "去把地浇了"},
            {"role": "assistant", "content": first},
        ]
        second = tool.handle({"request": "立刻去做"}, ToolCtx(history))
        print("\n[第二句 用户] 立刻去做")
        print("[角色回复]", second, flush=True)

        agent = PLUGIN._agent
        print("\n[存档]", agent.world_key, "日期", agent.day_stamp)
        data = todos.load_day(agent.store, agent.day_stamp)
        print("[待办]")
        for item in data.get("items") or []:
            print(json.dumps({
                "content": item.get("content"),
                "status": item.get("status"),
                "necessity": item.get("necessity"),
                "priority": item.get("priority"),
                "by": item.get("by"),
            }, ensure_ascii=False))
        print("\n[inbox]")
        for item in agent.inbox:
            print(item.get("by"), item.get("mode"), item.get("text"))
        print("\n[最近日志]")
        for row in agent._recent_journal(12):
            print(row.get("time"), row.get("kind"), str(row.get("content"))[:160])
    finally:
        try:
            PLUGIN.play_action("stop")
        except Exception:
            pass
        PLUGIN.teardown()


if __name__ == "__main__":
    main()
