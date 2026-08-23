# -*- coding: utf-8 -*-
# func/toolbox/add_backlog/add_tool.py
# Add Backlog 触发型工具入口：父级浅层触发 → 内部二次深度思考 → 追加待办 / 发起 excuse 追问
# 全程不写记忆、不播报；QQ 通道全链路走 QQ 消息，不走 pipeline TTS

import json
import re
from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.add_backlog.config import TBAddBacklogConfig
from func.toolbox.add_backlog.add_backlog import TBAddBacklog
from func.toolbox.get_prompt import TBoxGetPrompt


@singleton
class TBAddBacklogTool:
    """新建待办工具入口：父级只暴露 add_backlog 一个工具。

    - 语音/文本通道 dispatch：二次深度思考提取字段，缺 time/content 用 TBExcuse 追问一轮；
    - QQ 通道 dispatch_qq：同上，excuse 走 TBNapcatExcuseRouter 发 QQ 追问；
    - 缺省值：day=none、type=instant、loop=3、repeat_interval=300、qq=true。
    """

    TOOL_NAME = "add_backlog"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBAddBacklogConfig()
        self._username = ""

    def set_username(self, username: str):
        """注入当前用户（供 excuse 追问 / 提示词使用）"""
        self._username = username or ""

    # ==================== 工具 schema ====================
    def build_tools(self) -> List[Dict]:
        """父级暴露的新建待办工具 schema"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "新建/记录一条待办或提醒事项（写入 character/backlog）。\n"
                    "【仅在以下情况调用】用户明确要求记住某件事、提醒、新建待办、到点提醒、帮我记一下等。\n"
                    "【严格禁止调用】普通闲聊、讨论、询问观点、搜索/知识库、天气、新闻、发消息、看屏幕等一律不调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "用户的待办需求内容（尽量保留用户原话），例如：提醒我晚上10点睡觉",
                        },
                    },
                    "required": ["request"],
                },
            },
        }]

    # ==================== 语音/文本通道入口 ====================
    def dispatch(self, name: str, arguments: Dict):
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.enabled:
            return "新建待办模块未启用"

        arguments = arguments or {}
        request = (arguments.get("request") or "").strip()
        if not request:
            return "待办需求为空"
        return self._run(request, self._username, qq_context=None)

    # ==================== QQ 通道入口 ====================
    def dispatch_qq(self, name: str, arguments: Dict, qq_context: Dict):
        """QQ 场景：excuse 走 QQ 消息，结果直接写 backlog（不走 TTS、不播报）。

        返回：
        - True/False：是否写入成功；
        - ("redeliver", text)：用户另起话题，需重新投递；
        - None：静默（非待办 / 放弃 / 不通过）。
        """
        if name != self.TOOL_NAME:
            return None
        if not self.config.enabled or not self.config.qq_enabled:
            return None

        arguments = arguments or {}
        request = (arguments.get("request") or "").strip()
        if not request:
            return None
        return self._run(request, self._username, qq_context=qq_context)

    # ==================== 核心决策 ====================
    def _run(self, text: str, username: str, qq_context: Optional[Dict] = None):
        """二次深度思考 → 字段齐全落盘；缺 time/content 追问一轮后合并再提取（只一轮）"""
        decision = self._deep_think(text, username)
        if not decision.get("is_backlog"):
            return None

        content = (decision.get("content") or "").strip()
        time_str = self._norm_time(decision.get("time"))
        if content and time_str:
            return self._add(username, self._build_item(decision, content, time_str, qq_context is not None))

        # 缺 time/content → 追问一轮
        question = (decision.get("question") or "").strip() or "你想让我在什么时间提醒你做什么事呢？"
        if qq_context is not None:
            reply = self._ask_qq(question, qq_context, username)
            if isinstance(reply, tuple):
                if reply[0] == "redeliver":
                    return reply
                if reply[0] == "answer":
                    reply = reply[1]
            if not reply:
                return None
        else:
            reply = self._ask_voice(question, username)
            if not reply:
                return None
        merged = f"{text}；用户补充：{reply}"

        decision2 = self._deep_think(merged, username)
        if not decision2.get("is_backlog"):
            return None
        content2 = (decision2.get("content") or "").strip()
        time2 = self._norm_time(decision2.get("time"))
        if content2 and time2:
            return self._add(username, self._build_item(decision2, content2, time2, qq_context is not None))
        return None

    def _add(self, username: str, item: dict) -> bool:
        return TBAddBacklog().add_todo(username, item)

    def _build_item(self, decision: Dict, content: str, time_str: str, force_qq: bool) -> dict:
        day = self._norm_day(decision.get("day"))
        typ = self._norm_type(decision.get("type"))
        qq = True if force_qq else self._to_bool(decision.get("qq"), True)
        item = {
            "content": content,
            "day": day,
            "time": time_str,
            "type": typ,
            "qq": qq,
        }
        if typ == "steady":
            item["loop"] = self._to_int(decision.get("loop"), 3)
            item["repeat_interval"] = self._to_int(decision.get("repeat_interval"), 300)
        return item

    # ==================== 二次深度思考 ====================
    def _deep_think(self, text: str, username: str) -> Dict:
        """toolcalls 结构化判断：是否待办 + 提取字段 + 是否需追问"""
        llm = self._llm()
        if not llm or not llm.client:
            self.log.error("[AddBacklog] toolbox LLM 不可用")
            return {"is_backlog": False}

        system = TBoxGetPrompt().get_tool_prompt(username, text) or ""
        system = (
            f"{system}\n\n"
            f"【新建待办】请判断用户是否在新建/记录一条待办提醒，并提取结构化字段。\n"
            f"- time：提醒时刻，格式 HH:MM（24小时制），必须有；\n"
            f"- content：提醒内容，必须有；\n"
            f"- day：缺省 none（每天），或 MM-DD 指定日期；\n"
            f"- type：instant（单次提醒）或 steady（持续多次提醒），缺省 instant；\n"
            f"- loop：steady 的重复次数，缺省 3；\n"
            f"- repeat_interval：steady 的重复间隔（秒），缺省 300；\n"
            f"- qq：是否用 QQ 提醒，缺省 true；\n"
            f"- 若缺少 time 或 content，need_excuse 置 true 并生成自然的追问 question。"
        )
        tools = [{
            "type": "function",
            "function": {
                "name": "parse_backlog",
                "description": "提取待办结构化字段",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "is_backlog": {"type": "boolean"},
                        "content": {"type": "string"},
                        "time": {"type": "string"},
                        "day": {"type": "string"},
                        "type": {"type": "string"},
                        "loop": {"type": "integer"},
                        "repeat_interval": {"type": "integer"},
                        "qq": {"type": "boolean"},
                        "need_excuse": {"type": "boolean"},
                        "question": {"type": "string"},
                    },
                    "required": ["is_backlog", "content", "time", "need_excuse"],
                },
            },
        }]
        resp = llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": text}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "parse_backlog"}},
        )
        if not resp or not resp.choices:
            return {"is_backlog": False}
        msg = resp.choices[0].message
        for tc in (msg.tool_calls or []):
            if tc.function.name == "parse_backlog":
                try:
                    return json.loads(tc.function.arguments or "{}")
                except Exception:
                    self.log.exception("[AddBacklog] 解析工具参数失败")
        return {"is_backlog": False}

    # ==================== excuse 追问 ====================
    def _ask_voice(self, question: str, username: str):
        try:
            from func.toolbox.excuse import TBExcuse
            return TBExcuse().ask(question, username=username)
        except Exception:
            self.log.exception("[AddBacklog] 语音 excuse 追问失败")
            return None

    def _ask_qq(self, question: str, qq_context: Dict, username: str):
        """QQ 场景追问：发 QQ 询问 → 绑定用户等待 → 判断是否回答。

        返回：
        - ("answer", value)：用户回答了追问；
        - ("redeliver", text)：用户另起话题；
        - None：放弃/无回复。
        """
        if not question or not qq_context:
            return None
        question_text = self._in_character(question, username)
        self._send_qq(qq_context, question_text)

        from func.toolbox.napcat.excuse_router import TBNapcatExcuseRouter
        router = TBNapcatExcuseRouter()
        key = self._qq_key(qq_context)
        q = router.register(key)
        try:
            reply = q.get()
        finally:
            router.unregister(key)

        if not reply:
            return None
        return self._parse_reply(reply, question, username)

    def _parse_reply(self, reply: str, question: str, username: str):
        """判断 QQ 回复是否在回答追问（另起话题返回 redeliver）"""
        try:
            llm = self._llm()
            if not llm or not llm.client:
                return ("answer", reply.strip())
            system = TBoxGetPrompt().get_tool_prompt(username, reply) or ""
            tools = [{
                "type": "function",
                "function": {
                    "name": "parse_reply",
                    "description": "判断用户回复是否在回答追问，并提取有效信息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "is_answer": {
                                "type": "boolean",
                                "description": "是否在回答追问（false 表示另起话题、拒绝或放弃）",
                            },
                            "value": {
                                "type": "string",
                                "description": "提取的有效信息（待办时间与内容），非回答则为空",
                            },
                        },
                        "required": ["is_answer", "value"],
                    },
                },
            }]
            resp = llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": (
                        f"你刚才追问了用户：{question}\n"
                        f"用户回复：{reply}\n"
                        f"请判断用户是否在回答这个追问，并提取有效信息（待办的时间和内容）。"
                    )},
                ],
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "parse_reply"}},
            )
            if resp and resp.choices:
                msg = resp.choices[0].message
                for tc in (msg.tool_calls or []):
                    if tc.function.name == "parse_reply":
                        args = json.loads(tc.function.arguments or "{}")
                        if not args.get("is_answer"):
                            return ("redeliver", reply.strip())
                        value = str(args.get("value") or "").strip()
                        return ("answer", value or reply.strip())
        except Exception:
            self.log.exception("[AddBacklog] 判断 QQ 回复失败")
        return ("answer", reply.strip())

    def _in_character(self, question: str, username: str) -> str:
        """以角色身份生成 QQ 询问"""
        try:
            system = TBoxGetPrompt().get_system_prompt(username, question) or ""
            llm = self._llm()
            if llm and llm.client:
                resp = llm.chat([
                    {"role": "system", "content": system},
                    {"role": "user", "content": (
                        f"你现在需要向用户询问一个信息，内部需求是：{question}\n"
                        f"请以你自己的角色身份，自然、口语化地问出这个问题，"
                        f"必须是明确的问句，让用户知道要回复什么。"
                    )},
                ])
                if resp and resp.choices:
                    content = (resp.choices[0].message.content or "").strip()
                    if content:
                        return content
        except Exception:
            self.log.exception("[AddBacklog] 角色口吻生成询问失败")
        return question

    @staticmethod
    def _send_qq(qq_context: Dict, text: str):
        """发 QQ 文本（私聊或群聊）"""
        if not text:
            return
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        core = TBNapCatCore()
        if str(qq_context.get("message_type", "")) == "group":
            core.send_group_text(str(qq_context.get("target_id", "")), text)
        else:
            core.send_private_text(
                str(qq_context.get("target_id", "") or qq_context.get("user_id", "")), text
            )

    @staticmethod
    def _qq_key(qq_context: Dict) -> str:
        message_type = str(qq_context.get("message_type", "private"))
        target_id = str(qq_context.get("target_id", "") or "")
        user_id = str(qq_context.get("user_id", "") or target_id)
        from func.toolbox.napcat.excuse_router import TBNapcatExcuseRouter
        router = TBNapcatExcuseRouter()
        if message_type == "group":
            return router.group_key(target_id, user_id)
        return router.private_key(user_id)

    # ==================== 字段归一化 ====================
    @staticmethod
    def _norm_time(value) -> str:
        s = str(value or "").strip()
        m = re.match(r"^(\d{1,2})[:：](\d{2})$", s)
        if not m:
            return ""
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
        return ""

    @staticmethod
    def _norm_day(value) -> str:
        s = str(value or "").strip()
        if not s or s.lower() in ("none", "每天", "无", "每天提醒"):
            return "none"
        m = re.match(r"^(\d{1,2})-(\d{1,2})$", s)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{month:02d}-{day:02d}"
        return "none"

    @staticmethod
    def _norm_type(value) -> str:
        s = str(value or "").strip().lower()
        if s in ("steady", "持续", "多次", "循环", "重复"):
            return "steady"
        return "instant"

    @staticmethod
    def _to_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value, default=True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in ("true", "1", "yes")

    @staticmethod
    def _llm():
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
