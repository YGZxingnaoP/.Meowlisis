# -*- coding: utf-8 -*-
"""长线规划树 + 当日计划树。

长线规划：最多 4 层、最多 N 个根目标（默认 3，可配置）；每个节点必须带
必要性 necessity(1~10)、优先级 priority(1~10)、频率 frequency
（once / daily / weekly / seasonal），越往下越具体。

存储按「一根目标一个文件」拆开，禁止把整棵树堆进一个 JSON：

    plans/long_term/index.json          根索引（顺序、更新时间、说明）
    plans/long_term/<root_id>.json      每根目标一棵树（最多 4 层）

当日计划一天一个文件，也是树：

    plans/day/<年_季_日>.json
    {"date": ..., "reason": ..., "nodes": [{"title": "上午", "children": [...叶子...]}]}

叶子节点才带 action（映射到可执行的 goal + params）。叶子完成后子层全部完成，
父层自动完成，一路往上推。
"""

import os
import re

from . import store as store_mod

VERSION = 2
MAX_DEPTH = 4
MAX_ROOTS_DEFAULT = 3
FREQUENCIES = ("once", "daily", "weekly", "seasonal")
STATUSES = ("pending", "active", "done", "failed", "blocked", "cancelled", "skipped")
FREQUENCY_CN = {"once": "一次", "daily": "每天", "weekly": "每周", "seasonal": "每季"}
STATUS_CN = {"pending": "待做", "active": "进行中", "done": "完成", "failed": "失败",
             "blocked": "受阻", "cancelled": "取消", "skipped": "跳过"}


def _num(value, default, low, high):
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _clean(text, limit=160):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _status(value):
    value = str(value or "").strip().lower()
    return value if value in STATUSES else "pending"


def _clock(value):
    """把 6:30 / 0630 / 06:30 统一成 06:30；无效返回空串。"""
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    elif text.isdigit():
        digits = text.zfill(4)
        hour, minute = int(digits[:2]), int(digits[2:])
    else:
        return ""
    if hour > 26 or minute > 59:
        return ""
    return "%02d:%02d" % (hour, minute)


def clock_to_minutes(text):
    value = _clock(text)
    if not value:
        return -1
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _frequency(value):
    value = str(value or "").strip().lower()
    aliases = {"每天": "daily", "每日": "daily", "daily": "daily",
               "每周": "weekly", "每周一次": "weekly", "weekly": "weekly",
               "每季": "seasonal", "每季一次": "seasonal", "seasonal": "seasonal",
               "一次": "once", "一次性": "once", "once": "once"}
    return aliases.get(value, value if value in FREQUENCIES else "once")


def normalize_node(node, depth=1, prefix="n", used=None):
    """把模型输出 / 手写 JSON 修成固定结构；超过 4 层的子树直接截断。"""
    if not isinstance(node, dict):
        return None
    title = _clean(node.get("title") or node.get("name") or node.get("content"), 80)
    if not title:
        return None
    used = used if used is not None else set()
    node_id = _clean(node.get("id"), 40)
    if not node_id or node_id in used:
        index = 1
        while "%s%d" % (prefix, index) in used:
            index += 1
        node_id = "%s%d" % (prefix, index)
    used.add(node_id)
    clean = {
        "id": node_id,
        "title": title,
        "detail": _clean(node.get("detail") or node.get("reason") or "", 240),
        "necessity": _num(node.get("necessity"), 5, 1, 10),
        "priority": _num(node.get("priority"), 5, 1, 10),
        "frequency": _frequency(node.get("frequency")),
        "status": _status(node.get("status")),
        "source": _clean(node.get("source"), 80),
        "reason": _clean(node.get("reason"), 160),
        "start": _clock(node.get("start") or node.get("start_time")),
        "end": _clock(node.get("end") or node.get("end_time")),
        "children": [],
    }
    action = node.get("action")
    if isinstance(action, str):
        action = {"goal": action}
    if isinstance(action, dict) and action.get("goal"):
        clean["action"] = {
            "goal": _clean(action.get("goal"), 40),
            "params": action.get("params") if isinstance(action.get("params"), dict) else {},
        }
    if depth < MAX_DEPTH:
        children = node.get("children") or node.get("subtasks") or []
        if isinstance(children, list):
            for index, child in enumerate(children):
                item = normalize_node(child, depth + 1, "%s-%d" % (node_id, index + 1), used)
                if item:
                    clean["children"].append(item)
    return clean


