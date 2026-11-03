# -*- coding: utf-8 -*-
# func/catpaws/say.py
# 手机操作中的发言出口：执行正文不当台词，只在这几个时刻由角色本人说一句
import re
import random
import time

from func.catpaws.config import CWCatPawsConfig
from func.catpaws.port import get_catpaws_port
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

# 每类台词的字数上限（ask 不截断：问句必须完整，否则主人不知道该答什么）
MAX_CHARS = {"ack": 16, "look": 24, "oops": 22, "done": 36, "react": 12, "ask": 40}

# 台词生成失败时的兜底（只说一句，不做固定播报）
FALLBACK = {
    "ack": ("行，我去弄。", "好，这就来。"),
    "oops": ("哎，卡了一下。", "它又抽风了。"),
    "done": ("弄完了，你看看。", "好了，还要别的吗？"),
}

REASONS = {
    "done": "办成了",
    "max_rounds": "到手头这一步就停了",
    "stalled": "卡住了没往下走",
    "timeout": "等太久停了",
    "stopped": "被叫停了",
    "device_locked": "手机锁屏了",
    "llm_error": "模型出错了",
    "guard": "被规则拦了",
    "device_error": "手机那边出错了",
    "internal": "中间出了点岔子",
    "service_down": "服务断了",
}

_BRACKETS = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")
# 收句用的终止标点 / 次级停顿标点
_ENDS = "。！？…"
_TAILS = "，、；：,;:"


def clean_line(text, max_chars=0, strip_brackets=True):
    """去掉括号旁白/引号/换行，按需截成一句口语

    max_chars=0 表示不截断。截断优先落在终止标点上，其次落在逗号类停顿上，
    并把逗号收成句号——避免播出「…还挂现金钩子，」这种半句话。
    """
    body = str(text or "")
    if strip_brackets:
        body = _BRACKETS.sub("", body)
    body = " ".join(body.replace("　", " ").split())
    body = body.strip("\"'“”‘’「」『』 ")
    if max_chars and len(body) > max_chars:
        head = body[:max_chars]
        cut = max(head.rfind(ch) for ch in _ENDS)
        if cut < max_chars // 2:
            cut = max(head.rfind(ch) for ch in _TAILS)
        body = head[:cut + 1] if cut >= 0 else head
        body = body.rstrip(_TAILS + " ")
        if body and body[-1] not in _ENDS:
            body += "。"
    body = body.strip()
    # 收句：尾巴挂着逗号/顿号等于没说完；连标点都没有也补一个句号
    if body:
        tail = body[-1]
        if tail in _TAILS:
            body = body.rstrip(_TAILS + " ") + "。"
        elif tail not in _ENDS and tail not in ".!?":
            body += "。"
    return body


