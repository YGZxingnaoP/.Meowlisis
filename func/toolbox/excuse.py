# -*- coding: utf-8 -*-
# func/toolbox/excuse.py
# Toolbox 通用询问链路：AI 有疑问时以角色口吻语音询问用户，阻塞等待文本输入补充需求
# 供 toolbox 下所有模块（napcat / danmaku / minecraft ...）复用

import queue
import uuid
import threading
from typing import Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.config import TBoxConfig


@singleton
class TBExcuse:
    """通用询问器：语音/文字询问 + 阻塞等待用户文本输入 + 记录到 public_short_memory

    等待的是「文本输入结果」，来源可以是：
    - sensevoice_llm（语音识别后的文本，经 api.py 回调拦截）
    - api 直接收到的文本（/msg、/chat 等 HTTP 接口）
    通过 route_text() 统一拦截，正在等待时消费该文本并返回 True。

    使用方式（供任何 toolbox 模块）：
        reply = TBExcuse().ask("你要把这个文件发给谁？", username="主人")
        if reply: ...
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._waiting = False

    # ==================== 主入口 ====================
    def ask(self, question: str, username: str = "", timeout: float = None) -> Optional[str]:
        """以角色口吻语音询问用户，阻塞等待文本回复；返回用户确认文本（超时返回 None）"""
        if not question:
            return None
        timeout = timeout if timeout is not None else self.config.excuse_timeout

        question_text = self._in_character(question, username)
        # 记录 assistant 询问
        self._save_memory("assistant", question_text)
        # TTS 语音询问（toolbox_tts）
        self._speak(question_text)

        if not self.config.excuse_enabled:
            self.log.info("[Excuse] 未启用阻塞等待，直接返回")
            return None

        # 阻塞等待文本输入（sensevoice_llm 或 api 直接文本，经 route_text 送达）
        self._set_waiting(True)
        try:
            reply = self._queue.get(timeout=timeout)
        except queue.Empty:
            self.log.warning("[Excuse] 等待用户回复超时")
            reply = None
        finally:
            self._set_waiting(False)

        if reply:
            self._save_memory("user", str(reply))
        return reply

    # ==================== 文本拦截入口 ====================
    def route_text(self, text: str, username: str = "") -> bool:
        """文本输入统一拦截：若正在等待询问回复，则消费该文本并返回 True（已处理）。
        接入方式：
        - api.py 的 sensevoice 回调、/msg、/chat 端点先调用本方法；
        - 返回 True 则不再走后续 LLM 处理链。
        """
        if not self._waiting:
            return False
        if text and text.strip():
            self._queue.put(text.strip())
            return True
        return False

    # 兼容旧命名（sensevoice 场景）
    def route_sensevoice(self, text: str, username: str = "") -> bool:
        return self.route_text(text, username)

    def is_waiting(self) -> bool:
        return self._waiting

    # ==================== 内部 ====================
    def _set_waiting(self, value: bool):
        with self._lock:
            self._waiting = value

    def _save_memory(self, role: str, content: str):
        """保存询问/确认到 public_short_memory，type=toolbox_excuse（user/assistant 成对）"""
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({
                "role": role,
                "content": f"【toolbox询问】{content}",
                "type": "toolbox_excuse",
            }, 30)
        except Exception:
            self.log.exception("[Excuse] 保存短期记忆失败")

    def _speak(self, text: str):
        """通过 toolbox_tts 合成语音（桥接内部自持 LLmState，toolbox 只传文本，分段流式）"""
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(text, source="toolbox")
        except Exception:
            self.log.exception("[Excuse] TTS 合成失败")

    def _in_character(self, question: str, username: str = "") -> str:
        """以角色身份提问：用完整系统提示词，让角色以 AI 方式思考后自然发问。
        - 不是机械改写，而是让 LLM 在完整角色人设（前置词+角色卡+价值观+记忆）约束下，
          把「内部需要询问的信息」转化为角色自己会说的话。
        - 失败回退原文 question。
        """
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            system_prompt = TBoxGetPrompt().get_system_prompt(username, question) or ""
            llm = self._llm()
            if llm and llm.client:
                resp = llm.chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": (
                        f"你现在需要向用户询问一个信息，内部需求是：{question}\n"
                        f"请以你自己的角色身份，自然、口语化地问出这个问题。注意需要明确问句，让用户知道要回复什么"
                    )},
                ])
                if resp and resp.choices:
                    content = (resp.choices[0].message.content or "").strip()
                    if content:
                        return content
        except Exception:
            self.log.exception("[Excuse] 角色口吻提问失败")
        return question

    def _llm(self):
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