def _walk(node, callback):
    callback(node)
    for child in node.get("children") or []:
        _walk(child, callback)


def flatten(nodes):
    result = []

    def collect(node):
        result.append(node)
        for child in node.get("children") or []:
            collect(child)

    for node in nodes or []:
        collect(node)
    return result


def _leaf(node):
    return not (node.get("children") or [])


def rollup(node):
    """子层全部完成 → 父层完成；返回 (done_count, total_leaves)。"""
    children = node.get("children") or []
    if not children:
        node["progress"] = "done" if node.get("status") == "done" else "leaf"
        return (1 if node.get("status") == "done" else 0), 1
    done = total = 0
    for child in children:
        child_done, child_total = rollup(child)
        done += child_done
        total += child_total
    node["progress"] = "%d/%d" % (done, total)
    if total and done >= total:
        node["status"] = "done"
    elif any(child.get("status") == "blocked" for child in children):
        node["status"] = "blocked"
    elif node.get("status") == "done":
        # 子节点被重新打开时，已完成的父层必须退回 active
        node["status"] = "active"
    elif node.get("status") == "pending":
        node["status"] = "active"
    return done, total


def available_leaves(node):
    """按优先级展开还没完成的叶子；完成/失败/受阻的节点不再进入。"""
    if node.get("status") in ("done", "cancelled", "skipped", "failed", "blocked"):
        return []
    children = node.get("children") or []
    if not children:
        return [node]
    result = []
    for child in children:
        result.extend(available_leaves(child))
    return result


def find_node(nodes, node_id):
    for node in flatten(nodes):
        if node.get("id") == node_id:
            return node
    return None


def mark_node(nodes, node_id, status="done"):
    node = find_node(nodes, node_id)
    if node is None:
        return None
    node["status"] = _status(status)
    for root in nodes or []:
        rollup(root)
    return node


def progress_of(nodes):
    done = total = 0
    for node in nodes or []:
        if _leaf(node):
            total += 1
            if node.get("status") == "done":
                done += 1
    return done, total


def plan_complete(data):
    """整棵当日计划树是否所有叶子都完成。"""
    leaves = [node for node in flatten((data or {}).get("nodes") or []) if not node.get("children")]
    return bool(leaves) and all(node.get("status") == "done" for node in leaves)


# ===================== 长线规划 =====================

DEFAULT_BLUEPRINTS = {
    "赚钱": [
        ("把可用产出换成钱", ["收获成熟作物", "把非口粮作物送进出货箱", "鱼/矿/采集品按需出售"]),
        ("控制支出", ["列一张近期要买的东西", "只买种子、工具升级和必要补给"]),
        ("攒钱办大事", ["定一个阶段性存款目标", "达到目标后升级工具或扩建"]),
    ],
    "扩建": [
        ("准备土地", ["清理农场杂物", "规划一块整齐的田", "开垦矩形田块"]),
        ("准备种子和资金", ["确认当季种子", "留出买种子的钱", "播种并浇水"]),
        ("持续维护", ["每天浇水", "成熟就收", "收完补种"]),
    ],
    "开垦": [
        ("选址", ["看农场地形", "避开树和建筑", "选一块能连成矩形的空地"]),
        ("清理与开垦", ["清杂草石头", "锄出整块地", "播种"]),
    ],
    "清理": [
        ("清杂物", ["清杂草", "敲碎石头", "砍小树和树桩"]),
        ("整理空间", ["把没用完的东西存进箱子", "规划通道和箱子位置"]),
    ],
    "升级": [
        ("准备资源", ["攒钱", "准备木材/矿石", "确认要升级什么"]),
        ("执行升级", ["找对应工匠", "升级工具/房子/建筑"]),
    ],
    "房子": [
        ("攒钱", ["稳定出货", "少买非必需品"]),
        ("准备材料", ["木材", "石头"]),
        ("找 Robin 升级", ["去木匠店", "选升级项目"]),
    ],
    "钓鱼": [
        ("准备", ["买/修钓竿", "准备鱼饵"]),
        ("练习", ["找安全的岸边", "每天钓几竿"]),
    ],
    "矿": [
        ("准备", ["带镐和武器", "带回复食物"]),
        ("下矿", ["打怪", "敲石头找梯子", "记录深层资源"]),
    ],
    "动物": [
        ("准备", ["建鸡舍/畜棚", "买动物"]),
        ("照料", ["每天摸动物", "收蛋/奶/毛", "补干草"]),
    ],
    "社交": [
        ("认识人", ["每天和至少一个村民聊天", "记下他们的喜好"]),
        ("维护关系", ["生日送礼", "帮忙完成任务"]),
    ],
}


