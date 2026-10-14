import threading
import time
from collections import OrderedDict

from func.tools.singleton_mode import singleton


@singleton
class TBSelfSentStore:
    def __init__(self, maxlen: int = 200):
        self._lock = threading.Lock()
        self._max = maxlen
        self._items = OrderedDict()

    def remember(self, message_id, text):
        mid = str(message_id or "").strip()
        if not mid:
            return
        with self._lock:
            self._items[mid] = str(text or "")
            self._items.move_to_end(mid)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def text_of(self, message_id):
        mid = str(message_id or "").strip()
        if not mid:
            return None
        with self._lock:
            return self._items.get(mid)


@singleton
class TBQuoteStore:
    TTL = 20.0

    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}

    def put(self, scope: str, key, text: str, source: str = ""):
        k = (str(scope or ""), str(key or ""))
        if not k[1] or not str(text or "").strip():
            return
        with self._lock:
            self._items[k] = (str(text).strip(), str(source or "").strip(), time.monotonic())

    def take(self, scope: str, key, current=None):
        k = (str(scope or ""), str(key or ""))
        with self._lock:
            item = self._items.pop(k, None)
        if not item:
            return None
        text, source, ts = item
        if time.monotonic() - ts > self.TTL:
            return None
        if current is not None and source:
            cur = str(current or "")
            probe = source[:12]
            if probe and probe not in cur:
                return None
        return text
