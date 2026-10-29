# -*- coding: utf-8 -*-
# func/llm_active/director/responder.py
# 导演表演执行器：导演激活期间所有开口（开场 / 用户回合 / 失望 / 重写）都由这里生成
#
# 本文件是主链路 LLmCore._ai_response 的「复制编排」：
#   - 流式清洗/切段/水词：copied/output.py
#   - 短期记忆组装：copied/message_builder.py
#   - 情绪更新：copied/emotion.py
# 纪律：不 import func/llm/llm_core.py、output.py、narration/*、message_builder.py、
#       emotion_controller.py、state.py；跨模块一律走 func/pipeline 桥接。

import json
import queue
import threading
import uuid

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.llm.config import LLMConfig
from func.llm_active.config import AutoActiveConfig
from func.llm_active.director.copied.output import Output
from func.llm_active.director.copied.message_builder import MessageBuilder
from func.llm_active.director.copied.emotion import EmotionController
from func.llm_active.director.tools import STEP_TOOL_NAME, step_tool
from func.pipeline.llm_timer import LLMTimerBridge
from func.pipeline.llm_toolbox import LLMToolboxBridge, ToolCallAccumulator
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.pipeline.short_memory import ShortMemory
from func.pipeline.system_prompt import SystemPromptBridge


class DirectorResponder:
    """表演执行器：五种回合（start_bored / start_idle / reply / idle_disappointed / rewrite）"""

    def __init__(self, core):
        self.log = DefaultLog().getLogger()
        self.core = core
        self.builder = MessageBuilder(max_rounds=int(LLMConfig().short_term_rounds))
        self.ltmem = MeowLLMLtMemBridge()
        self.short_memory = ShortMemory()
        self.toolbox = LLMToolboxBridge()
        self._lock = threading.RLock()
        self._queue = queue.Queue(maxsize=32)
        self._worker = None
        self._worker_lock = threading.Lock()

    # ==================== 入队（用户回合） ====================
    def enqueue(self, uid, text, source="msg", traceid="") -> bool:
        """用户回合入队；立即重置一次主动回复计时（与主链路 msg_deal 一致）"""
        if not self.core.is_active():
            return False
        try:
            self._queue.put_nowait({"uid": str(uid or ""), "text": str(text or ""),
                                    "source": str(source or "msg"),
                                    "traceid": str(traceid or "")})
        except queue.Full:
            self.log.warning("[导演] 回合队列已满，丢弃本条")
            return False
        LLMTimerBridge().notify_user_message()
        self._ensure_worker()
        return True

    def _ensure_worker(self):
        with self._worker_lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._worker_loop, daemon=True,
                                            name="director-responder")
            self._worker.start()

    def _worker_loop(self):
        while True:
            try:
                item = self._queue.get(timeout=30)
            except queue.Empty:
                continue
            if item is None:
                return
            if not self.core.is_active():
                self.log.info("[导演] 已结束，丢弃积压的用户回合")
                continue
            try:
                with self._lock:
                    self._generate("reply", item["uid"], item["text"],
                                   item["source"], item["traceid"])
            except Exception:
                self.log.exception("[导演] 用户回合生成异常")

    # ==================== 同步开口（开场 / 失望 / 重写） ====================
    def speak(self, kind: str, uid=None, user_text: str = "",
              source: str = "llm", traceid: str = "") -> str:
        """同步生成一次开口；返回最终回复文本（失败为空串）"""
        if not self.core.is_active():
            return ""
        with self._lock:
            try:
                return self._generate(kind, uid, user_text, source, traceid)
            except Exception:
                self.log.exception(f"[导演] 开口生成异常（{kind}）")
                return ""

    def flush_memory(self):
        """退出导演时把副本内存里的轮次归档，保证与主链路顺序一致"""
        try:
            self.builder.flush_all()
        except Exception:
            self.log.exception("[导演] 归档副本短期记忆失败")

    # ==================== 生成 ====================
    def _generate(self, kind: str, uid, user_text: str, source: str, traceid: str) -> str:
        if not self.core.is_active():
            return ""
        if self._muted():
            self.log.info("[导演] 静默中，不出声")
            return ""
        cfg = LLMConfig()
        ai_name = str(AppConfig().ai_name or "")
        traceid = traceid or str(uuid.uuid4())
        is_reply = (kind == "reply")

        # 1) 工具与合并开关（与主链路一致：合并开着才挂 toolbox 工具）
        tools = [step_tool()]
        merge_on = False
        try:
            merge_on = bool(self.toolbox.merge_enabled())
        except Exception:
            merge_on = False
        if merge_on:
            tools = tools + self.toolbox.get_schemas()

        # 2) 用户侧长期记忆（与主链路顺序一致：先记用户，再判本地硬触发）
        if is_reply:
            try:
                self.ltmem.record_user_message(uid, user_text)
            except Exception:
                self.log.exception("[导演] 记录用户长期记忆失败")

        # 2.5) 本地硬触发（复制主链路 pre_route）：命中就派发工具、记一条用户短记忆并结束本轮
        if is_reply and merge_on:
            plan = None
            try:
                plan = self.toolbox.pre_route_plan(user_text, uid)
            except Exception:
                self.log.exception("[导演] 本地硬触发判断异常")
            if plan is not None:
                name, arguments = plan
                if name:
                    threading.Thread(
                        target=self.toolbox.handle_tool_calls,
                        args=([{"name": name, "arguments": arguments}], uid, user_text),
                        daemon=True).start()
                try:
                    self.builder.add_user_message(uid, user_text)
                except Exception:
                    self.log.exception("[导演] 本地硬触发记录短期记忆失败")
                LLMTimerBridge().notify_ai_reply(source="llm")
                self.log.info(f"[导演] 本地硬触发命中 {name or '插件会话'}，本轮不出表演台词")
                return ""

        # 3) 破甲审查（与主链路一样，在构建提示词之前）
        if is_reply:
            try:
                from func.pipeline.msg_rulebreak import MsgRuleBreakBridge
                MsgRuleBreakBridge().check_message(uid, user_text, self.short_memory.load())
            except Exception:
                self.log.exception("[导演] 破甲审查异常")

        # 4) 系统提示词（已含心理 + 导演块）
        prompt = self._system_prompt(kind, uid, user_text)
        if not prompt:
            self.log.warning("[导演] 系统提示词为空，放弃本次开口")
            return ""
        if merge_on:
            try:
                prompt = self.toolbox.attach_tool_hint(prompt)
            except Exception:
                self.log.exception("[导演] 追加工具提示失败")
        prompt = f"{prompt}\n\n{self._turn_hint(kind, user_text)}"

        # 5) 组装消息
        if is_reply:
            messages = self.builder.build_messages(uid, prompt, user_text)
            self.builder.add_user_message(uid, user_text)
        else:
            messages = self.builder.build_context(prompt)

        # 6) 请求参数（δ-mem 只走桥接）
        options = {"enable_thinking": False}
        if is_reply:
            try:
                options.update(self.ltmem.memory_options(uid) or {})
            except Exception:
                self.log.exception("[导演] δ-mem 上下文构建失败")

        # 7) 流式生成
        output = Output(cfg, source=source)
        acc = ToolCallAccumulator()
        got_content = False
        try:
            stream = self.core.reply_llm.chat_stream(
                messages, tools=tools, tool_choice="auto", options=options)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    got_content = True
                    output.process_chunk(delta.content, traceid)
                if getattr(delta, "tool_calls", None):
                    acc.add(delta.tool_calls)
        except Exception:
            self.log.exception("[导演] 流式生成异常")

        payload = acc.payload() if acc.has_calls() else []
        step_args, other_calls = self._split_calls(payload)

        # 8) 只调了工具、没正文 → 去掉全部工具重生成一次
        if not got_content and step_args is not None:
            self.log.info("[导演] 只回了 director_step，没有正文，去工具重生成")
            output = Output(cfg, source=source)
            retry_messages = [dict(m) for m in messages]
            if retry_messages and retry_messages[0].get("role") == "system":
                retry_messages[0]["content"] += (
                    "\n\n# 这次只说话\n只输出你要说的那句话，不要调用任何工具。")
            try:
                stream = self.core.reply_llm.chat_stream(retry_messages, options=options)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if getattr(delta, "content", None):
                        got_content = True
                        output.process_chunk(delta.content, traceid)
            except Exception:
                self.log.exception("[导演] 重生成异常")

        # 9) 结束流式（没有正文就不 finalize，避免空 end 与分数被空文本拉低）
        final_text = output.finalize(traceid) if got_content else ""
        if not final_text.strip():
            self.log.warning("[导演] 本次没有可用正文，不写记忆")
            if is_reply:
                self.ltmem.clear_memory_context()
            return ""

        # 10) 助手侧记忆（必须先写：apply_step 若判 clear，退出事件会立即归档副本记忆）
        try:
            self.builder.add_assistant_message(uid or "", final_text, ai_name)
        except Exception:
            self.log.exception("[导演] 记录短期记忆失败")
        try:
            if is_reply:
                self.ltmem.record_ai_message(uid, ai_name, final_text)
            else:
                self.ltmem.record_ltmem_only(ai_name, final_text)
        except Exception:
            self.log.exception("[导演] 记录长期记忆失败")

        # 11) 推进计划（完成打标 / 下一步 / clear），再分发其它工具
        if step_args is not None:
            try:
                self.core.apply_step(step_args)
            except Exception:
                self.log.exception("[导演] 应用 director_step 失败，保持原状")
        else:
            try:
                self.core.note_no_step()
            except Exception:
                self.log.exception("[导演] 失步计数异常")
        if other_calls:
            try:
                self.toolbox.handle_tool_calls(other_calls, uid, user_text)
            except Exception:
                self.log.exception("[导演] 工具分发异常")

        # 12) δ-mem 追加（仅用户回合）
        if is_reply:
            try:
                from func.catbrain.UserMemory.identity.dmem_bridge import DmemBridge
                DmemBridge().remember(uid, user_text, final_text)
            except Exception:
                self.log.exception("[导演] δ-mem 记忆追加失败")
            self.ltmem.clear_memory_context()

        # 13) 后置：情绪更新（异步）+ 计时通知
        threading.Thread(target=self._update_emotion_async,
                         args=(user_text or "（他还没说话，是你主动开口）", final_text),
                         daemon=True).start()
        LLMTimerBridge().notify_ai_reply(source="llm")
        self.core.note_utterance()
        self.log.info(f"[{traceid}][导演·{kind}]{final_text}")
        return final_text

    # ==================== 提示词 ====================
    def _system_prompt(self, kind: str, uid, user_text: str) -> str:
        bridge = SystemPromptBridge()
        if kind == "reply" or (kind == "start_bored" and uid):
            message = user_text or self._last_user_text()
            return bridge.get_system_prompt(uid, message, mark_first=False)
        cold = int(AutoActiveConfig().cold_time or 90)
        topic = str((self.core.current_plan().get("material") or {}).get("topic") or "")
        return bridge.get_active_prompt(cold, "", topic_override=topic)

    def _turn_hint(self, kind: str, user_text: str) -> str:
        if kind == "reply":
            return ("# 这一轮只做这些\n"
                    f"他刚说的是「{user_text}」。只看导演块里的[>]这一步，别把后面几步说完；"
                    "这一步说出口就算完成；如果这一步要讲由头，就说具体那一处（画面/台词），别空着。"
                    "说完必须调用 director_step 交回进度。")
        if kind == "idle_disappointed":
            return ("# 这一轮只做这些\n"
                    "他一直没回你。你有点失望（别抱怨、别卑微），把[>]这一步换个钩子再试一次；"
                    "要改这一步的做法就填 adjust，别把刚才的话重讲一遍。"
                    "说完必须调用 director_step 交回进度。")
        if kind == "rewrite":
            return ("# 这一轮只做这些\n"
                    "这条路走不通了，按新的走向重新开口，只走第一歩，别说后面；"
                    "说完必须调用 director_step 交回进度。")
        return ("# 这一轮只做这些\n"
                "现在由你先开口。只看导演块里的[>]这一步，一次只走一步，别说后面几步；"
                "说完必须调用 director_step 交回进度。")

    def _last_user_text(self) -> str:
        try:
            for m in reversed(self.short_memory.load_by_type(("llm_fast_response",))):
                if m.get("role") == "user":
                    return str(m.get("content") or "")
        except Exception:
            pass
        return ""

    # ==================== 工具结果拆分 ====================
    @staticmethod
    def _split_calls(payload):
        """拆出 director_step 与其它工具调用"""
        step_args = None
        other = []
        for call in payload or []:
            fn = (call.get("function") or {}) if isinstance(call, dict) else {}
            name = str(fn.get("name") or "")
            if name == STEP_TOOL_NAME:
                try:
                    args = json.loads(fn.get("arguments") or "{}", strict=False)
                except Exception:
                    args = None
                if isinstance(args, dict):
                    step_args = args
                continue
            other.append(call)
        return step_args, other

    # ==================== 情绪 / 静默 ====================
    def _update_emotion_async(self, prompt: str, reply_text: str):
        """后置情绪更新（复制主链路实现，端口用导演自己的）"""
        try:
            controller = EmotionController()
            tools = controller.build_tools()
            tool_choice = controller.build_tool_choice()
            update_messages = [
                {"role": "system", "content": "根据本轮对话，判断角色当前情绪、强度与性格。"},
                {"role": "user", "content": f"用户说：{prompt}\n角色回复：{reply_text}"},
            ]
            stream = self.core.reply_llm.chat_stream(
                update_messages, tools=tools, tool_choice=tool_choice,
                options={"enable_thinking": False})
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    controller.handle_stream_tool_calls(delta.tool_calls)
            if controller.tool_calls:
                controller.finalize()
        except Exception:
            self.log.exception("[导演] 后置情绪更新异常")

    @staticmethod
    def _muted() -> bool:
        try:
            from func.pipeline.silence_state import SilenceState
            return bool(SilenceState().muted)
        except Exception:
            return False