def _blueprint_for(text):
    for keyword, blueprint in DEFAULT_BLUEPRINTS.items():
        if keyword in text:
            return blueprint
    return [
        ("先做起来", ["今天能做的一小步", "明天接着做"]),
        ("持续维护", ["定期检查进度", "遇到问题换方法"]),
    ]


def default_root(index, title):
    blueprint = _blueprint_for(title)
    children = []
    for sub_index, (subtitle, steps) in enumerate(blueprint):
        leaves = []
        for leaf_index, step in enumerate(steps):
            leaves.append({
                "id": "lt%d-%d-%d" % (index + 1, sub_index + 1, leaf_index + 1),
                "title": step,
                "necessity": 6,
                "priority": 4,
                "frequency": "once",
                "status": "pending",
                "children": [],
            })
        children.append({
            "id": "lt%d-%d" % (index + 1, sub_index + 1),
            "title": subtitle,
            "necessity": 7,
            "priority": 5,
            "frequency": "weekly",
            "status": "pending",
            "children": leaves,
        })
    return {
        "id": "lt%d" % (index + 1),
        "title": title,
        "detail": "角色自己定下的长期方向",
        "necessity": 9,
        "priority": max(1, 8 - index),
        "frequency": "daily",
        "status": "active",
        "children": children,
    }


def load_long_term(store, config_text="", max_roots=MAX_ROOTS_DEFAULT):
    """读长线规划：index + 每根一个文件；缺失时用配置生成初始树。"""
    index = store.load_json(store.long_term_index_path(), None)
    if not isinstance(index, dict) or not isinstance(index.get("roots"), list) or not index["roots"]:
        raw = [item.strip() for item in re.split(r"[，,、;；\n]+", str(config_text or "")) if item.strip()]
        if not raw:
            raw = ["把农场经营好", "多赚点钱", "和镇上的人熟起来"]
        roots = []
        for position, title in enumerate(raw[:max(1, int(max_roots or MAX_ROOTS_DEFAULT))]):
            root = default_root(position, title)
            store.save_json(store.long_term_root_path(root["id"]), root)
            roots.append({"id": root["id"], "title": root["title"]})
        index = {
            "version": VERSION,
            "updated": store_mod.now(),
            "updated_day": "",
            "reason": "按配置生成的初始长线规划",
            "roots": roots,
        }
        store.save_json(store.long_term_index_path(), index)
    roots = []
    for entry in index.get("roots") or []:
        root = store.load_json(store.long_term_root_path(entry.get("id") or ""), None)
        if isinstance(root, dict) and root.get("title"):
            rollup(root)
            roots.append(root)
    return {
        "version": VERSION,
        "updated": index.get("updated") or 0,
        "updated_day": index.get("updated_day") or "",
        "reason": index.get("reason") or "",
        "roots": roots[:max(1, int(max_roots or MAX_ROOTS_DEFAULT))],
    }


def save_long_term(store, roots, max_roots=MAX_ROOTS_DEFAULT, reason="", day_stamp=""):
    """写回长线规划：每根一个文件 + 更新 index。"""
    cleaned = []
    used = set()
    for position, root in enumerate(list(roots or [])[:max(1, int(max_roots or MAX_ROOTS_DEFAULT))]):
        item = normalize_node(root, 1, "lt%d" % (position + 1), used)
        if not item:
            continue
        rollup(item)
        cleaned.append(item)
    entries = []
    active_roots = []
    for root in cleaned:
        store.save_json(store.long_term_root_path(root["id"]), root)
        active_roots.append(root)
        entries.append({"id": root["id"], "title": root["title"]})
        if root.get("status") == "done":
            archive_root(store, root, day_stamp)
    index = {
        "version": VERSION,
        "updated": store_mod.now(),
        "updated_day": str(day_stamp or ""),
        "reason": _clean(reason, 160),
        "roots": entries,
    }
    store.save_json(store.long_term_index_path(), index)
    return {
        "version": VERSION,
        "updated": index["updated"],
        "updated_day": index["updated_day"],
        "reason": index["reason"],
        "roots": active_roots,
    }


