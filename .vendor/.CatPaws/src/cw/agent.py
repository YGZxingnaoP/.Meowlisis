import json
import threading

from cw.guard import CWGuardError
from cw.llm_client import CWLLMClient, CWLLMError
from cw.protocol import CWProtocolError

CW_SYSTEM_PROMPT = (
    "你在用工具直接操作这台 iPhone，替主人把事办完。\n"
    "· 动手前先看一眼屏幕，坐标一律是截图像素。\n"
    "· 一步能做完就别拆；已知路径用序列一次下发。\n"
    "· 每个动作之后再看一眼，确认界面真的变了。\n"
    "· 滑动用方向和比例，不要手写起止点。\n"
    "· 打不了中文时：点输入框让键盘出现，用 cw_keys 逐字打拼音，再在候选里挑。\n"
    "· 不确定或需要内容，就问主人。\n"
    "· 有登记过且界面对得上的 action 就直接用。\n"
    "· 收尾回桌面。\n"
    "· 汇报只讲事实：做了什么、成没成、卡在哪；不要客套，不要复述规则。\n"
    "· 最后一行只输出 RESULT: OK 或 RESULT: FAIL <原因>。\n"
    "· 看不清就看图。"
)

CW_REFLECT_PROMPT = (
    "你是喵呜的手机操作复盘助手。刚结束一次手机操作，请判断这套流程是否值得沉淀成可复用的 action。\n"
    "规则：\n"
    "1. 只有步骤固定、界面稳定、以后还会重复的流程才值得沉淀（例如付款、打开某应用的固定路径）。\n"
    "2. 一次性操作、坐标强依赖当前画面的操作不要沉淀。\n"
    "3. 已有 action 因界面变化失败时，用 cw_update_action 做小规模修正（不超过 60 行）。\n"
    "4. 新建用 cw_write_action：脚本里只能 import json/time/re/math/random/datetime/typing/cw_script，"
    "通过 cw_script.emit/observe/ask/log 与执行器交互，不要写文件、不要联网。\n"
    "5. 不确定就问 cw_ask_user；没什么值得沉淀就什么都不调用，直接结束。"
)


class CWAgent:
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
        self.operator.confirmer = self._confirm

    def busy(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, goal):
        with self._lock:
            if self.busy():
                return False
            self.operator.clear_stop()
            self._final = ""
            self._thread = threading.Thread(target=self._run, args=(goal,),
                                            name="cw-agent", daemon=True)
            self._thread.start()
            return True

    def stop(self, reason="user"):
        self.operator.stop(reason)
        self.journal.record("stop", reason=reason)

    def last_final(self):
        return self._final

    def last_concluded(self):
        return self._concluded

    def _confirm(self, question):
        answer = self.session.ask(question, ["继续", "取消"])
        return str(answer).strip() in ("继续", "确定", "是", "yes", "ok", "OK")

    def _ask(self, question, options=None):
        return self.session.ask(question, options)

    def _run(self, goal):
        self._concluded = False
        self._exhausted = False
        self._empty_nudges = 0
        self.session.begin(goal)
        self.operator.guard.begin_session()
        system_prompt = CW_SYSTEM_PROMPT
        if self.apps is not None:
            block = self.apps.prompt_block()
            if block:
                system_prompt = "%s\n%s" % (system_prompt, block)
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": str(goal)}]
        transcript = []
        reason = ""
        try:
            self._loop(messages, "running", self.config.agent_max_rounds, transcript)
            if self.operator.stopping():
                reason = self.session.finish_reason or "stopped"
            elif self._exhausted:
                self._final = self._summarize(messages)
                reason = "max_rounds"
            elif self.config.reflect_enabled and self._worth_reflecting(transcript):
                self.session.set_phase("reflecting")
                self._reflect(transcript)
                reason = "done"
            else:
                reason = "done"
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
            self.session.finish(reason)
            self.operator.clear_stop()

    def _exit_home(self):
        if not self.config.exit_to_home:
            return
        if self.operator.stopping():
            return
        try:
            self.operator.single({"action": "press_key", "key": "home"})
        except Exception:
            pass

    def _worth_reflecting(self, transcript):
        for role, text in transcript:
            if role in ("completed", "cw_single", "cw_sequence", "cw_action"):
                return True
        return bool(transcript)

    def _loop(self, messages, phase, max_rounds, transcript):
        limit = int(max_rounds)
        index = 0
        while True:
            if limit > 0 and index >= limit:
                if phase == "running":
                    self._exhausted = True
                return messages
            index += 1
            if self.operator.stopping():
                return messages
            for text in self.session.take_instructions():
                messages.append({"role": "user", "content": "主人的补充指令：%s" % text})
                self.journal.record("instruction_applied", text=text[:200])
            self.operator.guard.check_session_window()
            try:
                message = self.llm.chat(messages, tools=self.tools.schemas(phase))
            except CWLLMError:
                raise
            content = str(message.content or "")
            calls = list(getattr(message, "tool_calls", None) or [])
            assistant = {"role": "assistant", "content": content}
            if calls:
                assistant["tool_calls"] = [
                    {"id": call.id, "type": "function",
                     "function": {"name": call.function.name,
                                  "arguments": call.function.arguments or "{}"}}
                    for call in calls
                ]
            messages.append(assistant)
            if content:
                self.journal.record("assistant", phase=phase, text=content[:1200])
                transcript.append(("assistant", content))
            if not calls:
                if content.strip():
                    if phase == "running":
                        self._final = content
                        self._concluded = True
                    return messages
                self._empty_nudges += 1
                if self._empty_nudges > 3:
                    return messages
                messages.append({"role": "user", "content":
                                 "（你上一条回复是空的）继续；要收尾就直接给结论和 RESULT 行。"})
                continue
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
                if result.get("image"):
                    messages.append({"role": "user", "content": [
                        CWLLMClient.text_part("这是当前屏幕截图。"),
                        CWLLMClient.image_part(result["image"]),
                    ]})
        return messages

    def _summarize(self, messages):
        try:
            extra = list(messages) + [{
                "role": "user",
                "content": ("轮次已用尽。不要再调用工具，用一两句话说明做到哪一步、卡在哪里，"
                            "最后一行输出 RESULT: OK 或 RESULT: FAIL <原因>。"),
            }]
            message = self.llm.chat(extra, tools=None)
            return str(getattr(message, "content", "") or "")
        except Exception as exc:
            self.journal.record("error", message="总结失败：%s" % exc)
            return ""

    def _reflect(self, transcript):
        recent = transcript[-60:]
        lines = []
        for role, text in recent:
            lines.append("[%s] %s" % (role, str(text)[:400]))
        actions = []
        for item in self.store.list():
            actions.append({"id": item.get("id"), "title": item.get("title"),
                            "scene": item.get("scene"), "status": item.get("status"),
                            "updatable": item.get("updatable")})
        prompt = ("已登记 action：\n%s\n\n本次操作记录：\n%s\n\n"
                  "需要沉淀就调用 cw_write_action；需要修正就调用 cw_update_action；否则直接结束。"
                  % (json.dumps(actions, ensure_ascii=False, indent=2), "\n".join(lines)))
        messages = [{"role": "system", "content": CW_REFLECT_PROMPT},
                    {"role": "user", "content": prompt}]
        self._loop(messages, "reflecting", self.config.reflect_max_rounds, [])
