import collections
import datetime
import io
import json
import os
import threading

from PIL import Image


class CWJournal:
    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()
        self._ring = collections.deque(maxlen=500)
        self._listeners = []
        self._seq = 0
        self.session_id = ""
        config.ensure_dirs()

    def new_session(self):
        with self._lock:
            self.session_id = "s_" + datetime.datetime.now().strftime("%m%d%H%M%S")
            self._seq = 0
            self._ring.clear()
            return self.session_id

    def _now(self):
        return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")

    def record(self, kind, **fields):
        with self._lock:
            self._seq += 1
            entry = {"ts": self._now(), "session": self.session_id or "-", "seq": self._seq, "kind": kind}
            entry.update(fields)
            self._ring.append(entry)
            try:
                with open(self.config.ops_log_path(), "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(entry)
            except Exception:
                pass
        return entry

    def add_listener(self, listener):
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener):
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def tail(self, limit=200):
        with self._lock:
            items = list(self._ring)
        return items[-int(limit):]

    def save_thumb(self, png_bytes, tag="op"):
        if not self.config.thumb_enabled or not png_bytes:
            return ""
        try:
            image = Image.open(io.BytesIO(png_bytes))
            image.load()
        except Exception:
            return ""
        try:
            longest = max(image.size) or 1
            if longest > self.config.thumb_long_edge:
                ratio = self.config.thumb_long_edge / float(longest)
                image = image.resize((max(1, int(image.width * ratio)),
                                      max(1, int(image.height * ratio))), Image.LANCZOS)
            name = "%s_%s_%03d.jpg" % (self.session_id or "s", tag, self._seq)
            path = os.path.join(self.config.thumb_dir, name)
            image.convert("RGB").save(path, format="JPEG", quality=self.config.thumb_quality)
            return "logs/catpaws_thumbs/" + name
        except Exception:
            return ""
