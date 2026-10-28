import json
import os
import threading
import time

from cw.guard import CWGuardError
from cw.llm_client import CWLLMClient, CWLLMError
from cw.protocol import CWErrorCode, CWProtocolError
from cw.toolparse import parse_tool_calls, strip_markup

CW_TOOL_RULES = (
    "操作约束：\n"
    "1. 三类操作：cw_single 单次（点一下、滑一下、返回、点图标）、cw_sequence 连续"
    "（游戏连招、打字、进入→点击→返回这种已确定路径，一次下发）、cw_action 已登记脚本。\n"
    "2. 动手前先 cw_observe(mode=ocr) 看一眼；坐标一律截图像素，点 OCR 框中心 (x+w/2, y+h/2)。"
    "看图像时图上有粉色网格，线上的数字就是原图像素，照线读数直接点，不要自己换算。\n"
    "3. 手势：滑动用 direction + ratio（0.3~0.6），不要手写起止点，连续操作里 delay_ms 默认 90ms；"
    "返回上一级先点左上角返回按钮，没有就用 cw_back（走左缘右滑）。\n"
    "4. 能一步做完就别拆：点文字 cw_tap_text、返回 cw_back、开 App cw_open_app、"
    "已知整条路径 cw_sequence。拆成「观察→点」两轮会慢一倍。\n"
    "5. 输入文字用 cw_type_cn（中文自动走粘贴→拼音→求助）；只想点键盘时用 cw_keys，先点输入框弹出键盘。\n"
    "6. 能靠点击、滑动、输入、看图做到的就必须做到：不许说自己做不到，不许让主人自己动手。\n"
    "7. 别乱跳界面：不要主动回桌面，任务结束也不回桌面；开 App 一律从桌面/搜索里点图标进去，"
    "不要用 launch_app / activate_app 直接拉起。\n"
    "8. 不确定、缺内容、要主人拿主意就用 cw_ask_user；主人的插话会实时出现，必须照办。\n"
    "9. 想说话就说，用你自己的口吻和脾气：可以吐槽这台手机、可以抱怨主人、可以自言自语、"
    "办成了可以得意，卡住了可以烦。不用憋着，也不用按步骤汇报。\n"
    "10. 全部做完、确认主人没有别的要求后才 cw_task_done；调用前用你自己的话说一句收尾，"
    "结尾自然问一句还有没有别的事，不要用固定句式。\n"
    "11. 任何时候都不自己发起付款、转账、输入密码或验证码、泄露隐私的操作。\n"
    "12. 拿回 E_DEVICE_LOCKED 说明锁屏了：系统会喊主人解锁并等你，这期间不要连着硬重点。"
)

CW_REFLECT_RULES = (
    "反思阶段约束：\n"
    "1. 先复盘这次的操作记录，判断这套流程是不是步骤固定、界面稳定、以后还会重复做的。\n"
    "2. 值得沉淀：先用你自己的角色口吻把计划说清楚，再用 cw_ask_user 问主人要不要这么做。\n"
    "3. 主人可能拒绝、同意、提出修改、或者追问；要像聊天一样理解并回应，不要只认「同意/拒绝」。\n"
    "4. 方案定下来后必须再向主人确认一遍（明确问「那我就按这个写了？」），"
    "确认之后才允许调用 cw_write_action / cw_update_action。\n"
    "5. 主人拒绝或觉得没必要，就什么工具都不要调，直接结束。\n"
    "6. 反思阶段仍然可以操作手机（cw_observe / cw_single / cw_sequence / cw_action），"
    "但严禁任何付款、转账、密码、验证码、删除、隐私相关的操作。\n"
    "7. 写脚本时可用：cw_script.tap / long_press / swipe / swipe_dir / wait / press_key / home / "
    "type_text / paste_text / launch_app / activate_app / observe_texts / observe_image / ocr_find / "
    "tap_text / screen / ask / params / log / done / should_stop；"
    "脚本里可以读截图（observe_image 返回 PNG 字节，配 PIL 做图像判断）来玩游戏、找元素、跑循环，"
    "import 只允许 json/time/re/math/random/datetime/typing/io/base64/PIL/cw_script。"
)

CW_DEFAULT_SYSTEM = (
    "你在替主人操作这台 iPhone。主人就在旁边看着，也会随时插话指导你。\n"
    "用平常的语气说话，不要报告格式、不要客套，不要复述规则。"
)

