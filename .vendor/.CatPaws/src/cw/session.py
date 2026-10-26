import collections
import threading
import time


class CWSession:
    IDLE = "idle"
    RUNNING = "running"
    REFLECTING = "reflecting"

    def __init__(self, config, journal):
        self.config = config
        self.journal = journal
        self._lock = threading.RLock()
        self.phase = self.IDLE
        self.goal = ""
        self.finish_reason = ""
        self.started_at = 0.0
        self.ended_at = 0.0
        self.session_id = ""
        self.stop_event = threading.Event()
        self._asking = False
        self._question = ""
        self._options = []
        self._answer = ""
        self._answer_event = threading.Event()
        self._instructions = collections.deque(maxlen=20)

    def begin(self, goal):
        with self._lock:
            self.goal = goal
            self.finish_reason = ""
            self.started_at = time.time()
            self.ended_at = 0.0
            self.stop_event.clear()
            self.phase = self.RUNNING
            self.session_id = self.journal.new_session()
            self._asking = False
            self._question = ""
            self._answer = ""
            self._answer_event.clear()
            self._instructions.clear()
            snapshot = self._snapshot_locked()
        self.journal.record("phase", phase=self.RUNNING, goal=goal, session=self.session_id)
        return snapshot

    def set_phase(self, phase):
        with self._lock:
            if self.phase == phase:
                return
            self.phase = phase
        self.journal.record("phase", phase=phase)

    def request_stop(self, reason="user"):
        with self._lock:
            self.finish_reason = reason
            self.stop_event.set()
            asking = self._asking
        if asking:
            self.answer("")
        self.journal.record("stop_request", reason=reason)

    def is_stopping(self):
        return self.stop_event.is_set()

    def finish(self, reason=""):
        with self._lock:
            if reason:
                self.finish_reason = reason
            self.ended_at = time.time()
            self.phase = self.IDLE
            self.stop_event.clear()
            self._asking = False
        self.journal.record("phase", phase=self.IDLE, reason=self.finish_reason)

    def ask(self, question, options=None, timeout=None):
        wait_for = float(timeout if timeout is not None else self.config.ask_timeout_sec)
        with self._lock:
            self._asking = True
            self._question = str(question)
            self._options = [str(item) for item in (options or [])]
            self._answer = ""
            self._answer_event.clear()
        self.journal.record("ask", question=self._question, options=self._options,
                            timeout_sec=int(wait_for))
        ok = self._answer_event.wait(wait_for)
        with self._lock:
            self._asking = False
            answer = self._answer
        self.journal.record("answer", question=self._question, answer=answer, answered=bool(ok))
        return answer

    def answer(self, text):
        with self._lock:
            if not self._asking:
                return False
            self._answer = str(text or "")
            self._answer_event.set()
        return True

    def push_instruction(self, text):
        body = str(text or "").strip()
        if not body:
            return False
        with self._lock:
            if self.phase == self.IDLE:
                return False
            self._instructions.append(body)
        self.journal.record("instruction", text=body[:200])
        return True

    def take_instructions(self):
        with self._lock:
            if not self._instructions:
                return []
            items = list(self._instructions)
            self._instructions.clear()
        return items

    def pending_question(self):
        with self._lock:
            if not self._asking:
                return None
            return {"question": self._question, "options": list(self._options)}

    def _snapshot_locked(self):
        return {
            "phase": self.phase,
            "goal": self.goal,
            "session": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "reason": self.finish_reason,
            "stopping": self.stop_event.is_set(),
            "elapsed_sec": int(time.time() - self.started_at) if self.started_at else 0,
        }

    def snapshot(self):
        with self._lock:
            return self._snapshot_locked()
