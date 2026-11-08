# -*- coding: utf-8 -*-
"""离线冒烟：不需要游戏，验证记录层 / 需求层 / tool-calling 决策循环。

用法：
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\smoke.py
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from plugins.stardew_agent.brain import needs  # noqa: E402
from plugins.stardew_agent.records import plans  # noqa: E402
from plugins.stardew_agent.runner.tool_agent import Agent  # noqa: E402

FAILED = []


def check(name, condition, detail=""):
    print(("  OK   " if condition else "  FAIL ") + name + ((" · " + detail) if detail else ""))
    if not condition:
        FAILED.append(name)


def sample_state(day=3, festival=False):
    return {
        "ok": True,
        "save": "Smoke_1",
        "meta": {},
        "text": "## 基本状态\n时间：第 1 年 春 3 日 10:00\n## 当前界面\n无\n",
        "game": {"year": 1, "season": "spring", "day": day, "time": 1000,
                 "raining": False, "festival": festival,
                 "day_of_week": "Mon"},
        "player": {"name": "Meow", "location": "Farm", "tile_x": 10, "tile_y": 8,
                   "energy": 200, "max_energy": 270, "money": 1200,
                   "inventory_slots": 36, "used_slots": 4, "has_rod": True,
                   "skills": {"farming": 1}, "professions": []},
        "inventory": [
            {"slot": 0, "name": "锄头", "id": "Hoe", "count": 1, "is_tool": True, "kind": "Hoe"},
            {"slot": 1, "name": "喷壶", "id": "WateringCan", "count": 1, "is_tool": True,
             "kind": "WateringCan"},
            {"slot": 2, "name": "防风草种子", "id": "472", "count": 12, "category": -74},
            {"slot": 3, "name": "土豆", "id": "194", "count": 5, "category": -75, "price": 80},
        ],
        "farm": {"crops": 6, "ready": 2, "thirsty": 4, "debris": 9, "trees": 3, "grass": 5,
                 "animals": 0, "buildings": 1, "hay": 0},
        "menu": {},
        "npcs": [],
        "pets": [],
    }


class _Log:
    def info(self, message, *args):
        pass

    def warning(self, message, *args):
        print("  [警告]", message % args if args else message)

    def exception(self, message, *args):
        print("  [异常]", message % args if args else message)


class _Ctx:
    def __init__(self, llm):
        self.dir = os.path.join(os.environ.get("TEMP", "."), "stardew_smoke")
        os.makedirs(self.dir, exist_ok=True)
        self.log = _Log()
        self.config = {}
        self._llm = llm

    def data_dir(self, per_user=None):
        return self.dir

    def ai_name(self):
        return "测试角色"

    def llm(self):
        return self._llm


class FakeMcp:
    def tools(self, refresh=False):
        return [
            {"name": "move_to", "description": "走到某一格",
             "inputSchema": {"type": "object", "properties": {
                 "x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}},
            {"name": "water_crops", "description": "浇水",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "sleep", "description": "睡觉",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "use_tool", "description": "用工具（参数里也有 tool）",
             "inputSchema": {"type": "object", "properties": {
                 "tool": {"type": "string"}, "x": {"type": "integer"},
                 "y": {"type": "integer"}}, "required": ["tool", "x", "y"]}},
            {"name": "say", "description": "联机说话（应被过滤）",
             "inputSchema": {"type": "object", "properties": {}}},
        ]

    def initialize(self):
        return {"instructions": "## 规则\n工具玩星露谷。"}

    def call(self, name, args=None, timeout=None):
        return "攻略内容"


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.slept = False

    def state(self):
        state = sample_state()
        if self.slept:
            state["game"]["day"] = 4
        return state

    def call(self, tool, timeout=None, **kwargs):
        return self.call_with(tool, kwargs, timeout=timeout)

    def call_with(self, tool, args=None, timeout=None):
        self.calls.append((tool, dict(args or {})))
        if tool == "sleep":
            self.slept = True
        return {"ok": True, "result": "%s 成功" % tool}

    def cancel(self):
        return {"ok": True}

    def screenshot(self):
        return {"ok": True, "path": "shot.png"}

    def farmmap(self):
        return {"ok": False}


class FakeMessage:
    def __init__(self, tool_calls=None, content=""):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, name, arguments):
        self.id = "call_1"
        self.function = FakeFunction(name, arguments)


class FakeLLM:
    client = object()

    def __init__(self):
        self.index = 0

    def chat(self, messages, tools=None, tool_choice=None):
        self.tools = tools
        self.choice = tool_choice
        if tools is None:
            text = " ".join(str((m or {}).get("content") or "") for m in (messages or []))
            if "写今天的日记" in text:
                payload = json.dumps({"content": "今天把农场收拾了一遍，挺踏实。",
                                      "mood": "踏实", "summary": "收拾农场",
                                      "tags": ["work:farming"]}, ensure_ascii=False)
            else:
                payload = "今天感觉不错。"
            return FakeResponse(FakeMessage(content=payload))
        if self.index == 0:
            self.index += 1
            return FakeResponse(FakeMessage(
                [FakeToolCall("move_to", '{"x": 12, "y": 9}')]))
        return FakeResponse(FakeMessage([FakeToolCall("sleep", "{}")]))


def main():
    print("== 记录层 ==")
    result = subprocess.run(
        [sys.executable, "-B", os.path.join(ROOT, "plugins", "stardew_agent",
                                            "tests", "records_smoke.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = result.returncode == 0
    check("records_smoke 全部通过", ok)
    if not ok:
        print(result.stdout[-2000:])
        print(result.stderr[-1000:])

    print("== 需求层 ==")
    state = sample_state()
    farm = needs.crop_summary(state)
    check("农场摘要", farm["crops"] == 6 and farm["ready"] == 2 and farm["thirsty"] == 4)
    check("种子识别", needs.seed_count(state) == 12)
    check("可出货识别", needs.shippable_count(state) == 5)
    check("工具识别", needs.has_hoe(state) and needs.has_watering_can(state))
    check("体力体感", "体力" in needs.fatigue_text(state) or "累" in needs.fatigue_text(state))
    assessed = needs.assess(state, {"diligence": 0.8})
    check("需求评分", assessed.get("farm", {}).get("value", 0) > 0.5)

    print("== planner 已删除 ==")
    try:
        import plugins.stardew_agent.brain.planner  # noqa: F401
        deleted = False
    except ImportError:
        deleted = True
    check("brain/planner.py 不存在", deleted)
    try:
        import plugins.stardew_agent.runner.agent as runner_agent
        check("runner.agent 指向 tool_agent", runner_agent.Agent is Agent)
    except Exception as exc:
        check("runner.agent 指向 tool_agent", False, str(exc))

    print("== tool-calling 循环 ==")
    llm = FakeLLM()
    ctx = _Ctx(llm)
    bridge = FakeBridge()
    agent = Agent(ctx, bridge, {"persona": "测试", "autonomy": {"llm": True},
                                "user_input": {"enabled": False},
                                "naming": {"ask_user": False}})
    agent.mcp = FakeMcp()
    agent.state = state
    agent.state_text = state["text"]
    agent.day_stamp = "0001_spring_03"
    agent._bind_world(state)
    agent.playing = True
    agent._ensure_tools()
    names = [item["function"]["name"] for item in agent._tools()]
    check("工具 schema 来自模组", "move_to" in names and "sleep" in names)
    check("联机工具被过滤", "say" not in names)
    check("模型看到完整 state", state["text"] in agent._user_prompt(state))
    check("工具不是固定序列", "steps_for" not in agent.__dict__)
    agent._step(state)
    check("模型选的工具被执行", bridge.calls and bridge.calls[0][0] == "move_to",
          str(bridge.calls))
    check("参数原样传给游戏",
          bridge.calls and bridge.calls[0][1] == {"x": 12, "y": 9})
    check("工具名进入日志", agent.last_action and agent.last_action["name"] == "move_to")
    reg = bridge.call_with("use_tool", {"tool": "axe", "x": 1, "y": 2})
    check("参数名撞形参也能执行",
          reg.get("ok") and bridge.calls[-1] == ("use_tool", {"tool": "axe", "x": 1, "y": 2}))

    agent.last_action = None
    agent.state = dict(state, game=dict(state["game"], day=4))
    agent._step(agent.state)
    check("睡觉工具交给游戏执行", any(name == "sleep" for name, _ in bridge.calls))

    print("\n结果：%s" % ("全部通过" if not FAILED else
                         "失败 %d 项：%s" % (len(FAILED), "、".join(FAILED))))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