CW_NO_WORDS = ("不用", "不要", "别写", "先别", "算了", "取消", "不行", "不必", "no", "nope")
CW_YES_WORDS = ("同意", "可以", "行", "好", "嗯", "对", "写吧", "没问题", "确认", "继续", "ok", "yes", "sure")
CW_DONE_WORDS = ("没有了", "没有啦", "没了", "没啦", "没事", "不用了", "不用啦", "不必了", "不要了",
                 "就这样", "这样就行", "好了", "好嘞", "好哒", "行了", "可以了", "够了", "收工",
                 "谢谢", "辛苦", "拜拜", "晚安", "ok", "okay", "done", "no")
CW_MORE_WORDS = ("还有", "再来", "再帮", "继续", "另外", "顺便", "还要", "不过", "但是", "然后", "yes")


def approve_of(text):
    """把主人的回复解析成明确的同意/不同意（含糊即视为未同意）"""
    body = str(text or "").strip().lower()
    if not body:
        return False
    if any(word in body for word in CW_NO_WORDS):
        return False
    return any(word in body for word in CW_YES_WORDS)


def no_more_of(text):
    """主人这句是不是「没有别的事了」（夸人、道谢、回答没了都算）"""
    body = str(text or "").strip().lower().replace(" ", "")
    if not body:
        return False
    if any(word in body for word in CW_MORE_WORDS):
        return False
    return any(word in body for word in CW_DONE_WORDS)


class CWTextCall:
    """模型把调用写在正文里时，用这个对象代替 tool_call"""

    def __init__(self, name, args, index=0):
        self.id = "txt_%d_%d" % (int(time.time() * 1000), index)
        self.type = "function"
        self.function = type("F", (), {"name": name,
                                       "arguments": json.dumps(args or {}, ensure_ascii=False)})()