def long_term_text(data, max_nodes=60, max_chars=5000):
    lines = ["# 长线规划"]
    count = 0

    def render(node, depth):
        nonlocal count
        if count >= max_nodes:
            return
        count += 1
        mark = {"done": "✔", "blocked": "!", "failed": "✘", "skipped": "–"}.get(node.get("status"), "·")
        lines.append("%s%s %s（必要%s/优先%s/%s）" % (
            "  " * depth, mark, node.get("title"),
            node.get("necessity"), node.get("priority"),
            FREQUENCY_CN.get(node.get("frequency"), node.get("frequency"))))
        for child in node.get("children") or []:
            render(child, depth + 1)

    for root in (data or {}).get("roots") or []:
        render(root, 0)
    return "\n".join(lines)[:max_chars]


def next_long_term_focus(data, limit=3):
    """给当日计划挑长线分支：优先没完成的、优先级高的。"""
    picked = []
    for root in (data or {}).get("roots") or []:
        leaves = available_leaves(root)
        if not leaves:
            continue
        leaves.sort(key=lambda node: (-int(node.get("priority") or 0),
                                      -int(node.get("necessity") or 0)))
        for leaf in leaves[:2]:
            picked.append({"root": root.get("title"), "leaf": leaf.get("title"),
                           "priority": leaf.get("priority"), "necessity": leaf.get("necessity")})
        if len(picked) >= limit:
            break
    return picked[:limit]


def executable_leaves(roots, limit=16, goals=None):
    """已废弃：动作不再由计划指定。保留函数名只为兼容旧存档读取。"""
    return []


def merge_status(old_roots, new_roots):
    """按 id / title 把旧树的完成状态合并进模型新树，避免更新后进度清零。"""
    old_status = {}
    for node in flatten(old_roots or []):
        old_status[node.get("id")] = node.get("status")
        old_status["title:" + str(node.get("title"))] = node.get("status")
    for node in flatten(new_roots or []):
        status = old_status.get(node.get("id")) or old_status.get("title:" + str(node.get("title")))
        if status == "done" and node.get("status") != "done":
            node["status"] = "done"
    return new_roots


# ===================== 当日计划 =====================

def default_day(stamp_text, state=None, reason="还没定计划"):
    game = (state or {}).get("game") or {}
    return {
        "version": VERSION,
        "date": stamp_text,
        "weather": "雨天" if game.get("raining") else ("雪天" if game.get("snowing") else "晴天"),
        "mood": "",
        "reason": reason,
        "created": store_mod.now(),
        "updated": store_mod.now(),
        "nodes": [],
    }


def load_day(store, stamp_text):
    """当日计划：先看活动目录，再看归档（归档后依然可读）。"""
    data = store.load_json(store.day_plan_path(stamp_text), None)
    if not (isinstance(data, dict) and isinstance(data.get("nodes"), list)):
        data = store.load_json(store.archive_day_path(stamp_text), None)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        return None
    return data


def archive_day(store, stamp_text):
    """把某一天的计划归档：plans/day → archive/day，并记入归档索引。

    返回 True 表示归档发生；False 表示当天没有计划文件。
    """
    src = store.day_plan_path(stamp_text)
    if not os.path.isfile(src):
        return False
    data = store.load_json(src, None)
    if not isinstance(data, dict) or not data.get("nodes"):
        try:
            os.remove(src)
        except OSError:
            pass
        return False
    store.save_json(store.archive_day_path(stamp_text), data)
    done_titles = [str(node.get("title") or "") for node in flatten(data.get("nodes") or [])
                   if not node.get("children") and node.get("status") == "done"]
    _record_archive(store, {
        "kind": "day",
        "day": str(stamp_text),
        "title": "当日计划",
        "done": done_titles[:20],
        "archived": store_mod.now(),
    })
    # 归档是复制，不是删除：活动计划继续保留，方便回看/继续编辑
    return True


def _archive_data(store):
    data = store.load_json(store.archive_index_path(), None)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        data = {"version": 1, "items": []}
    return data


def _record_archive(store, item):
    data = _archive_data(store)
    key = (item.get("kind"), item.get("day"), item.get("root") or "")
    data["items"] = [old for old in data.get("items") or []
                     if (old.get("kind"), old.get("day"), old.get("root") or "") != key]
    data["items"].append(item)
    data["items"] = data["items"][-500:]
    data["updated"] = store_mod.now()
    store.save_json(store.archive_index_path(), data)


