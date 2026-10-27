import collections
import threading
import time

from cw.protocol import CWErrorCode, CWProtocolError, point_steps, describe


class CWGuardError(CWProtocolError):
    def __init__(self, message, code=CWErrorCode.GUARD):
        super().__init__(code, message)


class CWGuard:
    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()
        self._marks = collections.deque()
        self._session_steps = 0
        self._session_started = 0.0
        self._sensitive_hits = collections.deque()

    def begin_session(self):
        with self._lock:
            self._session_steps = 0
            self._session_started = time.time()
            self._marks.clear()
            self._sensitive_hits.clear()

    def session_steps(self):
        with self._lock:
            return self._session_steps

    def check_session_window(self):
        with self._lock:
            if not self._session_started:
                return True
            elapsed = time.time() - self._session_started
        limit = int(self.config.session_timeout_sec or 0)
        if limit > 0 and elapsed > limit:
            raise CWGuardError("链路超时（%d 秒）" % limit)
        return True

    def check_batch(self, steps):
        with self._lock:
            total = self._session_steps + len(steps)
        limit = int(self.config.max_steps_per_session or 0)
        if limit > 0 and total > limit:
            raise CWGuardError("超出单链路步数上限 %d" % limit)
        if len(steps) > 1 and len(steps) > self.config.sequence_steps:
            raise CWGuardError("连续操作最多 %d 步" % self.config.sequence_steps)
        return True

    def check_reflect_safe(self, phase, steps, texts=None):
        """反思阶段禁止付款/隐私一类的操作"""
        if phase != "recording":
            return True
        body = " ".join(describe(step) for step in (steps or []))
        body += " " + " ".join(str(item) for item in (texts or []))
        for word in self.config.reflect_block_words or []:
            if word and word in body:
                raise CWGuardError("反思阶段禁止涉及「%s」的操作" % word)
        return True

    def check_rate(self, count=1):
        limit = max(1.0, self.config.max_actions_per_second)
        now = time.time()
        with self._lock:
            while self._marks and now - self._marks[0] > 1.0:
                self._marks.popleft()
            if len(self._marks) + 1 > limit:
                raise CWGuardError("操作过快（上限 %.0f 次/秒）" % limit)
            self._marks.append(now)
        return True

    def commit(self, count):
        with self._lock:
            self._session_steps += count

    def check_bounds(self, screen, steps):
        screen.check_portrait()
        for point in point_steps(steps):
            screen.check_point(point[0], point[1])
        return True

    def check_app(self, bundle_id):
        allow = self.config.app_allowlist
        deny = self.config.app_denylist
        if deny and bundle_id in deny:
            raise CWGuardError("应用 %s 在黑名单中" % bundle_id)
        if allow and bundle_id not in allow:
            raise CWGuardError("应用 %s 不在白名单中" % bundle_id)
        return True

    def check_app_steps(self, steps):
        for step in steps:
            if step.get("action") in ("launch_app", "activate_app"):
                self.check_app(step.get("bundle_id", ""))
        return True

    def find_sensitive(self, texts):
        for text in texts or []:
            body = str(text)
            for word in self.config.sensitive_words:
                if word and word in body:
                    return word
        return ""

    def note_sensitive(self, word):
        if not word:
            return
        with self._lock:
            self._sensitive_hits.append((time.time(), word))

    def take_sensitive(self):
        with self._lock:
            if not self._sensitive_hits:
                return ""
            _, word = self._sensitive_hits.popleft()
            return word

    def describe_steps(self, steps):
        return " → ".join(describe(step) for step in steps)
