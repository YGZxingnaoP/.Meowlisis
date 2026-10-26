import queue
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class CWCatPawsVoicePort:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.RLock()
        self._console = False
        self._auto_confirm = False
        self._queue = None

    def bind_console(self, on=True, auto_confirm=False):
        self._console = bool(on)
        self._auto_confirm = bool(auto_confirm)

    def waiting(self):
        with self._lock:
            return self._queue is not None

    def route_console(self, text):
        body = str(text or "").strip()
        if not body:
            return False
        with self._lock:
            queue_obj = self._queue
        if queue_obj is None:
            return False
        queue_obj.put(body)
        return True

    def ask(self, question, meowid="", timeout=None, options=None):
        text = str(question or "").strip()
        if not text:
            return ""
        choices = [str(item) for item in (options or []) if str(item)]
        if self._console:
            return self._ask_console(text, meowid, timeout, choices)
        try:
            from func.toolbox.excuse import TBExcuse
            answer = TBExcuse().ask(text, meowid=meowid, timeout=timeout)
        except Exception:
            self.log.exception("[CatPaws] 询问用户失败")
            return ""
        return str(answer or "").strip()

    def _ask_console(self, question, meowid, timeout, options):
        if self._auto_confirm and "继续" in options:
            print("\n（自动确认：%s）" % question, flush=True)
            return "继续"
        spoken = self._in_character(question, meowid, options)
        wait_for = float(timeout if timeout is not None else 120)
        queue_obj = queue.Queue()
        with self._lock:
            self._queue = queue_obj
        print("\n%s> %s" % (self._ai_name(), spoken), flush=True)
        if options:
            print("（参考选项：%s —— 也可以直接说你的要求；q = 不回答）"
                  % " / ".join(options), flush=True)
        else:
            print("（直接打字回答；q = 不回答）", flush=True)
        try:
            answer = str(queue_obj.get(timeout=wait_for)).strip()
        except queue.Empty:
            answer = ""
        finally:
            with self._lock:
                self._queue = None
        if answer in ("q", "Q", "quit", "退出"):
            return ""
        return answer

    @staticmethod
    def _ai_name():
        try:
            from func.config.app_config import AppConfig
            return AppConfig().ai_name or "AI"
        except Exception:
            return "AI"

    def _in_character(self, question, meowid="", options=None):
        choices = [str(item) for item in (options or []) if str(item)]
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            system_prompt = TBoxGetPrompt().get_system_prompt(meowid, question) or ""
            if choices:
                ask = ("你现在要向主人确认一件事，内部需求是：%s\n"
                       "请用你自己的角色口吻、自然口语化地问出来，不要解释技术细节；"
                       "要让主人知道回「%s」其中之一。" % (question, "」「".join(choices)))
            else:
                ask = ("你现在要向主人问一个信息，内部需求是：%s\n"
                       "请用你自己的角色口吻、自然口语化地问出来，不要解释技术细节，"
                       "问清楚你想知道的就行。" % question)
            llm = self._llm()
            if llm is not None and llm.client:
                resp = llm.chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": ask},
                ])
                if resp and resp.choices:
                    content = (resp.choices[0].message.content or "").strip()
                    if content:
                        return content
        except Exception:
            self.log.exception("[CatPaws] 角色化提问失败")
        return question

    @staticmethod
    def _llm():
        from func.toolbox.config import TBoxConfig
        conf = TBoxConfig()
        if conf.llm_type == "meowllm":
            from func.toolbox.port.meowllm import TBoxMeowLLM
            return TBoxMeowLLM(conf)
        if conf.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(conf)
        if conf.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(conf)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(conf)
