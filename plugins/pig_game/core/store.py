# -*- coding: utf-8 -*-
"""养猪游戏：数据落盘。

目录下有 4 个 JSON：
    players.json   {scope: {qq: Player}}
    trades.json    [Trade]
    battles.json   [Battle]
    notes.json     {scope: {qq: [待提醒文本]}}
每次变更整体落盘，单据完成即删。规模很小，够用。
"""

import json
import os

FILES = ("players", "trades", "battles", "notes")


class Store:
    def __init__(self, data_dir):
        self.dir = data_dir
        self.players = {}
        self.trades = []
        self.battles = []
        self.notes = {}
        self.load()

    # ---------- 路径与读写 ----------
    def _path(self, name):
        return os.path.join(self.dir, name + ".json")

    def _read(self, name, default):
        path = self._path(name)
        if not os.path.isfile(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, type(default)) else default
        except Exception:
            return default

    def load(self):
        self.players = self._read("players", {})
        self.trades = self._read("trades", [])
        self.battles = self._read("battles", [])
        self.notes = self._read("notes", {})

    def save(self, name):
        try:
            os.makedirs(self.dir, exist_ok=True)
            payload = getattr(self, name)
            tmp = self._path(name) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path(name))
        except Exception:
            pass

    def save_all(self):
        for name in FILES:
            self.save(name)

    # ---------- 玩家 ----------
    def get_player(self, scope, qq):
        return (self.players.get(str(scope)) or {}).get(str(qq))

    def put_player(self, scope, qq, player):
        self.players.setdefault(str(scope), {})[str(qq)] = player

    def scope_players(self, scope):
        return self.players.get(str(scope)) or {}

    def all_players(self):
        """扁平遍历：产出 (scope, qq, player)"""
        for scope, bucket in self.players.items():
            for qq, p in (bucket or {}).items():
                yield scope, qq, p

    # ---------- 提醒（被动提醒，对方下次交互时给出）----------
    def add_note(self, scope, qq, text):
        if not text:
            return
        bucket = self.notes.setdefault(str(scope), {})
        bucket.setdefault(str(qq), []).append(str(text))

    def take_notes(self, scope, qq):
        bucket = self.notes.get(str(scope)) or {}
        items = bucket.pop(str(qq), [])
        if not items:
            return []
        if not bucket:
            self.notes.pop(str(scope), None)
        return items
