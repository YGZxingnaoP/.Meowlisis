# -*- coding: utf-8 -*-
"""按存档隔离的文件存储层。

每个存档一个根目录（存档名_角色名）：

    character/plugin_data/stardew_agent/saves/<key>/
        journal/<年_季_日>.csv          当天日志：时间、类型、内容（短期记忆）
        memory/<年_季_日>_<序号>.json   每条长期记忆 tip 一个独立 JSON
        habits/w00012.json              每 7 天一个窗口的生活习惯
        diary/<年_季_日>.json           每天一篇日记
        plans/long_term/index.json      长线规划根索引
        plans/long_term/<root_id>.json  每个根目标一棵树（最多 4 层）
        plans/day/<年_季_日>.json        当天计划树
        todos/<年_季_日>.json           当天的待办条目
        tags/star_tags.json             标签词表（日记 / 记忆共用）
        state/profile.json              运行时状态（心情、性格、待确认问题…）

原则：一个文件只放一类东西；所有写入都原子替换。
"""

import json
import os
import re
import threading
import time

SEASON_ORDER = {"spring": 0, "summer": 1, "fall": 2, "winter": 3}
SEASON_CN = {"spring": "春", "summer": "夏", "fall": "秋", "winter": "冬"}
WEEK_CN = {"Mon": "星期一", "Tue": "星期二", "Wed": "星期三", "Thu": "星期四",
           "Fri": "星期五", "Sat": "星期六", "Sun": "星期日"}
WEEK_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SAFE_RE = re.compile(r"[^0-9A-Za-z_\-]+")
DAY_STAMP_RE = re.compile(r"^\d{4}_[a-z]+_\d{2}$")


def safe(text, limit=80):
    cleaned = SAFE_RE.sub("_", str(text or "")).strip("_")
    return cleaned[:limit]