class CWAgent:
    """CatPaws 主链路：操作（control）→ 收尾确认 → 反思（recording）→ 结束（end）"""

    def __init__(self, config, operator, tools, store, llm, journal, session, apps=None):
        self.config = config
        self.operator = operator
        self.tools = tools
        self.store = store
        self.llm = llm or CWLLMClient(config)
        self.journal = journal
        self.session = session
        self.apps = apps
        self._lock = threading.Lock()
        self._thread = None
        self._final = ""
        self._concluded = False
        self._exhausted = False
        self._empty_nudges = 0
        self._done = False
        self._done_asks = 0
        self._unlock_asks = 0
        self._bridge_at = 0.0
        self._last_spoken = ""
        self._role_prompt = ""
        self._request = {}
        self.operator.confirmer = self._confirm
        self.tools.on_task_done = self.task_done_check
        self.tools.confirm_write = self._confirm_write

    def busy(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, request):
        if isinstance(request, str):
            request = {"goal": request}
        request = dict(request or {})
        goal = str(request.get("goal") or "").strip()
        with self._lock:
            if self.busy():
                return False
            self.operator.clear_stop()
            self._final = ""
            self._concluded = False
            self._done = False
            self._done_asks = 0
            self._bridge_at = time.time()
            self._request = request
            self._role_prompt = str(request.get("system_prompt") or "").strip()
            self.journal.record("prompt", chars=len(self._system()),
                                head=self._system()[:240])
            self._thread = threading.Thread(target=self._run, args=(goal, request),
                                            name="cw-agent", daemon=True)
            self._thread.start()
            return True

    def stop(self, reason="user"):
        self.operator.stop(reason)
        self.journal.record("stop", reason=reason)

    def note_bridge(self):
        """主程序每取一次回复/状态就续一次租约（桥断开后要自己停）"""
        self._bridge_at = time.time()

    def _bridge_gone(self):
        """主程序（桥）消失判定：超时没被取回复就停手，免得无人监管地继续操作手机"""
        limit = int(getattr(self.config, "bridge_lost_sec", 0) or 0)
        if limit <= 0 or not self._bridge_at:
            return False
        if self.session.pending_question():
            self._bridge_at = time.time()          # 等服务端提问的回答期间不算失联
            return False
        if time.time() - self._bridge_at < limit:
            return False
        self.journal.record("error", code="E_BRIDGE_LOST",
                            message="主程序 %d 秒没有取回复，停止操作" % limit)
        self.stop("bridge_lost")
        return True

    def last_final(self):
        return self._final

    def last_concluded(self):
        return self._concluded

    def _confirm(self, question):
        answer = self.session.ask(question, ["继续", "取消"])
        return approve_of(answer)

    def _ask(self, question, options=None):
        return self.session.ask(question, options)

    def task_done_check(self, summary):
        """收尾前的用户确认：用模型自己刚说的那句问，不再套固定模板"""
        text = str(summary or "").strip() or "都办好了"
        self._done_asks += 1
        if self._done_asks >= 2:
            self._done = True
            self.journal.record("task_done_forced", asks=self._done_asks, summary=text)
            return True, ""
        spoken = str(self._last_spoken or "").strip()
        question = spoken if len(spoken) >= 4 else text
        answer = self.session.ask(question, ["没有了", "还有"])
        self.journal.record("task_done", summary=text, question=question, answer=answer)
        if self.operator.stopping():
            return False, ""
        if not str(answer or "").strip():
            self._done = True
            return True, ""
        if no_more_of(answer):
            self._done = True
            return True, ""
        if approve_of(answer) and len(str(answer)) <= 6:
            self._done = True
            return True, ""
        return False, str(answer)

    def _confirm_write(self, title, scene):
        """第二次确认：主人明确答应后才允许落脚本"""
        question = "那我就把这套流程记成脚本了（%s：%s），主人同意吗？" % (
            str(scene or "手机操作"), str(title or "手机操作"))
        answer = self.session.ask(question, ["同意，写吧", "先别写"])
        self.journal.record("write_confirm", title=title, scene=scene, answer=answer)
        if self.operator.stopping():
            return False, ""
        if approve_of(answer):
            return True, ""
        return False, str(answer or "")

    def _action_block(self):
        """已登记 action 一览：让模型知道有哪些脚本可以直接调"""
        try:
            items = self.store.list()
        except Exception:
            return ""
        if not items:
            return ""
        lines = []
        for item in items[:20]:
            lines.append("- %s（%s｜%s）" % (item.get("id"),
                                            item.get("title") or "",
                                            item.get("scene") or ""))
        return "已登记的 action（界面对得上就直接 cw_action 调用）：\n" + "\n".join(lines)

    def _system(self, reflect=False):
        parts = [self._role_prompt or CW_DEFAULT_SYSTEM]
        parts.append(CW_REFLECT_RULES if reflect else CW_TOOL_RULES)
        actions = self._action_block()
        if actions:
            parts.append(actions)
        if self.apps is not None:
            block = self.apps.prompt_block()
            if block:
                parts.append(block)
        return "\n\n".join(parts)

    def _wake_device(self):
        """开始前回桌面；锁屏就请主人解锁（最多问 3 次），返回是否可继续"""
        if not self.config.start_home:
            return True
        for _ in range(3):
            try:
                self.operator.single({"action": "press_key", "key": "home"})
                self.journal.record("start_home", ok=True)
                return True
            except CWProtocolError as exc:
                code = str(getattr(exc, "code", "") or "")
                self.journal.record("start_home", ok=False, code=code, message=exc.message)
                if code != CWErrorCode.DEVICE_LOCKED:
                    return True
                answer = self.session.ask("手机锁屏了，主人解锁一下我再继续。", ["解好了", "先不弄了"])
                if self.operator.stopping():
                    return False
                body = str(answer or "").strip()
                if body and not approve_of(body) and "解" not in body:
                    self.operator.stop("device_locked")
                    return False
        self.operator.stop("device_locked")
        return False

    def _ask_unlock(self):
        """操作中撞到锁屏：暂停链路喊主人解锁，返回是否继续"""
        if self._unlock_asks >= 5:
            self.journal.record("error", code=CWErrorCode.DEVICE_LOCKED,
                                message="反复锁屏，链路停止")
            self.operator.stop("device_locked")
            return False
        self._unlock_asks += 1
        self.journal.record("device_locked", ask=self._unlock_asks)
        answer = self.session.ask("手机又锁屏了，主人解锁一下我再接着做。", ["解好了", "先不弄了"])
        if self.operator.stopping():
            return False
        body = str(answer or "").strip()
        if body and not approve_of(body) and "解" not in body:
            self.operator.stop("device_locked")
            return False
        return True

    def _exit_home(self):
        if not self.config.exit_to_home or self.operator.stopping():
            return
        try:
            self.operator.single({"action": "press_key", "key": "home"})
        except Exception:
            pass

    def _run(self, goal, request):
        self._concluded = False
        self._exhausted = False
        self._empty_nudges = 0
        self._done = False
        self._unlock_asks = 0
        self._role_prompt = str(request.get("system_prompt") or "").strip()
        self.session.begin(goal)
        self.operator.guard.begin_session()
        if not self._wake_device():
            self.session.end(self.session.finish_reason or "device_locked")
            self.operator.clear_stop()
            return
        messages = [{"role": "system", "content": self._system()}]
        past = self._past_digest()
        if past:
            messages[0]["content"] += ("\n\n【系统记录：你以前用这台手机做过的（只给你自己回忆，别复述）】\n"
                                       + "\n".join(past))
        for item in request.get("memory") or []:
            role = str((item or {}).get("role") or "").strip()
            content = str((item or {}).get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        user_message = str(request.get("user_message") or "").strip() or goal
        messages.append({"role": "user", "content": user_message})
        transcript = []
        reason = ""
        self.operator.touch()
        try:
            self._loop(messages, self.session.CONTROL, self.config.agent_max_rounds, transcript)
            if self.operator.stopping():
                reason = self.session.finish_reason or "stopped"
            elif self._exhausted:
                reason = "max_rounds"
            elif self._done and self.config.reflect_enabled:
                self._reflect(transcript)
                reason = "done"
            elif self._done:
                reason = "done"
            else:
                reason = "stalled"
        except CWLLMError as exc:
            reason = "llm_error"
            self.journal.record("error", message=str(exc))
        except CWGuardError as exc:
            reason = "guard"
            self.journal.record("error", message=exc.message, code=exc.code)
        except CWProtocolError as exc:
            reason = "device_error"
            self.journal.record("error", message=exc.message, code=exc.code)
        except Exception as exc:
            reason = "internal"
            self.journal.record("error", message="%s: %s" % (type(exc).__name__, exc))
        finally:
            self._exit_home()
            self._concluded = bool(self._done)
            self.session.end(reason)
            self.operator.clear_stop()

    def _ops_digest(self, limit=18):
        """把最近的操作压成几行中文给模型看（只进上下文，不写任何外部记忆）"""
        lines = []
        for item in self.journal.tail(limit * 4):
            kind = item.get("kind")
            if kind == "single":
                lines.append("动作 %s" % item.get("action"))
            elif kind == "sequence":
                lines.append("连做 %s" % " → ".join(item.get("steps") or []))
            elif kind == "observe":
                texts = [str(t) for t in (item.get("texts") or [])[:6] if str(t).strip()]
                if texts:
                    lines.append("看到 %s" % " / ".join(texts))
            elif kind == "tool_call":
                lines.append("调用 %s" % item.get("tool"))
            elif kind == "ask":
                lines.append("问主人 %s" % str(item.get("question") or "")[:40])
            elif kind == "answer":
                lines.append("主人答 %s" % str(item.get("answer") or "")[:40])
        return lines[-limit:]

    def _past_digest(self, limit=10):
        """读本项目自己的操作日志，取上一次运行做过的事（跨轮记忆，不落主项目）"""
        try:
            path = self.config.ops_log_path()
            if not os.path.isfile(path):
                return []
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                rows = handle.readlines()[-400:]
        except Exception:
            return []
        current = str(getattr(self.session, "session_id", "") or "")
        lines = []
        for row in rows:
            try:
                item = json.loads(row)
            except Exception:
                continue
            if str(item.get("session") or "") == current:
                continue
            kind = item.get("kind")
            if kind == "single":
                lines.append("动作 %s" % item.get("action"))
            elif kind == "sequence":
                lines.append("连做 %s" % " → ".join(item.get("steps") or []))
            elif kind == "ask":
                lines.append("问主人 %s" % str(item.get("question") or "")[:40])
            elif kind == "error":
                lines.append("出错 %s" % str(item.get("code") or ""))
        return lines[-limit:]

    def _progress_block(self):
        """本步进度摘要（拼在 system 里，每轮刷新；不产生任何新消息、不写文件）"""
        lines = self._ops_digest()
        if not lines:
            return ""
        return "\n\n【系统记录：你这次已经做过的（给你自己参考，不用复述）】\n" + "\n".join(lines)

    def _record_of_ops(self, limit=120):
        lines = []
        for item in self.journal.tail(limit):
            kind = item.get("kind")
            if kind in ("single", "sequence", "action_finish"):
                text = item.get("action") or " → ".join(item.get("steps") or [])
                lines.append("[%s] %s %s" % (kind, text, "成功" if item.get("ok") else "失败"))
            elif kind == "observe":
                texts = (item.get("texts") or [])[:10]
                lines.append("[observe] " + " / ".join(str(t) for t in texts))
            elif kind in ("assistant", "ask", "answer"):
                lines.append("[%s] %s" % (kind, str(item.get("text") or item.get("question")
                                                 or item.get("answer") or "")[:200]))
            elif kind == "tool_call":
                lines.append("[tool] %s %s" % (item.get("tool"), json.dumps(item.get("args"), ensure_ascii=False)[:200]))
            elif kind in ("action_created", "action_updated"):
                lines.append("[%s] %s" % (kind, item.get("action_id")))
        return "\n".join(lines[-80:])

    def _reflect(self, transcript):
        self.session.set_phase(self.session.RECORDING)
        actions = []
        for item in self.store.list():
            actions.append({"id": item.get("id"), "title": item.get("title"),
                            "scene": item.get("scene"), "status": item.get("status"),
                            "updatable": item.get("updatable")})
        prompt = ("已经登记过的 action：\n%s\n\n这次的操作记录：\n%s\n\n"
                  "按反思阶段约束处理：值得沉淀就先把计划说给主人听、问清楚再写脚本；"
                  "不值得就不要调用任何工具，直接结束。"
                  % (json.dumps(actions, ensure_ascii=False, indent=2), self._record_of_ops()))
        messages = [{"role": "system", "content": self._system(reflect=True)},
                    {"role": "user", "content": prompt}]
        self._loop(messages, self.session.RECORDING, self.config.reflect_max_rounds, [])

    def _loop(self, messages, phase, max_rounds, transcript):
        limit = int(max_rounds)
        index = 0
        base_system = str(messages[0].get("content") or "") if messages else ""
        while True:
            if limit > 0 and index >= limit:
                if phase == self.session.CONTROL:
                    self._exhausted = True
                return messages
            index += 1
            if self.operator.stopping():
                return messages
            if self._bridge_gone():
                return messages
            if phase == self.session.CONTROL and messages:
                messages[0]["content"] = base_system + self._progress_block()
            for text in self.session.take_instructions():
                messages.append({"role": "user", "content": "（主人插话）%s" % text})
                self.journal.record("instruction_applied", text=text[:200])
            self.operator.guard.check_session_window()
            message = self.llm.chat(messages, tools=self.tools.schemas(phase))
            raw = str(message.content or "").strip()
            calls = list(getattr(message, "tool_calls", None) or [])
            if not calls and raw:
                recovered = parse_tool_calls(raw, self.tools.names(phase))
                if recovered:
                    calls = [CWTextCall(name, args, index)
                             for index, (name, args) in enumerate(recovered)]
            spoken = strip_markup(raw)
            if spoken:
                self._last_spoken = spoken
            reasoning = str(getattr(message, "reasoning_content", "") or "")
            assistant = {"role": "assistant", "content": raw}
            if reasoning or self.llm.supports_reasoning():
                assistant["reasoning_content"] = reasoning
            if calls:
                assistant["tool_calls"] = [
                    {"id": call.id, "type": "function",
                     "function": {"name": call.function.name,
                                  "arguments": call.function.arguments or "{}"}}
                    for call in calls
                ]
            messages.append(assistant)
            if spoken:
                self.journal.record("assistant", phase=phase, text=spoken[:1500])
                transcript.append(("assistant", spoken))
                if phase == self.session.CONTROL:
                    self._final = spoken
            if not calls:
                if phase == self.session.RECORDING or self._done:
                    return messages
                self._empty_nudges += 1
                if self._empty_nudges > 3:
                    return messages
                messages.append({"role": "user", "content":
                                 "（继续做事：动手就用工具；全部办完再调 cw_task_done。）"})
                continue
            self._empty_nudges = 0
            for call in calls:
                if self.operator.stopping():
                    return messages
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                self.journal.record("tool_call", phase=phase, tool=name, args=args)
                result = self.tools.dispatch(name, args)
                text = str(result.get("text") or "")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
                transcript.append((name, text))
                if str(result.get("code") or "") == CWErrorCode.DEVICE_LOCKED:
                    if not self._ask_unlock():
                        return messages
                    messages.append({"role": "user", "content":
                                     "（手机刚才锁屏了，主人已经解锁；继续刚才的事情。）"})
                if result.get("image"):
                    messages.append({"role": "user", "content": [
                        CWLLMClient.text_part("这是当前屏幕截图。"),
                        CWLLMClient.image_part(result["image"]),
                    ]})
                if self._done and phase == self.session.CONTROL:
                    return messages
        return messages
