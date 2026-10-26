import re
import threading
import time

from func.catpaws.client import CWCatPawsClient
from func.catpaws.config import CWCatPawsConfig
from func.catpaws.if_start import CWCatPawsIfStart
from func.catpaws.state import CWCatPawsState
from func.catpaws.stop import CWCatPawsStop
from func.catpaws.voice import CWCatPawsVoicePort
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

CW_RULES = (
    "执行要求：\n"
    "1. 先 cw_observe(mode=ocr) 看清屏幕，点按用 OCR 框中心，不要盲点。\n"
    "2. 滑动用 direction+ratio（up/down/left/right，ratio 0.3~0.6），每次滑完 wait 400ms 再观察。\n"
    "3. 中文用 paste_text（type_text 只支持 ASCII）。\n"
    "4. 做完按 home 回桌面。\n"
    "5. 最后一行只输出 RESULT: OK 或 RESULT: FAIL <原因>。"
)


@singleton
class CWCatPawsCore:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CWCatPawsConfig()
        self.client = CWCatPawsClient(self.config)
        self.state = CWCatPawsState()
        self.if_start = CWCatPawsIfStart(self.config)
        self.stop_port = CWCatPawsStop()
        self.voice = CWCatPawsVoicePort()
        self._lock = threading.RLock()
        self._thread = None
        self._meowid = ""
        self._notify = self.config.notify

    def set_notify(self, on):
        self._notify = bool(on)

    def is_active(self):
        return self.state.is_active()

    def available(self):
        status = self.client.status()
        if not status.get("ok"):
            return False
        device = status.get("device") or {}
        return not bool(device.get("mock")) and not device.get("error")

    def receive(self, text, meowid="", source="msg"):
        if not self.config.enabled:
            return False
        body = str(text or "").strip()
        if not body:
            return False
        if self.state.is_active():
            status = self.client.status()
            remote = status.get("session") or {}
            if not status.get("ok") or (remote.get("phase") == "idle" and not status.get("agent_busy")):
                self.state.finish("stale")
            elif self.stop_port.is_stop(body):
                self.stop("keyword")
                return False
            else:
                return False
        hit, goal = self.if_start.decide(body)
        if not hit:
            return False
        if not goal:
            self.log.info("[CatPaws] 只说了触发词，没有目标：%s" % body)
            return False
        self.start(goal, str(meowid or "").strip(), source)
        return False

    def start(self, goal, meowid="", source="msg", notify=None):
        goal = str(goal or "").strip()
        if not self.config.enabled:
            return False, "catpaws 未启用"
        if not goal:
            return False, "目标为空"
        with self._lock:
            if self.state.is_active():
                return False, "已经在操作手机"
            status = self.client.status()
            if not status.get("ok"):
                self.log.warning("[CatPaws] 服务不可用：%s" % status.get("message", ""))
                return False, "服务不可用"
            device = status.get("device") or {}
            if device.get("mock") or device.get("error"):
                self.log.warning("[CatPaws] 设备未连接：%s" % device.get("error", "mock"))
                return False, "设备未连接"
            result = self.client.start(self._compose(goal))
            if not result.get("ok"):
                self.log.warning("[CatPaws] 启动失败：%s" % result.get("message", ""))
                return False, str(result.get("message") or "启动失败")
            remote = result.get("session") or {}
            session = str(remote.get("session") or "")
            self.state.begin(goal, session, source)
            self._meowid = str(meowid or "").strip()
            if notify is not None:
                self._notify = bool(notify)
            self._thread = threading.Thread(target=self._run, args=(session, self._meowid),
                                            name="catpaws-run", daemon=True)
            self._thread.start()
        self.log.info("[CatPaws] 链路启动：%s" % goal)
        return True, "开始操作手机"

    def stop(self, reason="user"):
        return self.stop_port.trigger(reason)

    def answer(self, text):
        result = self.client.answer(text)
        if result.get("ok") and result.get("queued"):
            self.log.info("[CatPaws] 补充指令已入队：%s" % str(text)[:80])
            return True
        if result.get("ok"):
            self.state.set_answer(text)
            return True
        return False

    def say(self, text):
        return self.answer(text)

    def status(self):
        remote = self.client.status()
        return {"service": bool(remote.get("ok")),
                "device": remote.get("device") or {},
                "state": self.state.snapshot(),
                "remote": remote}

    def _compose(self, goal):
        return "%s\n\n%s" % (goal, CW_RULES)

    def _answer(self, question):
        text = str((question or {}).get("question") or "").strip()
        if not text:
            return ""
        options = (question or {}).get("options") or []
        answer = self.voice.ask(text, self._meowid, self.config.answer_timeout, options)
        if answer:
            self.state.set_answer(answer)
        return answer

    def _run(self, session, meowid):
        started = time.time()
        reason = ""
        final = ""
        final_ok = False
        phase = "running"
        while True:
            status = self.client.status()
            if not status.get("ok"):
                reason = "service_down"
                break
            remote = status.get("session") or {}
            phase = str(remote.get("phase") or "idle")
            self.state.sync(phase, remote.get("session") or session)
            question = status.get("pending_question") or {}
            if question.get("question"):
                answer = self._answer(question)
                if answer:
                    self.client.answer(answer)
            if phase == "idle" and not status.get("agent_busy"):
                reason = str(remote.get("reason") or "done")
                final = str(status.get("final") or "")
                final_ok = bool(status.get("final_ok"))
                break
            if time.time() - started > self.config.max_run_sec:
                self.log.warning("[CatPaws] 超过 %s 秒，停止链路" % self.config.max_run_sec)
                self.client.stop("timeout")
                reason = "timeout"
                break
            time.sleep(max(0.3, self.config.poll_sec))
        ok = self._ok(reason, final)
        self.state.finish(reason, ok=ok, final=final)
        self.log.info("[CatPaws] 链路结束 ok=%s reason=%s concluded=%s final=%s"
                      % (ok, reason, final_ok, final[:160]))
        self._report(meowid, ok, reason, final)

    @staticmethod
    def _ok(reason, final):
        if reason != "done":
            return False
        text = str(final or "")
        if re.search(r"RESULT\s*[:：]\s*FAIL", text, re.I):
            return False
        return bool(re.search(r"RESULT\s*[:：]\s*OK", text, re.I))

    def _report(self, meowid, ok, reason, final):
        if not self._notify or not meowid:
            return
        body = re.sub(r"RESULT\s*[:：]\s*(OK|FAIL[^\n]*)", "", str(final or ""), flags=re.I).strip()
        body = body or str(reason or "")
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({"role": "assistant", "content": "【手机】" + body,
                                "type": "toolbox_catpaws"}, 50, trim_mode="items")
        except Exception:
            self.log.exception("[CatPaws] 写短期记忆失败")
        try:
            from func.pipeline.toolbox_llm import ToolboxLLMBridge
            ToolboxLLMBridge().send_to_llm(
                "（手机那边回来了，%s：%s）" % ("成了" if ok else "没成", body),
                meowid, source="toolbox")
        except Exception:
            self.log.exception("[CatPaws] 回传结果失败")