def stamp(state):
    """把游戏日期压成 0001_spring_03。"""
    game = (state or {}).get("game") or {}
    try:
        year = int(game.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    season = safe(game.get("season") or "spring", 12).lower() or "spring"
    try:
        day = int(game.get("day") or 0)
    except (TypeError, ValueError):
        day = 0
    return "%04d_%s_%02d" % (year, season, day)


def season_of(day_stamp):
    parts = str(day_stamp or "").split("_")
    if len(parts) >= 2:
        return "%s_%s" % (parts[0], parts[1])
    return "0000_spring"


def day_of(day_stamp):
    parts = str(day_stamp or "").split("_")
    try:
        return int(parts[2])
    except (IndexError, TypeError, ValueError):
        return 0


def stamp_order(day_stamp):
    parts = str(day_stamp or "").split("_")
    try:
        return int(parts[0]) * 112 + SEASON_ORDER.get(parts[1], 0) * 28 + int(parts[2])
    except (IndexError, TypeError, ValueError):
        return 0


def stamp_from_order(order):
    order = max(1, int(order or 1))
    order0 = order - 1
    year = order0 // 112 + 1
    within = order0 % 112
    season = ["spring", "summer", "fall", "winter"][within // 28]
    day = within % 28 + 1
    return "%04d_%s_%02d" % (year, season, day)


def weekday_of(day_stamp):
    """星露谷每年固定从星期一（第 1 天）开始，7 天一轮。"""
    day = day_of(day_stamp)
    if day <= 0:
        return "Mon"
    return WEEK_ORDER[(day - 1) % 7]


def game_clock(state):
    game = (state or {}).get("game") or {}
    try:
        value = int(game.get("time") or 0)
    except (TypeError, ValueError):
        value = 0
    return "%02d:%02d" % (value // 100, value % 100)


def world_key(state):
    """存档目录名 + 角色名；不同存档 / 不同角色绝不共用文件。"""
    save = str((state or {}).get("save") or "").strip()
    if not save:
        return ""
    player = str(((state or {}).get("player") or {}).get("name") or "").strip()
    raw = ("%s_%s" % (save, player)) if player else save
    return safe(raw, 60) or "unknown"


def now():
    return int(time.time())


def _read_json(path, default):
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
            if data is None:
                return json.loads(json.dumps(default, ensure_ascii=False))
    except Exception:
        pass
    return json.loads(json.dumps(default, ensure_ascii=False))


def _write_json(path, data):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    # Windows 上固定 .tmp 会在多个线程同时写时互相占用；用进程+线程唯一的临时名。
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    for attempt in range(4):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            if attempt >= 3:
                raise
            time.sleep(0.05 * (attempt + 1))
    return path


class Store:
    """一个存档的文件仓库；所有读写都走这里，路径不会串。"""
    SUBDIRS = ("journal", "memory", "memory/digest", "habits", "diary", "plans",
               "plans/long_term", "plans/day", "todos", "tags", "state", "maps",
               "maps/diff", "archive", "archive/day", "archive/long_term")

    def __init__(self, ctx, key, label=""):
        self.ctx = ctx
        self.key = safe(key, 60) or "unknown"
        self.label = safe(label, 40)
        base = ctx.data_dir(per_user="")
        name = "%s__%s" % (self.key, self.label) if self.label else self.key
        self.root = os.path.join(base, "saves", name)
        self._lock = threading.RLock()
        for sub in self.SUBDIRS:
            os.makedirs(os.path.join(self.root, *sub.split("/")), exist_ok=True)
        try:
            from . import tags
            tags.ensure(self)
        except Exception:
            pass

    # ---- 路径 ----
    def path(self, *parts):
        return os.path.join(self.root, *[str(p) for p in parts])

    def journal_path(self, day_stamp):
        return self.path("journal", "%s.csv" % day_stamp)

    def memory_dir(self):
        return self.path("memory")

    def memory_digest_path(self, day_stamp):
        return self.path("memory", "digest", "%s.json" % safe(day_stamp, 20))

    def habit_path(self, window_key):
        return self.path("habits", "%s.json" % window_key)

    def diary_path(self, day_stamp):
        return self.path("diary", "%s.json" % day_stamp)

    def long_term_dir(self):
        return self.path("plans", "long_term")

    def long_term_index_path(self):
        return self.path("plans", "long_term", "index.json")

    def long_term_root_path(self, root_id):
        return self.path("plans", "long_term", "%s.json" % safe(root_id, 40))

    def day_plan_path(self, day_stamp):
        return self.path("plans", "day", "%s.json" % day_stamp)

    def archive_day_path(self, day_stamp):
        return self.path("archive", "day", "%s.json" % day_stamp)

    def archive_long_term_path(self, root_id, day_stamp=""):
        name = ("%s_%s" % (safe(day_stamp, 20), safe(root_id, 40))) if day_stamp else safe(root_id, 40)
        return self.path("archive", "long_term", "%s.json" % name)

    def archive_index_path(self):
        return self.path("archive", "long_term", "index.json")

    def todo_path(self, day_stamp):
        return self.path("todos", "%s.json" % day_stamp)

    def tags_path(self):
        return self.path("tags", "star_tags.json")

    def profile_path(self):
        return self.path("state", "profile.json")

    # ---- JSON ----
    def load_json(self, path, default):
        return _read_json(path, default)

    def save_json(self, path, data):
        with self._lock:
            return _write_json(path, data)

    # ---- 列表辅助 ----
    def files(self, folder, suffix=".json"):
        directory = self.path(*folder.split("/"))
        try:
            return sorted(name[:-len(suffix)] for name in os.listdir(directory)
                          if name.endswith(suffix))
        except OSError:
            return []

    def existing_days(self, folder):
        return [name for name in self.files(folder) if DAY_STAMP_RE.match(name)]

    def latest_day(self, folder):
        days = self.existing_days(folder)
        if not days:
            return ""
        return max(days, key=stamp_order)

    def prune_memory(self, keep_days=60):
        """长期记忆不按天清理，但把残缺 / 空文件清掉，避免越写越乱。"""
        directory = self.memory_dir()
        removed = 0
        try:
            for name in os.listdir(directory):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(directory, name)
                data = _read_json(path, None)
                if not isinstance(data, dict) or not str(data.get("content") or "").strip():
                    try:
                        os.remove(path)
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
        return removed


def list_saves(ctx):
    """列出所有存档目录，供前端存档选择器用。"""
    base = os.path.join(ctx.data_dir(per_user=""), "saves")
    result = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return result
    for name in names:
        root = os.path.join(base, name)
        if not os.path.isdir(root):
            continue
        all_days = set()
        for folder in ("diary", "plans/day", "todos", "journal"):
            directory = os.path.join(root, *folder.split("/"))
            try:
                for f in os.listdir(directory):
                    if f.endswith(".json") or f.endswith(".csv"):
                        all_days.add(f[:-5] if f.endswith(".json") else f[:-4])
            except OSError:
                pass
        days = sorted(all_days, key=stamp_order)
        latest = days[-1] if days else ""
        result.append({"key": name, "latest_day": latest, "days": days[-120:]})
    return result
