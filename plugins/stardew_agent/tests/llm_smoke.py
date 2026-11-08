# -*- coding: utf-8 -*-
"""用确定性假模型验证 LLM 路径（不调用外网、不需要游戏）。

覆盖：日记 / 记忆 tips / 习惯 / 长线规划 / 当日计划 / 职业选择 的
prompt → JSON → 落盘 链路，保证模型返回时不会崩。
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from plugins.stardew_agent.brain import reflect  # noqa: E402
from plugins.stardew_agent.records import diary, habits, memtips, plans, store as store_mod  # noqa: E402


class FakeLLM:
    client = object()

    def chat(self, messages):
        text = " ".join(str((m or {}).get("content") or "") for m in (messages or [])
                        if isinstance(m, dict))
        if "你在写自己的日记" in text:
            payload = {"content": "今天清理了农场，累但踏实，明天想接着种田。",
                       "mood": "挺满足", "summary": "清理农场",
                       "tags": ["work:farming"]}
        elif "排今天" in text or "今日打算" in text:
            payload = {"reason": "先干活再散步", "plan": [
                {"title": "上午把农场弄一遍", "detail": "先收成熟的，再浇水，有空地补种",
                 "start": "06:30", "end": "10:00"},
                {"title": "下午去镇上转转", "detail": "和人聊聊天，顺便看看商店",
                 "start": "13:00", "end": "16:00"}]}
        elif "给一只猫起名字" in text or "只输出名字本身" in text:
            payload = "防风"
        elif "自然、简短的口语" in text or "问一个问题" in text:
            payload = "这只猫你想叫它什么呀？想好了告诉我。"
        elif "生活习惯" in text:
            payload = {"habits": [{"content": "早上先看天气再下地",
                                   "week_day": ["Mon", "Tue"],
                                   "time": ["06:00"], "priority": 4,
                                   "goal": "watch_tv", "reason": "7 天里 6 天都这样"}]}
        elif "记忆 tips" in text or "长期有价值" in text:
            payload = {"tips": [{"content": "Pierre 喜欢防风草，和艾米丽关系很好。",
                                  "tag": ["npc"],
                                  "attributes": {"accuracy": 3, "value": 8, "npc": "Pierre",
                                                 "friendship": 4, "relationship": "店主/熟人"}}]}
        elif "长线规划" in text:
            payload = {"reason": "按今天的进展更新", "roots": [
                {"id": "lt1", "title": "把农场经营好", "necessity": 9, "priority": 8,
                 "frequency": "daily", "status": "active", "children": [
                     {"id": "lt1-1", "title": "清理农场杂物", "necessity": 7, "priority": 7,
                      "frequency": "once", "status": "done"},
                     {"id": "lt1-2", "title": "种一片防风草", "necessity": 7, "priority": 6,
                      "frequency": "weekly", "status": "pending"}]}]}
        else:
            payload = {"content": "今天清理了农场，累但踏实，明天想接着种田。",
                       "mood": "挺满足", "summary": "清理农场",
                       "tags": ["work:farming"]}

        class Message:
            content = json.dumps(payload, ensure_ascii=False)

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        return Response()


class Ctx:
    class _Log:
        def info(self, message):
            pass

        def warning(self, message):
            print("[警告]", message, flush=True)

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="stardew_llm_smoke_")
        self.config = {}
        self.log = Ctx._Log()
        self._llm = FakeLLM()

    def data_dir(self, per_user=None):
        return self.dir

    def ai_name(self):
        return "测试角色"

    def llm(self):
        return self._llm


def main():
    ctx = Ctx()
    store = store_mod.Store(ctx, "Test_Meow")
    day = "0001_spring_03"
    state = {
        "ok": True, "save": "Test", "player": {"name": "Meow", "location": "Farm",
                                               "energy": 200, "max_energy": 270,
                                               "money": 1000, "inventory_slots": 36},
        "game": {"year": 1, "season": "spring", "day": 3, "time": 900,
                 "raining": False, "is_festival": False},
        "farm": {"crops": 10, "ready": 2, "thirsty_tiles": [[1, 2]]},
        "inventory": [], "npcs": [], "shed": {},
    }
    rows = [{"time": "08:00", "kind": "action", "content": "清理农场杂物", "goal": "clear_farm"}]

    diary_data = reflect.write_diary(ctx, state, store, day, rows, "Meow", {}, "平静")
    assert diary_data and diary_data.get("content")

    tips = reflect.write_memories(ctx, state, store, day, rows, diary_data, "Meow", {},
                                  None, "")
    assert tips, "LLM 记忆没有落盘"

    habit_rows = reflect.write_habits(ctx, store, "0001_spring_01", "0001_spring_07",
                                      "Meow", {})
    assert habit_rows, "LLM 习惯没有落盘"

    current = plans.load_long_term(store, "把农场经营好", 3)
    updated = reflect.update_long_term(ctx, state, store, current, day, diary_data, rows,
                                       "Meow", {}, 3, "")
    assert updated.get("roots"), "LLM 长线没有落盘"

    nodes, reason = reflect.make_day_plan(ctx, state, store, updated, "tips", "习惯",
                                          [], "上一本日记", rows, "Meow", {}, 6, "")
    assert nodes and all(not node.get("action") for node in nodes), "今日打算不应带动作"
    assert any("农场" in node.get("title") for node in nodes)

    question = reflect.natural_question(
        ctx, state, "name", {"subject": "猫", "fallback_text": "你想给它起什么名字？"},
        "Meow", {})
    assert question and "{" not in question, "自然提问没有走文本生成"
    name = reflect.suggest_name(ctx, state, "Meow", "Pierre 喜欢防风草", [], "今天种了防风草")
    assert name == "防风", "根据记忆起名没有走模型"

    print("LLM SMOKE OK")
    print("data:", ctx.dir)


if __name__ == "__main__":
    main()
