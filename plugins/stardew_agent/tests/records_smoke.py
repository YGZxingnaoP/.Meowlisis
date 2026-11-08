# -*- coding: utf-8 -*-
"""记录层离线自检：不需要游戏，验证日志/记忆/习惯/日记/长线/当日计划/待办。

全部写在系统临时目录，不碰正式存档。

用法：
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\records_smoke.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from plugins.stardew_agent.records import (diary, habits, journal, memtips,  # noqa: E402
                                           plans, profile, store as store_mod, tags, todos)


class Ctx:
    class _Log:
        def info(self, *a):
            pass

        def warning(self, *a):
            pass

    def __init__(self, base):
        self.base = base
        self.log = Ctx._Log()

    def data_dir(self, per_user=None):
        os.makedirs(self.base, exist_ok=True)
        return self.base


def check(name, condition, detail=""):
    print(("  OK   " if condition else "  FAIL ") + name + ((" · " + detail) if detail else ""))
    return bool(condition)


def main():
    base = tempfile.mkdtemp(prefix="stardew_records_")
    ctx = Ctx(base)
    store = store_mod.Store(ctx, "Test_Meow")
    day = "0001_spring_03"

    print("存档目录：%s" % store.root)
    ok = True

    # 日志 CSV
    journal.append(store, day, "action", "清了一块地", goal="clear_farm",
                   clock="09:10")
    journal.append(store, day, "dialogue", "和 Pierre 聊了种子", clock="10:20")
    rows = journal.read_day(store, day)
    ok &= check("日志 CSV 写入/读取", len(rows) == 2 and rows[0]["time"] == "09:10")

    # 记忆：一条一个文件 + 流水账过滤
    added = memtips.add_day(store, day, [
        {"content": "Pierre 是镇上杂货店老板，喜欢防风草。", "tag": ["npc"],
         "attributes": {"accuracy": 3, "value": 8, "npc": "Pierre",
                        "friendship": 4, "relationship": "店主"}},
        {"content": "今天种了 10 颗防风草。", "tag": ["work"],
         "attributes": {"accuracy": 3, "value": 8}},
    ])
    files = [n for n in os.listdir(store.memory_dir()) if n.endswith(".json")]
    ok &= check("记忆一条一个 JSON", len(files) == 1, "文件数=%d" % len(files))
    ok &= check("记忆过滤流水账", len(added) == 1)
    recalled = memtips.recall(store, limit=5, current_stamp=day)
    ok &= check("记忆召回", len(recalled) == 1 and "Pierre" in recalled[0]["content"])
    ok &= check("记忆渲染", "Pierre" in memtips.render(recalled))

    # 习惯窗口
    habits.save_summary(store, day, [
        {"content": "早上会先看电视", "week_day": ["Mon"], "time": ["06:00"],
         "priority": 4, "goal": "watch_tv", "reason": "3 天里 2 天如此"},
    ])
    window = habits.latest(store)
    ok &= check("习惯窗口", len(window.get("habits") or []) == 1)

    # 日记
    data = diary.write(store, day, "今天清了一块地，Pierre 人不错。", mood="还行",
                       tags=["npc:Pierre"], summary="清地")
    ok &= check("日记写入", bool(data and diary.read(store, day)))
    ok &= check("日记检索", bool(diary.search(store, query="Pierre")))

    # 长线：每根一个文件 + 4 层
    roots = [{
        "id": "lt1", "title": "把农场经营好", "necessity": 9, "priority": 8,
        "frequency": "daily", "status": "active",
        "children": [{
            "id": "lt1-1", "title": "种一片田", "necessity": 8, "priority": 8,
            "frequency": "weekly", "status": "pending",
            "children": [{
                "id": "lt1-1-1", "title": "锄地", "necessity": 7, "priority": 7,
                "frequency": "once", "status": "pending",
                "children": [{
                    "id": "lt1-1-1-1", "title": "锄 8x6", "necessity": 6,
                    "priority": 6, "frequency": "once", "status": "pending",
                }],
            }],
        }],
    }]
    roots[0]["children"][0]["children"][0]["children"][0]["status"] = "done"
    plans.rollup(roots[0])
    ok &= check("长线子完成父完成", roots[0]["status"] == "done")
    roots[0]["children"][0]["children"][0]["children"][0]["status"] = "pending"
    plans.rollup(roots[0])
    saved = plans.save_long_term(store, roots, max_roots=3, reason="测试", day_stamp=day)
    loaded = plans.load_long_term(store, "把农场经营好", 3)
    leaf_count = len(plans.flatten(loaded["roots"]))
    ok &= check("长线拆根存储", os.path.isfile(store.long_term_root_path("lt1"))
                and os.path.isfile(store.long_term_index_path()))
    ok &= check("长线 4 层保留", leaf_count == 4, "节点数=%d" % leaf_count)
    ok &= check("长线未完成不归档", loaded["roots"][0]["status"] != "done")

    done_root = {
        "id": "lt2", "title": "已完成目标", "necessity": 8, "priority": 7,
        "frequency": "once", "status": "active",
        "children": [{"id": "lt2-1", "title": "已完成叶子", "necessity": 6,
                      "priority": 6, "frequency": "once", "status": "done"}],
    }
    plans.save_long_term(store, [done_root], max_roots=3, reason="归档测试", day_stamp=day)
    ok &= check("长线完成归档（保留活动树）",
                os.path.isfile(store.archive_long_term_path("lt2", day))
                and os.path.isfile(store.long_term_root_path("lt2")))

    # 当日计划 + 回滚
    nodes = [{
        "title": "上午", "necessity": 8, "priority": 8, "frequency": "daily",
        "children": [{
            "title": "浇水", "necessity": 7, "priority": 7, "frequency": "daily",
            "action": {"goal": "water_all", "params": {}},
        }],
    }]
    plan = plans.save_day(store, day, nodes, reason="测试")
    leaf = plans.available_leaves(plan["nodes"][0])[0]
    plans.mark_node(plan["nodes"], leaf["id"], "done")
    plan = plans.save_day(store, day, plan["nodes"], reason="测试")
    ok &= check("当日计划回滚", plan["nodes"][0]["status"] == "done")
    ok &= check("当日计划完成判定", plans.plan_complete(plan))
    archived = plans.archive_day(store, day)
    ok &= check("当日计划归档", archived and os.path.isfile(store.archive_day_path(day))
                and plans.load_day(store, day) is not None)
    ok &= check("完成历史可读", "浇水" in plans.recent_done_text(store))

    # 失败叶子不能原地反复重选
    fail_plan = plans.save_day(store, day, [{
        "title": "下午", "children": [{"title": "失败动作",
                                       "action": {"goal": "water_all", "params": {}}}],
    }], reason="失败测试")
    fail_leaf = plans.available_leaves(fail_plan["nodes"][0])[0]
    plans.mark_node(fail_plan["nodes"], fail_leaf["id"], "failed")
    fail_plan = plans.save_day(store, day, fail_plan["nodes"], reason="失败测试")
    ok &= check("失败叶子不再重选",
                not plans.available_leaves(fail_plan["nodes"][0]))

    # 待办
    item = todos.add(store, day, {"content": "去镇上买种子", "priority": 8,
                                  "action": {"goal": "buy_seeds", "params": {}}})
    todos.update_status(store, day, item["id"], "done")
    moved = todos.carry_over(store, day, "0001_spring_04")
    ok &= check("待办完成/结转", len(moved) == 0)

    # profile / tags
    prof = profile.Profile(store)
    prof.set_thought("今天还行")
    ok &= check("profile 写入", profile.Profile(store).data.get("thought") == "今天还行")
    tag_data = tags.ensure(store)
    ok &= check("标签表", "npc" in (tag_data.get("categories") or {}))

    print("\n结果：%s" % ("全部通过" if ok else "有失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
