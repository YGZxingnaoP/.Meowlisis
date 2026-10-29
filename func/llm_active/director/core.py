# -*- coding: utf-8 -*-
# func/llm_active/director/core.py
# 导演核心：生命周期（触发 → 规划 → 表演 → 失望/重写 → clear）+ 端口持有

import json
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.llm_active.config import AutoActiveConfig
from func.llm_active.director.config import AutoDirectorConfig
from func.llm_active.director.judge import DirectorJudge
from func.llm_active.director.planner import DirectorPlanner
from func.llm_active.director.responder import DirectorResponder
from func.llm_active.director.state import apply_step as apply_step_state
from func.llm_active.director.state import render_status
from func.llm_active.director.tools import STEP_TOOL_NAME, step_tool
from func.pipeline.llm_director import LLMDirectorBridge
from func.pipeline.llm_timer import LLMTimerBridge
from func.pipeline.short_memory import ShortMemory


@singleton
class DirectorCore:
    """导演核心（主链路）：只服务电脑端对话，QQ 不接入"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.bridge = LLMDirectorBridge()
        self.short_memory = ShortMemory()
        self._lock = threading.RLock()
        self._silent = 0
        self._stall = 0
        self._user_spoke = False
        self._user_seq = 0
        self._cooldown_until = 0.0

        # 三个独立端口：判官/规划器/表演各用各的，避免临时改 max_tokens 串参数
        cfg = AutoDirectorConfig()
        self.judge_llm = self._create_port(cfg.judge_max_tokens)
        self.plan_llm = self._create_port(cfg.planner_max_tokens)
        self.reply_llm = self._create_port(None)

        self.judge = DirectorJudge(self)
        self.planner = DirectorPlanner(self)
        self.responder = DirectorResponder(self)

        # 进入/退出事件（宿主归档由桥接负责）
        self.bridge.subscribe(on_entered=self._on_entered, on_cleared=self._on_cleared)
        # 计时桥订阅：用户说话标记 + 每轮回复后判官
        LLMTimerBridge().subscribe(on_user_message=self._on_user_message,
                                   on_ai_reply=self.judge.on_ai_reply)

        # 重启不恢复旧计划（默认），避免几小时前的计划复活
        try:
            if not cfg.resume_on_start and self.bridge.is_active("main"):
                self.bridge.clear("main", "重启")
        except Exception:
            self.log.exception("[导演] 重启清理旧计划失败")

    # ==================== 端口 ====================
    @staticmethod
    def _create_port(max_tokens=None):
        """按 llm_active 的后端类型建一个独立端口（配置复用，端口不复用）"""
        cfg = AutoActiveConfig()
        kind = str(cfg.llm_type or "")
        if kind == "meowllm":
            from func.llm_active.port.meowllm import AutoMeowLLM as port_cls
        elif kind == "gemini":
            from func.llm_active.port.gemini import AutoGeminiLLM as port_cls
        elif kind == "aliyun":
            from func.llm_active.port.aliyun import AutoAliyunLLM as port_cls
        else:
            from func.llm_active.port.deepseek import AutoDeepSeekLLM as port_cls
        port = port_cls()
        if max_tokens:
            port.max_tokens = int(max_tokens)
        return port

    def rebuild(self):
        """配置热重载：重建三个端口（配置项由 AutoDirectorConfig 单例原地刷新）"""
        from func.llm.port import close_port_later
        cfg = AutoDirectorConfig()
        old = [self.judge_llm, self.plan_llm, self.reply_llm]
        self.judge_llm = self._create_port(cfg.judge_max_tokens)
        self.plan_llm = self._create_port(cfg.planner_max_tokens)
        self.reply_llm = self._create_port(None)
        for port in old:
            close_port_later(port)
        # 导演总开关被关掉时，别把已经激活的旧计划留在提示词里
        try:
            if not cfg.enabled and self.bridge.is_active("main"):
                self.bridge.clear("main", "配置关闭")
        except Exception:
            self.log.exception("[导演] 关闭导演时清理状态失败")
        # 短期记忆轮数可能被改过：同步给副本的 MessageBuilder
        try:
            from func.llm.config import LLMConfig
            self.responder.builder.set_max_rounds(int(LLMConfig().short_term_rounds))
        except Exception:
            self.log.exception("[导演] 同步短期记忆轮数失败")

    # ==================== 查询 ====================
    def is_active(self) -> bool:
        return self.bridge.is_active("main")

    def current_plan(self) -> dict:
        return self.bridge.get("main")

    def cooldown_ok(self) -> bool:
        """冷却是否结束（clear / 启动后冷却，防刚结束又开）"""
        return time.time() >= self._cooldown_until

    def set_cooldown(self, seconds=None):
        try:
            if seconds is None:
                seconds = AutoDirectorConfig().cooldown_after_clear
            self._cooldown_until = time.time() + max(0.0, float(seconds))
        except Exception:
            self._cooldown_until = time.time() + 600

    # ==================== 触发（AutoActiveCore 调用） ====================
    def on_idle_trigger(self, forced: bool = False, reason: str = "") -> bool:
        """主动回复触发时的第一分支：True=导演已接管，False=走原 inherit/origin"""
        cfg = AutoDirectorConfig()
        if not cfg.enabled:
            return False
        if self.is_active():
            self._idle_loop()
            return True
        kind = "start_bored" if forced else "start_idle"
        seq = self._user_seq
        plan = self.planner.plan(kind, reason=reason)
        if not plan:
            return False
        if self._user_seq != seq:
            # 规划期间主人开口了：让主链路去回他，这次不再主动开场
            self.log.info("[导演] 规划期间主人开口，放弃本次开场")
            return True
        self._begin(plan)
        self.responder.speak(kind, uid=self._last_uid(), user_text=self._last_user_text())
        return True

    def enqueue_user_turn(self, uid, text, source="msg", traceid="") -> bool:
        """入口桥调用：导演激活时接管用户回合"""
        if not self.is_active():
            return False
        return self.responder.enqueue(uid, text, source, traceid)

    # ==================== 计划推进 ====================
    def apply_step(self, payload: dict):
        """应用一次 director_step 结果（完成打标 / 调整 / 推进 / clear）"""
        with self._lock:
            plan = self.current_plan()
            if not plan.get("active"):
                return
            try:
                result = apply_step_state(plan, payload or {})
            except Exception:
                self.log.exception("[导演] 推进计划失败（参数异常），保持原状")
                return
            self._stall = 0
            self.bridge.set_state("main", plan)
            if result.get("clear"):
                self.bridge.clear("main", result.get("reason") or "")
            elif result.get("changed"):
                self.log.info(f"[导演] 计划推进：\n{render_status(plan)}")

    def note_no_step(self):
        """这一轮没拿到 director_step：累计失步，必要时补一次小监工"""
        cfg = AutoDirectorConfig()
        self._stall += 1
        limit = int(cfg.stall_turns or 0)
        if limit <= 0 or self._stall < limit:
            return
        self._stall = 0
        threading.Thread(target=self._catch_up, daemon=True).start()

    def note_utterance(self):
        """导演说过话：下一次空闲触发重新开始累计「没收到消息」"""
        self._user_spoke = False

    # ==================== 内部 ====================
    def _begin(self, plan):
        """写入激活状态（桥接会通知宿主归档 + 通知本核心重置计数）"""
        self._silent = 0
        self._stall = 0
        self.bridge.activate("main", plan)

    def _idle_loop(self):
        """导演激活中，空闲计时又到期：失望一轮，或累计够次数就重写"""
        cfg = AutoDirectorConfig()
        if self._user_spoke:
            self._silent = 0
        else:
            self._silent += 1
        limit = max(1, int(cfg.silent_rounds))
        if self._silent >= limit:
            seq = self._user_seq
            plan = self.planner.plan("rewrite", reason="连着几次他都没接，换一条路")
            if plan:
                self._silent = 0
                self._begin(plan)
                if self._user_seq != seq:
                    self.log.info("[导演] 重写期间主人开口，跳过本次额外开口")
                    return
                self.responder.speak("rewrite", uid=self._last_uid())
                return
            self.log.warning("[导演] 重写失败，退回失望回合")
        self.responder.speak("idle_disappointed", uid=self._last_uid())

    def _catch_up(self):
        """折叠工具漏打标时的补判：只让模型补交一次 director_step"""
        try:
            plan = self.current_plan()
            if not plan.get("active"):
                return
            rows = self.short_memory.load_by_type(("llm_fast_response",))[-6:]
            recent = "\n".join(f"{'主人' if m.get('role') == 'user' else '我'}：{m.get('content', '')}"
                               for m in rows)
            messages = [
                {"role": "system", "content": (
                    "你在补记上一轮表演的进度：只根据最近这段对话，调用 director_step 交回"
                    "完成情况/下一步/要不要 clear，不要说话、不要写正文。")},
                {"role": "user", "content": (
                    f"【当前计划】\n{render_status(plan)}\n\n【最近对话】\n{recent}\n\n"
                    f"必须调用 {STEP_TOOL_NAME}。")},
            ]
            resp = self.judge_llm.chat(
                messages, tools=[step_tool()],
                tool_choice={"type": "function", "function": {"name": STEP_TOOL_NAME}},
                options={"enable_thinking": False})
            args = self._parse_step(resp)
            if args:
                self.log.info("[导演] 补判已补回进度")
                self.apply_step(args)
        except Exception:
            self.log.exception("[导演] 补判失败")

    @staticmethod
    def _parse_step(resp):
        if not resp or not getattr(resp, "choices", None):
            return None
        msg = resp.choices[0].message
        for tc in (getattr(msg, "tool_calls", None) or []):
            if str(getattr(tc.function, "name", "")) != STEP_TOOL_NAME:
                continue
            try:
                args = json.loads(tc.function.arguments or "{}", strict=False)
            except Exception:
                return None
            return args if isinstance(args, dict) else None
        return None

    def _last_uid(self):
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            return str(MeowLLMLtMemBridge().last_uid or "")
        except Exception:
            return ""

    def _last_user_text(self) -> str:
        try:
            for m in reversed(self.short_memory.load_by_type(("llm_fast_response",))):
                if m.get("role") == "user":
                    return str(m.get("content") or "")
        except Exception:
            pass
        return ""

    # ==================== 事件 ====================
    def _on_user_message(self):
        self._user_spoke = True
        with self._lock:
            self._user_seq += 1

    def _on_entered(self, scope="main"):
        with self._lock:
            self._silent = 0
            self._stall = 0
            self._user_spoke = False

    def _on_cleared(self, scope="main"):
        with self._lock:
            self._silent = 0
            self._stall = 0
            self._user_spoke = False
        self.set_cooldown()
        self.responder.flush_memory()
