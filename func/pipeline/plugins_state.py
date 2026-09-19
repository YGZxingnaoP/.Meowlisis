# -*- coding: utf-8 -*-
# func/pipeline/plugins_state.py
# 插件状态总线：插件声明「我正在占用」，框架各模块按能力位让位（标准化接口）

import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


# ==================== 标准能力位（框架与插件共用一套常量） ====================
CAP_DANMAKU = "danmaku"            # 是否读弹幕（朗读 + LLM 回复 + 工具分析）
CAP_DANMAKU_GIFT = "danmaku_gift"  # 是否播报礼物/舰长感谢（入账不受影响）
CAP_REMINDER = "reminder"          # 是否允许日程/待办提醒
CAP_ACTIVE_REPLY = "active_reply"  # 是否允许主动回复计时
CAP_TOOLBOX = "toolbox"            # 是否允许其它 toolbox 分析/工具派发
CAP_OTHER_TTS = "other_tts"        # 是否允许非本插件的 TTS 出声
CAP_VOICE_CHAT = "voice_chat"      # 是否允许语音闲聊回复

CAPS = (CAP_DANMAKU, CAP_DANMAKU_GIFT, CAP_REMINDER, CAP_ACTIVE_REPLY,
        CAP_TOOLBOX, CAP_OTHER_TTS, CAP_VOICE_CHAT)

# 缺省全开：没有插件声明状态时，框架行为与改动前完全一致
DEFAULT_CAPS = {cap: True for cap in CAPS}


