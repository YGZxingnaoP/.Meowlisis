# -*- coding: utf-8 -*-
"""睡前关机：主链路专用（绝不接 QQ）。

流程：
    1. 角色回复里出现「愿弦月之眼保佑你」，或主人说要去睡/多次晚安后调用工具
    2. 写 plugins/pc_power/state.json，进入睡前监听（默认 300 秒）
    3. 监听期间主人说话就重写计时；说「别关」就取消
    4. 到点后体检下载/上传进程：有就转为确认态；没有就结束服务并关机
"""

import datetime
import os
import threading
import time

from func.pipeline.plugins_state import CAP_ACTIVE_REPLY
from func.toolbox.plugins.sdk import CHANNEL_MAIN, ToolboxPlugin, TriggerTool

from . import power
from .monitor import SleepMonitor, _bool, _num
from .state import CONFIRM, IDLE, LISTENING, OFF, StateStore

SLEEP_WORDS = ("睡觉", "去睡", "睡了", "睡吧", "要睡", "困了")
GOODNIGHT_WORDS = ("晚安", "睡啦", "睡咯")
DEFAULT_TRIGGER_PHRASE = "愿弦月之眼保佑你"
REPLY_FRESH_SEC = 180


def latest_assistant_message():
    """取主链路最后一条助手回复（内存轮，不落 json，能立刻看到）"""
    try:
        from func.llm.llm_core import LLmCore
        builder = getattr(LLmCore(), "message_builder", None)
        history = getattr(builder, "history", None) or []
        for item in reversed(history):
            if item.get("role") == "assistant" and str(item.get("content") or "").strip():
                return item
    except Exception:
        pass
    return {}


def _fresh_enough(item):
    """回复是否发生在最近几分钟内（防旧消息被重复判断）"""
    raw = str(item.get("time") or "").strip()
    if not raw:
        return True
    try:
        stamp = datetime.datetime.strptime(raw, "%Y-%m-%d %H:%M")
        return abs((datetime.datetime.now() - stamp).total_seconds()) <= REPLY_FRESH_SEC
    except Exception:
        return True


class PcPowerTool(TriggerTool):
    name = "pc_power_bedtime"
    description = ("睡前关机监听：只有主人明确表示要去睡了、或已经互道晚安并准备睡觉时才能调用。"
                   "其它任何情况（聊天、开玩笑、问空调音量、群里说话）一律不准调用。")
    parameters = {
        "action": {"type": "string", "enum": ["begin", "cancel", "status"],
                   "description": "begin=开始睡前监听；cancel=取消；status=看当前状态"},
        "note": {"type": "string", "description": "这次触发的原因，可省略"},
    }
    required = ["action"]
    channels = (CHANNEL_MAIN,)

    def __init__(self, plugin):
        self.plugin = plugin

    def handle(self, arguments, ctx):
        return self.plugin.on_tool(arguments, ctx)

    def handle_qq(self, arguments, qq_context, ctx):
        """主链路专用：QQ 链路任何时候都不执行"""
        return None

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return self.plugin.observe_text(text, meowid, channel)