def archive_root(store, root, day_stamp=""):
    """完成的长线根目标归档：复制一份到 archive，活动树继续保留。"""
    if not isinstance(root, dict) or not root.get("id"):
        return False
    store.save_json(store.archive_long_term_path(root["id"], day_stamp), root)
    _record_archive(store, {
        "kind": "long_term",
        "root": str(root.get("id")),
        "title": str(root.get("title") or ""),
        "day": str(day_stamp or ""),
        "archived": store_mod.now(),
    })
    return True


def recent_done_text(store, limit=12):
    """最近归档的完成项，给下一次排计划看，避免原样重复。"""
    data = _archive_data(store)
    lines = []
    for item in reversed((data.get("items") or [])[-max(1, int(limit or 1)):]):
        if item.get("kind") == "day":
            done = "、".join(item.get("done") or [])
            lines.append("- %s 完成：%s" % (item.get("day"), done or "（无具体叶子）"))
        elif item.get("kind") == "long_term":
            lines.append("- 长线目标完成：%s（%s）" % (item.get("title"), item.get("day")))
    return "\n".join(lines)


def save_day(store, stamp_text, nodes, state=None, reason="", mood=""):
    data = load_day(store, stamp_text) or default_day(stamp_text, state, reason)
    used = set()
    clean = []
    for index, node in enumerate(nodes or []):
        item = normalize_node(node, 1, "d%d" % (index + 1), used)
        if item:
            clean.append(item)
    for node in clean:
        rollup(node)
    data["nodes"] = clean
    data["reason"] = _clean(reason or data.get("reason"), 200)
    data["updated"] = store_mod.now()
    if mood:
        data["mood"] = _clean(mood, 30)
    if state:
        data["weather"] = "雨天" if (state.get("game") or {}).get("raining") else "晴天"
    store.save_json(store.day_plan_path(stamp_text), data)
    return data


def reopen_skipped(nodes):
    """恢复被停止/跳过但没做的叶子：skipped → pending，done/failed 不动。"""
    changed = 0
    for node in flatten(nodes or []):
        if node.get("status") == "skipped":
            node["status"] = "pending"
            changed += 1
    for node in nodes or []:
        rollup(node)
    return changed


def next_day_leaf(data):
    leaves = []
    for node in (data or {}).get("nodes") or []:
        if node.get("status") in ("done", "cancelled", "skipped"):
            continue
        leaves.extend(available_leaves(node))
    leaves = [leaf for leaf in leaves if leaf.get("status") not in
              ("done", "cancelled", "skipped", "failed", "blocked")]
    leaves.sort(key=lambda leaf: (-int(leaf.get("priority") or 0), -int(leaf.get("necessity") or 0)))
    return leaves[0] if leaves else None


def day_text(data, max_chars=3000):
    lines = ["# 今天的打算"]
    if not data:
        return "\n".join(lines + ["（还没定）"])

    def render(node, depth):
        mark = {"done": "✔", "failed": "✘", "active": "…", "blocked": "!",
                "skipped": "–", "cancelled": "×"}.get(node.get("status"), "·")
        when = ("%s~%s " % (node.get("start"), node.get("end"))) if node.get("start") and node.get("end") else ""
        detail = ("：%s" % node.get("detail")) if node.get("detail") else ""
        lines.append("%s%s %s%s（必要%s/优先%s/%s）%s" % (
            "  " * depth, mark, when, node.get("title"),
            node.get("necessity"), node.get("priority"),
            FREQUENCY_CN.get(node.get("frequency"), node.get("frequency")), detail))
        for child in node.get("children") or []:
            render(child, depth + 1)

    for node in data.get("nodes") or []:
        render(node, 0)
    return "\n".join(lines)[:max_chars]


def day_summary(data):
    if not data:
        return "今天还没有计划"
    active = []
    for node in data.get("nodes") or []:
        if node.get("status") in ("done", "cancelled", "skipped", "failed", "blocked"):
            continue
        active.append(node.get("title"))
    if not active:
        return "今天的计划都处理完了"
    return "今天打算：" + "；".join(active[:5])


def carry_over_day(prev_day_data, new_stamp):
    """把昨天没做完的叶子转成今天的计划条目（保留来源和标签）。"""
    items = []
    if not prev_day_data:
        return items
    for leaf in flatten(prev_day_data.get("nodes") or []):
        if leaf.get("children"):
            continue
        if leaf.get("status") in ("done", "cancelled", "skipped", "failed", "blocked"):
            continue
        item = dict(leaf)
        item["id"] = ""
        item["status"] = "pending"
        item["source"] = "carry:" + str(prev_day_data.get("date") or "")
        items.append(item)
    return items
