# -*- coding: utf-8 -*-
# func/catpaws/core.py
# catpaws 核心：触发接管、启动链路、回收服务端回复（桥接 TTS 与记忆）、等 end 释放
import threading
import time

from func.catpaws.client import CWCatPawsClient
from func.catpaws.config import CWCatPawsConfig
from func.catpaws.if_start import CWCatPawsIfStart
from func.catpaws.memory import CWCatPawsMemory
from func.catpaws.prompt import CWCatPawsPrompt
from func.catpaws.state import CWCatPawsState
from func.catpaws.stop import CWCatPawsStop
from func.catpaws.voice import CWCatPawsVoice
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class CWCatPawsCore:
    """catpaws 链路调度：触发判断 → 启动 → 回复桥接 → 等 end 释放"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CWCatPawsConfig()
        self.client = CWCatPawsClient(self.config)
        self.state = CWCatPawsState()
        self.if_start = CWCatPawsIfStart(self.config)
        self.stop_port = CWCatPawsStop(self.config)
        self.memory = CWCatPawsMemory(self.config)
        self.prompt = CWCatPawsPrompt(self.config)
        self.voice = CWCatPawsVoice(self.config)
        self._lock = threading.RLock()
        self._thread = None

    def receive(self, text, username="", source="msg"):
        """接收一条消息，返回 True 表示本方已接管（拦截主链路）"""
        self.config.refresh()
        if not self.config.enabled:
            return False
        body = str(text or "").strip()
        if not body:
            return False
        username = str(username or "").strip()
        if not username:
            self.log.error("[CatPaws] 缺少身份编号，不接管本条")
            return False
        if self.state.is_active():
            return self._hold(body, username)
        try:
            from func.pipeline.silence_state import SilenceState
            if SilenceState().muted:
                return False
        except Exception:
            pass
        mode, goal = self.if_start.decide(body, username)
        if not mode:
            return False
        self.log.info("[CatPaws] 触发（%s）：%s" % (mode, body[:60]))
        self.memory.user(username, body)
        self._start(goal, username, body, source)
        return True

    def stop(self, reason="user"):
        """外部主动停止（GUI / 停止词）"""
        return self.stop_port.trigger(reason)

    def start_task(self, goal, username, text="", source="gui"):
        """外部主动指定目标启动（GUI 面板用，跳过触发判断）"""
        body = str(goal or "").strip()
        if not body:
            return False
        self.config.refresh()
        if not self.config.enabled:
            return False
        username = str(username or "").strip()
        if not username:
            self.log.error("[CatPaws] 缺少身份编号，拒绝启动")
            return False
        self.memory.user(username, body)
        return self._start(body, username, str(text or body), source)

    def is_active(self):
        return self.state.is_active()

    def status(self):
        return {"state": self.state.snapshot(), "remote": self.client.status()}

    def send_text(self, text, username):
        """链路进行中把主人这句话交给服务端（有提问＝回答，没有＝补充指令）"""
        body = str(text or "").strip()
        if not body:
            return False
        return self._hold(body, username)

    def _hold(self, body, username):
        """链路进行中：停止词立即停；其余当补充指令转给服务端"""
        if self.stop_port.is_stop(body):
            self.memory.user(username, body)
            self.stop_port.trigger("keyword")
            return True
        self.memory.user(username, body)
        result = self.client.answer(body)
        if not result.get("ok"):
            self.log.warning("[CatPaws] 补充指令未送达：%s" % result.get("message", ""))
        return True

    def _start(self, goal, username, text, source):
        """启动服务端链路；服务不可用或手机没连上时以角色口吻说明"""
        status = self.client.status()
        if not status.get("ok"):
            self.log.warning("[CatPaws] 服务不可用：%s" % status.get("message", ""))
            self.voice.excuse("手机控制服务没有启动，现在没法操作手机", username)
            return False
        device = status.get("device") or {}
        if device.get("error"):
            self.log.warning("[CatPaws] 手机未连接：%s" % device.get("error"))
            self.voice.excuse("手机没有连上，现在没法操作", username)
            return False
        if device.get("mock") and not self.config.allow_mock:
            self.log.warning("[CatPaws] 当前是 mock 设备，拒绝真机操作")
            self.voice.excuse("手机还没连上真机，现在没法操作", username)
            return False
        with self._lock:
            if self.state.is_active():
                return False
            payload = self.prompt.build(goal, username, text)
            result = self.client.start(payload)
            if not result.get("ok"):
                self.log.warning("[CatPaws] 启动失败：%s" % result.get("message", ""))
                self.voice.excuse("手机那边没接上这个任务，现在办不了", username)
                return False
            session = str((result.get("session") or {}).get("session") or "")
            self.state.begin(goal, username, session)
            run_id = self.state.snapshot().get("run_id")
            self._thread = threading.Thread(target=self._run, args=(username, run_id),
                                            name="catpaws-sync", daemon=True)
            self._thread.start()
        self.log.info("[CatPaws] 链路启动（%s）：%s" % (source, goal[:60]))
        return True

    def _run(self, username, run_id):
        """轮询服务端：把角色回复桥接出去，等 end 之后释放拦截"""
        started = time.time()
        reason = ""
        while self.state.is_active() and self.state.snapshot().get("run_id") == run_id:
            status = self.client.status()
            if not status.get("ok"):
                reason = "service_down"
                break
            self._consume(username)
            remote = status.get("session") or {}
            phase = str(remote.get("phase") or "idle")
            self.state.sync(phase=phase, session=str(remote.get("session") or ""))
            if phase == "end" or (phase == "idle" and not status.get("agent_busy")):
                reason = str(remote.get("reason") or "done")
                break
            if self.config.max_run_sec > 0 and time.time() - started > self.config.max_run_sec:
                self.log.warning("[CatPaws] 超过 %s 秒仍无结果，停止链路" % self.config.max_run_sec)
                self.client.stop("timeout")
                reason = "timeout"
                break
            time.sleep(max(0.2, self.config.poll_sec))
        snapshot = self.state.snapshot()
        if snapshot.get("run_id") == run_id and not snapshot.get("reason"):
            self.state.finish(reason)
            snapshot = self.state.snapshot()
        self.log.info("[CatPaws] 链路结束（%s）" % (snapshot.get("reason") or reason))

    def _consume(self, username):
        """拉取增量事件：角色说的话写入记忆并播报，服务端提问则按序暂停等回答"""
        data = self.client.replies(self.state.seq())
        if not data.get("ok"):
            return
        remote_session = str(data.get("session") or "")
        current_session = str(self.state.snapshot().get("session") or "")
        if remote_session and remote_session != current_session:
            self.state.sync(session=remote_session, seq=0)
            return
        for item in data.get("items") or []:
            index = int(item.get("seq") or 0)
            if index <= self.state.seq():
                continue
            if str(item.get("kind") or "") == "ask":
                self.state.sync(seq=index)
                self._answer(item, username)
                continue
            self._event(item, username)
            self.state.sync(seq=index)

    def _event(self, item, username):
        """单条事件分发：assistant 说话 → 记忆 + TTS；error 只记日志"""
        kind = str(item.get("kind") or "")
        if kind == "assistant":
            text = str(item.get("text") or "").strip()
            if text:
                self.memory.reply(username, text)
                self.voice.speak(text)
        elif kind == "error":
            self.log.warning("[CatPaws] 服务端异常：%s %s"
                             % (item.get("code", ""), item.get("message", "")))

    def _answer(self, item, username):
        """服务端在等回答：提问按事件顺序写进记忆并播报，再等一条回复送回去"""
        text = str(item.get("question") or "").strip()
        if not text:
            return
        options = [str(opt) for opt in (item.get("options") or []) if str(opt)]
        self.memory.reply(username, text)
        self.voice.speak(text)
        reply = self.voice.wait(username, self.config.answer_timeout or 300)
        if reply and self.stop_port.is_stop(reply):
            self.stop_port.trigger("keyword")
            return
        if reply:
            self.memory.user(username, reply)
            self.client.answer(reply)
        else:
            self.client.answer("")
        self.log.info("[CatPaws] 提问已回答（选项 %s）" % "/".join(options))
