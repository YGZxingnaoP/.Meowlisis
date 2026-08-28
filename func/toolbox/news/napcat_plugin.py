# -*- coding: utf-8 -*-
# func/toolbox/news/napcat_plugin.py
# News 的 QQ 适配层：负责 QQ 场景的 excuse（角色口吻发 QQ 询问 + 绑定用户等待 + 判断是否另起话题）
# 不负责结果回传（结果由 news_core 生成后交给 napcat 模块发 QQ，不走 pipeline TTS）

from typing import Dict, Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.get_prompt import TBoxGetPrompt


@singleton
class TBNewsNapcatPlugin:
    """News 的 QQ excuse 适配层"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def ask_count(self, qq_context: Dict, username: str = ""):
        """QQ 场景追问条数。

        返回：
        - 正整数条数（成功）；
        - ("redeliver", text) 元组（用户另起话题，需重新投递）；
        - None（放弃/无回复）。
        """
        result = self.ask_qq(
            question="你想看几条新闻？",
            qq_context=qq_context,
            username=username,
            extract_hint="新闻条数（正整数，如 3、5）",
        )
        if isinstance(result, tuple) and result and result[0] == "redeliver":
            return result
        if isinstance(result, tuple) and result and result[0] == "answer":
            reply = result[1]
        else:
            return None
        try:
            import re
            m = re.search(r"\d+", str(reply))
            if m:
                return max(1, min(int(m.group()), 10))
        except Exception:
            pass
        return None

    # ==================== 通用 QQ excuse ====================
    def ask_qq(self, question: str, qq_context: Dict, username: str = "",
               extract_hint: str = ""):
        """发 QQ 询问 → 绑定用户等待回复 → 判断回复是否有效。

        返回统一结构化结果：
        - ("answer", value)：用户回答了追问；
        - ("redeliver", text)：用户另起话题，text 为需重新投递的消息；
        - ("abort", None)：放弃/无回复。
        """
        if not question or not qq_context:
            return ("abort", None)
        question_text = self._in_character(question, username)
        self._send_qq(qq_context, question_text)

        from func.toolbox.napcat.excuse_router import TBNapcatExcuseRouter
        router = TBNapcatExcuseRouter()
        key = self._key(qq_context)
        q = router.register(key)
        try:
            reply = q.get()
        finally:
            router.unregister(key)

        if not reply:
            return ("abort", None)
        return self._decide(reply, question, username, extract_hint)

    # ==================== 内部 ====================
    @staticmethod
    def _key(qq_context: Dict) -> str:
        message_type = str(qq_context.get("message_type", "private"))
        target_id = str(qq_context.get("target_id", "") or "")
        user_id = str(qq_context.get("user_id", "") or target_id)
        from func.toolbox.napcat.excuse_router import TBNapcatExcuseRouter
        router = TBNapcatExcuseRouter()
        if message_type == "group":
            return router.group_key(target_id, user_id)
        return router.private_key(user_id)

    @staticmethod
    def _send_qq(qq_context: Dict, text: str):
        if not text:
            return
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        core = TBNapCatCore()
        if str(qq_context.get("message_type", "")) == "group":
            core.send_group_text(str(qq_context.get("target_id", "")), text)
        else:
            core.send_private_text(str(qq_context.get("target_id", "") or qq_context.get("user_id", "")), text)

    def _in_character(self, question: str, username: str) -> str:
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
            self.log.exception("[NewsNapcatPlugin] 角色口吻生成询问失败")
        return question

    def _decide(self, reply: str, question: str, username: str, extract_hint: str):
        """判断用户回复是否回答了追问。

        返回：
        - ("answer", value)：回答追问，value 为提取的有效信息；
        - ("redeliver", text)：另起话题，text 为需重新投递的消息；
        - 兜底按回答处理。
        """
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
                                "description": f"提取的有效信息（{extract_hint}），非回答则为空",
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
                        f"请判断用户是否在回答这个追问，并提取有效信息（{extract_hint}）。"
                    )},
                ],
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "parse_reply"}},
            )
            if resp and resp.choices:
                msg = resp.choices[0].message
                for tc in (msg.tool_calls or []):
                    if tc.function.name == "parse_reply":
                        import json
                        args = json.loads(tc.function.arguments or "{}")
                        if not args.get("is_answer"):
                            return ("redeliver", reply.strip())
                        value = str(args.get("value") or "").strip()
                        return ("answer", value or reply.strip())
        except Exception:
            self.log.exception("[NewsNapcatPlugin] 判断回复失败")
        return ("answer", reply.strip())

    @staticmethod
    def _llm():
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