@singleton
class CWCatPawsSay:
    """几个开口时刻（接活/插话/看到东西/出岔子/办完/提问）的唯一出口

    agent 的正文只当素材（feed_agent），不当台词；台词一律由角色本人按当时的事实说一句。
    """

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = config or CWCatPawsConfig()
        self.reset()

    def reset(self, goal="", username=""):
        self._goal = str(goal or "")
        self._username = str(username or "")
        self._see = ""
        self._said_see = ""
        self._act = []
        self._user = ""
        self._recent = []
        self._oops = set()
        self._lines = 0
        self._last_look = 0.0
        self._closed = False
        self._summary = ""

    # ==================== 素材 ====================
    def feed_see(self, texts):
        items = [str(t).strip() for t in (texts or []) if str(t).strip()]
        if items:
            self._see = "、".join(dict.fromkeys(items))[:80]

    def feed_act(self, item):
        name = str(item.get("action") or "") or " → ".join(item.get("steps") or [])
        if name:
            self._act.append(name[:40])
            del self._act[:-4]

    def feed_user(self, text):
        self._user = str(text or "").strip()

    def closing(self, summary="", hard=False):
        """服务端给出了 task_done：记下执行摘要；hard=True（强制结束）时不再插「招呼」"""
        body = str(summary or "").strip()
        if body:
            self._summary = body[:120]
        if hard:
            self._closed = True

    def seal(self):
        """链路已结束：此后不再有新的「招呼」（避免手机操作结束后还在慢慢补话）"""
        self._closed = True

    # ==================== 开口 ====================
    def happen(self, kind, payload=None, username=""):
        """按时刻开口；返回说出口的台词（空串=这次不说）"""
        payload = payload or {}
        self._username = str(username or self._username or "")
        if not self.config.voice_enabled and kind not in ("ack", "done"):
            return ""
        if kind in ("look", "oops") and self._closed:
            return ""
        if kind == "look":
            if not self._ready_look():
                return ""
        elif kind == "oops":
            code = str(payload.get("code") or "")
            if code and code in self._oops:
                return ""
            if code:
                self._oops.add(code)
        # 主动开口（接活/招呼/出错）计入总句数上限；办完必说，插话与提问不受限
        counting = kind in ("ack", "look", "oops")
        if counting and not self._allow_lines():
            return ""
        line = self._generate(self._need(kind, payload), self._username,
                              max_chars=MAX_CHARS.get(kind, 20))
        if not line:
            pool = FALLBACK.get(kind) or ()
            line = random.choice(pool) if pool else ""
        if not line:
            return ""
        return self._say(line, self._username,
                         max_chars=MAX_CHARS.get(kind, 20), count=counting)

    def react(self, text, username=""):
        """主人在旁边插话：先应一句（再照办）"""
        self.feed_user(text)
        if not self.config.voice_enabled:
            return ""
        line = self._generate(f"主人刚在旁边说：「{self._user}」。先应一句，再照办。",
                              self._username or username, max_chars=MAX_CHARS["react"])
        if not line:
            return ""
        return self._say(line, self._username or username,
                         max_chars=MAX_CHARS["react"], count=False)

    def ask(self, question, options=(), username=""):
        """服务端要问主人：用角色自己的话问一遍，必须保留「要答什么」

        - 不照念原生问句：那是系统口吻，不是她在说话；
        - 但也不许丢信息：提示词里强调保留要选什么/是否同意，不许砍成半句；
        - 生成失败才照念原问题（动态文本，不是写死的台词），保证主人知道要答什么。
        """
        text = str(question or "").strip()
        if not text:
            return ""
        opts = "、".join(str(o) for o in (options or ()) if str(o).strip())
        need = (f"手机操作卡在需要主人拍板的地方，要问的是：「{text}」"
                + (f"，可以答：{opts}" if opts else "")
                + "。用你自己的话问他，必须说清要他回答什么/选哪个，"
                  "别解释过程、别砍成半句。")
        line = self._generate(need, self._username or username,
                              max_chars=MAX_CHARS.get("ask", 40))
        if not line:
            line = clean_line(text, 0, strip_brackets=False)
        if not line:
            return ""
        if options:
            self.log.info("[CatPaws][ask] 提问（选项 %s）：%s"
                          % ("/".join(str(o) for o in options), text))
        return self._say(line, self._username or username, max_chars=0, count=False,
                         strip_brackets=False, dedupe=False)

    # ==================== 内部 ====================
    def _need(self, kind, payload):
        if kind == "ack":
            return (f"主人让你在手机上办「{self._goal}」，你刚接下来。"
                    "应一声，让他知道你在弄了；别报步骤。")
        if kind == "look":
            doing = f"（你刚在弄：{'、'.join(self._act[-2:])}）" if self._act else ""
            return (f"你在手机上看到这些内容：「{self._see}」{doing}。"
                    "招呼主人一起看，像你发现了什么好玩的东西；别汇报进度。")
        if kind == "oops":
            code = str(payload.get("code") or "")
            message = str(payload.get("message") or "")[:60]
            return (f"手机上这件事卡了一下（{code}{('：' + message) if message else ''}）。"
                    "轻松带过：可以自嘲、开个玩笑、怪手机；别说抱歉，也别说教。")
        reason = REASONS.get(str(payload.get("reason") or ""), "办完了")
        need = (f"主人让你办「{self._goal}」，现在结束了（{reason}）。"
                "只告诉他结果，别复盘过程；再说一句自然的收尾，问还要不要别的。")
        if self._summary:
            need += f"服务端的执行摘要（素材，别整段念）：{self._summary}。"
        return need

    def _generate(self, need, username, max_chars=20):
        """说一句：模型生成，失败重试一次，仍失败由调用方兜底"""
        for _ in range(2):
            line = self._line(need, username, max_chars)
            if line:
                return line
        self.log.warning("[CatPaws] 台词生成失败，改用兜底：%s" % need[:40])
        return ""

    def _line(self, need, username, max_chars=20):
        system = self._system_prompt(username, need)
        if not system:
            return ""
        messages = [{"role": "system", "content": system}]
        messages.extend(self._history())
        parts = [f"（这是你自己的内部提示，不是主人说的话）{need}"]
        parts.append(f"用你自己的口气说一句，不超过{max_chars}字；不报步骤、不念坐标/按钮名/工具名，"
                     "不用「正在」开头；可以吐槽、可以问回去。")
        if self._recent:
            parts.append("你最近说过：" + " / ".join(self._recent[-4:]) + "。别重复。")
        messages.append({"role": "user", "content": "\n".join(parts)})
        try:
            raw = get_catpaws_port(self.config).text(messages)
        except Exception:
            self.log.exception("[CatPaws] 台词生成失败")
            return ""
        return clean_line(raw)

    def _system_prompt(self, username, need):
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_tool_prompt(username, need) or ""
        except Exception:
            self.log.exception("[CatPaws] 读取人设提示词失败")
            return ""

    def _history(self):
        try:
            from func.pipeline.short_memory import ShortMemory
            items = ShortMemory().load()[-4:]
        except Exception:
            return []
        out = []
        for item in items:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                out.append({"role": role, "content": content})
        return out

    def _say(self, line, username, max_chars=0, count=True,
             strip_brackets=True, dedupe=True):
        body = clean_line(line, max_chars, strip_brackets=strip_brackets)
        if not body:
            return ""
        if dedupe and body in self._recent[-3:]:
            self.log.info("[CatPaws] 台词重复，跳过：%s" % body)
            return ""
        self.log.info("[CatPaws] 台词：%s" % body)
        self._speak(body)
        self._remember(username, body)
        self._recent.append(body)
        del self._recent[:-8]
        if count:
            self._lines += 1
        return body

    def _speak(self, text):
        try:
            from func.catpaws.voice import CWCatPawsVoice
            CWCatPawsVoice(self.config).speak(text)
        except Exception:
            self.log.exception("[CatPaws] 台词播报失败")

    def _remember(self, username, text):
        try:
            from func.catpaws.memory import CWCatPawsMemory
            CWCatPawsMemory(self.config).say(username, text)
        except Exception:
            self.log.exception("[CatPaws] 记录台词失败")

    # ==================== 限频 ====================
    def _ready_look(self):
        if not self._see or self._see == self._said_see:
            return False
        gap = float(getattr(self.config, "voice_look_min_gap", 20) or 0)
        if gap > 0 and time.time() - self._last_look < gap:
            return False
        self._last_look = time.time()
        self._said_see = self._see
        return True

    def _allow_lines(self):
        limit = int(getattr(self.config, "voice_max_lines", 8) or 0)
        return limit <= 0 or self._lines < limit