@singleton
class PluginsStateBridge:
    """插件状态总线（标准接口，只做状态聚合，不认识任何具体插件）

    - 插件侧（写入）：enter / update / exit
    - 框架侧（读取）：allow / owner / is_active / snapshot / subscribe
    - 聚合规则：多个插件同时占用时，逐能力位取「与」（任一插件声明 False 即为 False）
    - 副作用：CAP_ACTIVE_REPLY 由允许变为禁止时自动暂停主动回复计时，反之恢复
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._states = {}                 # plugin_id -> {"title","caps","ts","meta"}
        self._subs = []                   # 状态变化订阅者
        self._lock = threading.RLock()
        self._active_reply_paused = False

    # ==================== 插件侧（写入） ====================
    def enter(self, plugin_id, caps=None, title="", meta=None):
        """插件进入状态：声明能力位占用（未列出的沿用默认 True）"""
        pid = str(plugin_id or "").strip()
        if not pid:
            return False
        merged = dict(DEFAULT_CAPS)
        for key, val in (caps or {}).items():
            if key in DEFAULT_CAPS:
                merged[key] = bool(val)
        with self._lock:
            state = self._states.get(pid)
            if state and state.get("caps") == merged:
                return True                       # 幂等：能力位没变则不重复处理
            self._states[pid] = {"title": title or pid, "caps": merged,
                                 "ts": time.time(), "meta": dict(meta or {})}
        blocked = [c for c in CAPS if not merged[c]]
        self.log.info(f"[插件状态] {pid} 进入：{title or pid}（禁用 "
                      f"{'/'.join(blocked) if blocked else '无'}）")
        self._sync_active_reply()
        self._notify(pid, True)
        return True

    def update(self, plugin_id, **caps):
        """插件运行中调整能力位（仅对已进入状态的插件生效）"""
        pid = str(plugin_id or "").strip()
        with self._lock:
            state = self._states.get(pid)
            if not state:
                return False
            for key, val in caps.items():
                if key in DEFAULT_CAPS and val is not None:
                    state["caps"][key] = bool(val)
            state["ts"] = time.time()
        self._sync_active_reply()
        self._notify(pid, True)
        return True

    def exit(self, plugin_id):
        """插件退出状态：释放全部能力位占用"""
        pid = str(plugin_id or "").strip()
        with self._lock:
            state = self._states.pop(pid, None)
        if state is None:
            return False
        self.log.info(f"[插件状态] {pid} 退出：{state.get('title') or pid}")
        self._sync_active_reply()
        self._notify(pid, False)
        return True

    # ==================== 框架侧（读取） ====================
    def is_active(self, plugin_id=None):
        """查询是否有插件处于占用状态（指定 id 则查该插件）"""
        with self._lock:
            if plugin_id is None:
                return bool(self._states)
            return str(plugin_id) in self._states

    def allow(self, cap):
        """当前是否允许某能力位（任一活跃插件禁用即为 False；未知能力位恒 True）"""
        key = str(cap or "")
        if key not in DEFAULT_CAPS:
            return True
        with self._lock:
            for state in self._states.values():
                if not state["caps"].get(key, True):
                    return False
        return True

    def owner(self, cap):
        """返回禁用该能力位的插件 id（无则空串，供日志/GUI 显示）"""
        key = str(cap or "")
        with self._lock:
            for pid, state in self._states.items():
                if not state["caps"].get(key, True):
                    return pid
        return ""

    def snapshot(self):
        """返回当前全部占用状态（供日志/GUI 展示）"""
        with self._lock:
            return {pid: {"title": st["title"], "caps": dict(st["caps"]),
                          "ts": st["ts"], "meta": dict(st["meta"])}
                    for pid, st in self._states.items()}

    def subscribe(self, callback):
        """注册状态变化订阅者（callback(plugin_id, active)）"""
        if callback is not None and callback not in self._subs:
            self._subs.append(callback)

    def unsubscribe(self, callback):
        """移除状态变化订阅者"""
        if callback in self._subs:
            self._subs.remove(callback)

    # ==================== 内部 ====================
    def _notify(self, plugin_id, active):
        """通知订阅者（单个异常不影响其它；在锁外触发）"""
        for cb in list(self._subs):
            try:
                cb(plugin_id, active)
            except Exception:
                self.log.exception("[插件状态] 订阅者回调异常")

    def _sync_active_reply(self):
        """按聚合结果暂停/恢复主动回复计时（幂等）"""
        want_paused = not self.allow(CAP_ACTIVE_REPLY)
        with self._lock:
            if want_paused == self._active_reply_paused:
                return
            self._active_reply_paused = want_paused
        if want_paused:
            self._pause_active_reply()
        else:
            self._resume_active_reply()

    def _pause_active_reply(self):
        """暂停主动回复计时"""
        try:
            from func.llm_active.active_core import AutoActiveCore
            AutoActiveCore().pause()
            self.log.info("[插件状态] 主动回复计时已暂停")
        except Exception:
            self.log.exception("[插件状态] 暂停主动回复计时失败")

    def _resume_active_reply(self):
        """恢复主动回复计时（其它全局暂停源仍在时不恢复）"""
        try:
            from func.pipeline.silence_state import SilenceState
            if SilenceState().muted:
                return
        except Exception:
            pass
        try:
            from func.pipeline.singing_state import SingingStateBridge
            if SingingStateBridge().is_singing():
                return
        except Exception:
            pass
        try:
            from func.llm_active.active_core import AutoActiveCore
            AutoActiveCore().resume()
            self.log.info("[插件状态] 主动回复计时已恢复")
        except Exception:
            self.log.exception("[插件状态] 恢复主动回复计时失败")


def allow(cap):
    """模块级快捷查询：当前是否允许某能力位（框架侧各模块使用）"""
    return PluginsStateBridge().allow(cap)


class PluginStateHandle:
    """插件状态句柄（标准接口）：插件只调 enter / update / exit

    能力位取自插件自身的 state_decl()，插件无需 import 框架内部单例；
    enter/exit 幂等，可在异常路径重复调用。
    """

    def __init__(self, plugin_id, decl=None, log=None):
        self._id = str(plugin_id or "")
        self._decl = dict(decl or {})
        self.log = log

    @property
    def id(self):
        """插件 id"""
        return self._id

    @property
    def title(self):
        """状态展示名"""
        return str(self._decl.get("title") or self._id or "")

    def declared_caps(self):
        """声明中的能力位"""
        return dict(self._decl.get("caps") or {})

    def enter(self, **caps):
        """进入状态；caps 可覆盖声明值（未声明且未覆盖时视为无状态，不占用任何能力）"""
        merged = self.declared_caps()
        for key, val in (caps or {}).items():
            if key in DEFAULT_CAPS and val is not None:
                merged[key] = bool(val)
        if not merged:
            return False
        return PluginsStateBridge().enter(self._id, caps=merged, title=self.title,
                                          meta=self._decl.get("meta"))

    def update(self, **caps):
        """运行中调整能力位"""
        return PluginsStateBridge().update(self._id, **caps)

    def exit(self):
        """退出状态"""
        return PluginsStateBridge().exit(self._id)

    def is_active(self):
        """本插件是否处于占用状态"""
        return PluginsStateBridge().is_active(self._id)