class Plugin(ToolboxPlugin):
    id = "pc_power"
    title = "睡前关机"
    version = "1.0.0"
    default_enabled = False

    def __init__(self):
        self._ctx = None
        self._cfg = {}
        self._store = None
        self._monitor = None
        self._active = False
        self._last_sig = ()
        self._last_user_signal = 0.0
        self._last_uid = ""
        self._recent_lines = []

    # ==================== 生命周期 ====================
    def setup(self, ctx):
        self._ctx = ctx
        self._cfg = dict(ctx.config or {})
        self._store = StateStore(os.path.join(ctx.plugin_dir(), "state.json"))
        old_phase = self._store.read().get("phase")
        self._store.reset_stale()
        self._active = True
        ctx.log.info("[pc_power] 启动重置状态（上次 phase=%s），不会沿用上次监听", old_phase)
        self._monitor = SleepMonitor(
            self._store, self._cfg, ctx.log,
            say_need=self._say_need,
            transfer_check=self._transfer_check,
            power_exec=self._power_exec,
            on_idle=self._on_idle,
        )
        self._monitor.start()
        self._subscribe()
        ctx.log.info("[pc_power] 已启用：监听 %s 秒，模式 %s，dry_run=%s，state=%s",
                     _num(self._cfg, "window_sec", 300),
                     self._cfg.get("mode", "shutdown"),
                     power.dry_run(self._cfg), self._store.path)

    def teardown(self):
        self._active = False
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        try:
            if self._store and self._store.read().get("phase") in (LISTENING, CONFIRM):
                self._store.cancel("plugin_stop")
        except Exception:
            pass
        try:
            if self._ctx:
                self._ctx.state().exit()
        except Exception:
            pass
        self._ctx = None

    def _subscribe(self):
        try:
            from func.pipeline.llm_timer import LLMTimerBridge
            LLMTimerBridge().subscribe(on_user_message=self._on_user_message,
                                       on_ai_reply=self._on_ai_reply)
        except Exception:
            self._ctx.log.exception("[pc_power] 订阅活动桥接失败")

    # ==================== 工具 ====================
    def trigger_tools(self):
        return [PcPowerTool(self)]

    def interface_tools(self):
        return []

    def state_decl(self):
        return {"title": "睡前监听", "caps": {CAP_ACTIVE_REPLY: False}}

    def prompt_hint(self):
        return ("- 睡前关机（仅主链路，QQ 不可用）：主人说要睡了 / 互道晚安 → "
                "pc_power_bedtime(action=begin)；说「别关电脑」→ action=cancel。")

    def on_tool(self, arguments, ctx):
        request = ctx.request() or {}
        uid = str(request.get("meowid") or ctx.uid() or "")
        if uid:
            self._last_uid = uid
        action = str((arguments or {}).get("action") or "status").strip().lower()
        if action == "status":
            return self._describe()
        if action == "cancel":
            self._leave("tool_cancel")
            return "好，不关了。"
        if action == "begin":
            return self._begin_by_tool(ctx)
        return "未知动作：%s" % action

    def _begin_by_tool(self, ctx):
        if not self._active:
            return "插件还没准备好，先不监听。"
        state = self._store.read()
        if state.get("phase") in (LISTENING, CONFIRM):
            self._store.touch()
            return "已经在睡前监听里了，这次重新计时。"
        text = str((ctx.request() or {}).get("text") or "")
        count = int(state.get("goodnight_count") or 0)
        ok, why = self._may_begin(text, count)
        if not ok:
            return why
        self.start_listening("tool", text)
        return "好，我开始听着了；%d 秒内你不说话，我就关电脑去睡。" % int(
            _num(self._cfg, "window_sec", 300))

    def _may_begin(self, text, goodnight_count):
        body = str(text or "")
        if any(word in body for word in SLEEP_WORDS):
            return True, ""
        need = int(_num(self._cfg, "min_goodnight", 2))
        if goodnight_count >= need:
            return True, ""
        return False, "还没到要睡的时候吧，再聊会儿。"

    # ==================== 监听 ====================
    def start_listening(self, trigger, note=""):
        if not self._active or not self._store:
            return False
        window = _num(self._cfg, "window_sec", 300)
        self._store.begin(trigger, window, note=note)
        try:
            self._ctx.state().enter()
        except Exception:
            self._ctx.log.exception("[pc_power] 进入监听态失败")
        self._ctx.log.info("[pc_power] 开始睡前监听（%s），%.0f 秒", trigger, window)
        return True

    def _leave(self, reason):
        if not self._store:
            return
        self._store.cancel(reason)
        try:
            self._ctx.state().exit()
        except Exception:
            pass
        self._ctx.log.info("[pc_power] 退出监听：%s", reason)

    def cancel_words(self):
        return power.csv_list(self._cfg.get("cancel_words"),
                              ("别关", "不要关", "别关机", "不关电脑", "先别关", "不准关"))

    def confirm_words(self):
        return power.csv_list(self._cfg.get("confirm_words"),
                              ("关吧", "关掉", "确认关机", "关机吧", "可以关了", "现在关"))

    @staticmethod
    def _hit(text, words):
        body = str(text or "")
        return any(str(word) and str(word) in body for word in words)

    # ==================== 活动桥接 ====================
    def _on_user_message(self):
        if not self._active or not self._store:
            return
        now = time.time()
        if now - self._last_user_signal < 1.5:
            return
        self._last_user_signal = now
        state = self._store.read()
        if state.get("phase") in (LISTENING, CONFIRM):
            self._store.touch(now)
            self._ctx.log.info("[pc_power] 主人说话，监听重新计时")

    def _on_ai_reply(self, source="llm"):
        if not self._active or not self._store:
            return
        if source in ("danmaku",):
            return
        if not _bool(self._cfg, "watch_reply", True):
            return
        item = latest_assistant_message()
        text = str(item.get("content") or "")
        sig = (id(item), text)
        if not text or sig == self._last_sig:
            return
        self._last_sig = sig
        phrase = str(self._cfg.get("trigger_phrase") or DEFAULT_TRIGGER_PHRASE)
        if not phrase or phrase not in text:
            return
        if not _fresh_enough(item):
            return
        if self._store.read().get("phase") != IDLE:
            return
        self.start_listening("phrase", phrase)
        self._ctx.log.info("[pc_power] 回复命中睡前语句，进入监听")

    # ==================== 主链路输入 ====================
    def observe_text(self, text, meowid="", channel=CHANNEL_MAIN):
        """只观察主链路输入：说话重置计时，说「别关」取消；绝不接管输入"""
        if not self._active or not self._store or channel != CHANNEL_MAIN:
            return False
        body = str(text or "")
        if not body.strip():
            return False
        if meowid:
            self._last_uid = str(meowid)
        self._last_user_signal = time.time()
        state = self._store.read()
        phase = state.get("phase")
        if phase == OFF:
            # 系统关机倒计时内仍可撤销：主人一句「别关」就把 shutdown /a 打出去
            if self._hit(body, self.cancel_words()) and power.abort_shutdown(self._ctx.log):
                self._leave("abort_after_scheduled")
                self._ctx.log.info("[pc_power] 关机倒计时已被主人撤销")
            return False
        if phase not in (LISTENING, CONFIRM):
            if self._hit(body, GOODNIGHT_WORDS):
                self._store.note_goodnight(_num(self._cfg, "goodnight_gap_sec", 1800))
            return False
        if self._hit(body, self.cancel_words()):
            self._leave("user_cancel")
            return False
        if phase == CONFIRM and self._hit(body, self.confirm_words()):
            self._ctx.log.info("[pc_power] 主人确认关机")
            threading.Thread(target=self._monitor.execute, args=("confirmed",),
                             daemon=True).start()
            return False
        if self._hit(body, GOODNIGHT_WORDS):
            self._store.note_goodnight(_num(self._cfg, "goodnight_gap_sec", 1800))
        self._store.touch()
        return False

    # ==================== 动作 ====================
    def _transfer_check(self, keywords, mbps):
        exclude = (os.getpid(),)
        return power.find_transfer_processes(
            power.csv_list(keywords, power.DEFAULT_TRANSFER_KEYWORDS),
            net_busy_mbps=mbps, exclude_pids=exclude, log=self._ctx.log)

    def _power_exec(self):
        cfg = self._cfg
        log = self._ctx.log
        dry = power.dry_run(cfg)
        if not dry and _bool(cfg, "stop_processes", True):
            keywords = power.csv_list(cfg.get("process_keywords"),
                                      power.DEFAULT_SERVICE_KEYWORDS)
            power.stop_services(keywords, dry_run=False, log=log)
        mode = str(cfg.get("mode") or "shutdown")
        delay = _num(cfg, "shutdown_delay_sec", 20)
        return power.schedule_shutdown(mode, delay, dry_run=dry,
                                       note=str(cfg.get("shutdown_note") or "喵呜要睡了"),
                                       log=log)

    def _say_need(self, need, max_chars=40):
        """口播内容交给角色 LLM 现场组织（程序只给「要说什么事」）"""
        if not self._ctx:
            return
        threading.Thread(target=self._compose_and_speak,
                         args=(str(need), int(max_chars)), daemon=True).start()

    def _compose_and_speak(self, need, max_chars):
        if not self._ctx:
            return
        try:
            from func.toolbox.character_voice import TBoxCharacterVoice
            history = []
            try:
                from func.pipeline.short_memory import ShortMemory
                history = [{"role": m.get("role"), "content": m.get("content")}
                           for m in ShortMemory().load_by_type(("llm_fast_response",))[-4:]]
            except Exception:
                history = []
            line = TBoxCharacterVoice().line(
                need, self._last_uid or "", history=history,
                max_chars=max_chars, avoid=tuple(self._recent_lines))
        except Exception:
            self._ctx.log.exception("[pc_power] 角色组织语言失败")
            return
        line = str(line or "").strip()
        if not line:
            self._ctx.log.warning("[pc_power] 没组织出话，这次不出声")
            return
        self._recent_lines.append(line)
        del self._recent_lines[:-6]
        self._speak_line(line)

    def _speak_line(self, line):
        if not self._ctx:
            return
        try:
            self._ctx.tts().send_stream(str(line), source="toolbox_pc_power")
        except Exception:
            self._ctx.log.exception("[pc_power] 口播失败")

    def _on_idle(self, reason):
        try:
            self._ctx.state().exit()
        except Exception:
            pass

    def _describe(self):
        state = self._store.read() if self._store else {}
        phase = state.get("phase", IDLE)
        left = max(0.0, float(state.get("deadline") or 0) - time.time())
        return ("phase=%s left=%.0fs trigger=%s resets=%s goodnight=%s cancel=%s"
                % (phase, left, state.get("trigger", ""), state.get("resets", 0),
                   state.get("goodnight_count", 0), state.get("cancel_reason", "")))


PLUGIN = Plugin()
