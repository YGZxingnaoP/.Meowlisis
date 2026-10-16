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

    def _path(self, name):
        return os.path.join(self.dir, name + ".json")

    def _read(self, name, default):
        path = self._path(name)
        if not os.path.isfile(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default

    def load(self):
        self.players = self._read("players", {})
        self.trades = self._read("trades", [])
        self.battles = self._read("battles", [])
        self.notes = self._read("notes", {})

    def save(self, name):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(getattr(self, name), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path(name))

    def save_all(self):
        for name in FILES:
            self.save(name)

    def get_player(self, uid):
        return self.players.get(str(uid))

    def put_player(self, uid, player):
        self.players[str(uid)] = player

    def add_note(self, scope, uid, text):
        bucket = self.notes.setdefault(str(scope), {})
        bucket.setdefault(str(uid), []).append(str(text))

    def take_notes(self, scope, uid):
        bucket = self.notes.get(str(scope)) or {}
        items = bucket.pop(str(uid), [])
        if not bucket:
            self.notes.pop(str(scope), None)
        return items
