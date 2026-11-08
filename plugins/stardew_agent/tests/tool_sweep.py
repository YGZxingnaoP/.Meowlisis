# -*- coding: utf-8 -*-
"""真机全量工具扫描：除节日外，逐个调用 mod 的 MCP 工具并记录结果。

用法（游戏已启动并读档）：
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\tool_sweep.py
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\tool_sweep.py --fast

说明：
    - 每个工具用“最小可行参数”调用（鱼 1 竿、矿 1 层、小矩形），避免跑几小时；
    - 前置条件不满足（没动物/没钱/没厨房）也会调用，结果记为“预期失败”，
      用来验证工具能正确拒绝，而不是崩溃；
    - 节日工具按用户要求跳过；
    - 最后才睡觉，避免提前换天；
    - 报告写到 %TEMP%\\stardew_tool_sweep.json。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

MOD = "http://127.0.0.1:8765"
OUT = os.path.join(os.environ.get("TEMP", "."), "stardew_tool_sweep.json")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def http(path, payload=None, timeout=90):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        MOD + path, data=data, headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            return {"ok": False, "reason": "http %s" % exc.code}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def state():
    return http("/state", timeout=15)


def call(name, timeout=90, **args):
    started = time.time()
    result = http("/command", {"tool": name, "args": args}, timeout=timeout)
    return {
        "tool": name,
        "args": args,
        "ok": bool(result.get("ok")),
        "result": str(result.get("result") or result.get("reason") or "")[:300],
        "seconds": round(time.time() - started, 1),
    }


def wait_scene(seconds=12):
    """等场景切换结束，避免所有动作都报“正在切换场景”。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        agent = state()
        text = str(agent.get("text") or "")
        if "正在切换场景" not in text:
            return True
        time.sleep(0.5)
    return False


def farm_block():
    """从农场记忆图里挑一块空地/作物块，返回 (x1,y1,x2,y2)。"""
    data = http("/farmmap", timeout=20)
    blocks = data.get("blocks") or []
    picked = None
    for block in blocks:
        if int(block.get("empty_dirt") or 0) >= 4:
            picked = block
            break
    if picked is None and blocks:
        picked = blocks[0]
    if picked is None:
        return 60, 12, 63, 15
    x = int(picked.get("x") or 60)
    y = int(picked.get("y") or 12)
    return x, y, x + 3, y + 3


def summarize(agent):
    meta = (agent or {}).get("meta") or {}
    game = meta.get("game") or {}
    player = meta.get("player") or {}
    inv = meta.get("inventory") or []
    return {
        "ready": bool((agent or {}).get("ready")),
        "time": game.get("time"),
        "money": player.get("money"),
        "location": player.get("location"),
        "npcs": meta.get("npcs") or [],
        "items": {str(i.get("name")): i.get("count") for i in inv},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="跳过钓鱼/下矿这类长动作")
    args = parser.parse_args()

    agent = state()
    info = summarize(agent)
    if not info["ready"]:
        print("游戏还没读档，退出")
        return 1
    print("开始：%s · 钱 %s · 物品 %s" % (info["location"], info["money"],
                                          ",".join("%s×%s" % (k, v) for k, v in info["items"].items())))
    results = []

    def run(name, timeout=90, **kwargs):
        record = call(name, timeout=timeout, **kwargs)
        mark = "OK  " if record["ok"] else "FAIL"
        print("  %s %-18s %6.1fs %s" % (mark, name, record["seconds"], record["result"][:100]))
        results.append(record)
        return record

    # 先把可能卡住的剧情/界面清掉
    run("skip_event", 20)
    run("close_menu", 20)

    # ---- 查询类 ----
    # get_state / get_guide 是 MCP 专用入口；REST /command 只有 Tools 注册表里的工具，
    # 这里如果失败属于“REST 不支持”，不是工具坏了。
    run("get_state", 15)
    run("get_guide", 15, topic="")
    run("update_notes", 15, notes="全量扫描测试笔记")
    run("gift_info", 20, npc="Pierre")
    run("bundle_info", 20, all=False)
    run("screenshot", 60)

    # ---- 移动 ----
    run("travel_to", 180, location="Farm")
    run("skip_event", 20)
    run("move_to", 60, x=64, y=16)

    # ---- 商店先买种子（后面播种要用）----
    run("travel_to", 120, location="SeedShop")
    wait_scene()
    run("open_shop", 30)
    run("buy", 30, item="防风草种子", count=5)
    run("close_menu", 20)
    run("travel_to", 120, location="Farm")
    wait_scene()

    # ---- 农活：从农场记忆图挑一块地 ----
    x1, y1, x2, y2 = farm_block()
    print("  农场测试块：(%s,%s)-(%s,%s)" % (x1, y1, x2, y2))
    run("clear_area", 240, x1=x1, y1=y1, x2=x2, y2=y2, include_trees=False)
    run("till_area", 240, x1=x1, y1=y1, x2=x2, y2=y2)
    run("plant_seeds", 240, seed="防风草种子", x1=x1, y1=y1, x2=x2, y2=y2, max=4)
    run("water_crops", 240)
    run("harvest_crops", 240)
    run("use_tool", 90, tool="hoe", x=x1, y=y1, times=1)

    # ---- 物品 / 背包 ----
    run("eat", 30, item="韭葱")
    run("ship_items", 180, item="韭葱", count=1)
    run("tidy_backpack", 240)
    run("store_items", 120, items="树液", x=68, y=16)
    run("take_items", 120, items="树液", x=68, y=16)
    run("craft", 30, recipe="Chest", count=1)
    run("place_item", 60, item="防风草种子", x=61, y=11)

    # ---- 商店 ----
    run("open_shop", 30)
    run("buy", 30, item="防风草种子", count=1)
    run("sell", 30, item="韭葱", count=1)
    run("close_menu", 20)

    # ---- 交互 / 界面 ----
    npc = (info["npcs"] or [{}])[0].get("name") or "Pierre"
    run("interact", 180, npc=npc)
    run("dialogue", 20)
    run("menu_click", 20, index=0)
    run("close_menu", 20)
    run("choose_profession", 20, side="left")
    run("skip_event", 20)

    # ---- 冒险 ----
    if not args.fast:
        run("travel_to", 180, location="Beach")
        run("fish", 600, casts=1)
        run("travel_to", 120, location="Mountain")
        run("explore_mine", 600, levels=1)
        run("fight", 120, radius=6, min_health_percent=40)
    run("crack_geodes", 120)
    run("quest_board", 120, accept=False)

    # ---- 动物 / 社交 ----
    run("care_animals", 120)
    run("give_gift", 180, npc="Pierre", item="韭葱")
    run("donate_museum", 120)
    run("donate_bundles", 240)
    run("cook", 60)
    run("check_crab_pots", 120)
    run("buy_animal", 60, type="Chicken")
    run("build", 60, building="Coop")
    run("upgrade_house", 60)
    run("upgrade_tool", 60, tool="pickaxe")
    run("wait", 60, minutes=10)
    run("watch_tv", 240, channel="Fortune")
    run("leave_festival", 30)

    # ---- 联机（单人预期失败）----
    run("say", 20, text="测试")
    run("set_mode", 20, mode="solo")
    run("wait_chat", 20, seconds=5)
    run("follow", 20, seconds=5)
    run("propose", 20)
    run("set_name", 20, name="测试名")

    # ---- 最后睡觉（会写日记/换天）----
    run("sleep", 420)

    after = summarize(state())
    report = {"start": info, "end": after, "results": results}
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    ok = sum(1 for r in results if r["ok"])
    print("\n完成：%d/%d 成功，报告 %s" % (ok, len(results), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
