# -*- coding: utf-8 -*-
# func/llm_active/inherit/inherit_core.py
# 继承型主动回复：延续当前话题，tool_choice 决策并输出

import json
import os
import uuid

from func.log.default_log import DefaultLog
from func.llm.output import Output
from func.llm.state import LLmState
from func.pipeline.llm_tts import LLMTtsBridge
from func.pipeline.short_memory import ShortMemory
from func.llm_active.config import AutoActiveConfig
from func.llm_active.get_prompt import AutoGetPrompt
from func.llm_active.get_shortmem import AutoGetShortMem


class AutoInheritCore:
    """继承型主动回复：判断是否延续当前话题，延续则输出主动回复内容"""

    TOOL_NAME = "auto_reply"

    def __init__(self, llm):
        self.log = DefaultLog().getLogger()
        self.llm = llm
        self.config = AutoActiveConfig()
        self.get_prompt = AutoGetPrompt()
        self.get_shortmem = AutoGetShortMem()
        self.tts_bridge = LLMTtsBridge()
        self.short_memory = ShortMemory()
        self.topic_path = os.path.join(".temp", "current_topic.json")

    def run(self):
        """执行继承型主动回复，返回是否延续话题（False 表示应转 origin）"""
        topic = self._read_topic()
        prompt = self.get_prompt.get_active_prompt(self.config.cold_time)
        history = self.get_shortmem.load()

        messages = [{"role": "system", "content": prompt}]
        for item in history:
            messages.append({"role": item["role"], "content": item["content"]})
        messages.append({
            "role": "user",
            "content": f"当前话题：{topic}\n请根据最近的对话，判断是否延续当前话题主动发起聊天，并给出主动回复内容。"
        })

        resp = self.llm.chat(messages, tools=self.build_tools(), tool_choice=self.build_tool_choice())
        result = self._parse_tool(resp)
        if not result:
            return False

        if not bool(result.get("continue_topic", False)):
            return False

        reply = str(result.get("reply_content", "") or "").strip()
        reply = Output.remove_analysis(reply)
        if not reply:
            return False

        traceid = str(uuid.uuid4())
        # 整段合成，不分段
        self.tts_bridge.send_whole_to_answer_queue(LLmState(), reply, traceid)
        # 仅 AI 消息写入短期记忆
        self.short_memory.save(
            {"role": "assistant", "content": reply, "type": "llm_active_response"},
            self._max_rounds(),
        )
        self.log.info(f"[{traceid}][主动回复-inherit]{reply}")
        return True

    def _max_rounds(self):
        from func.llm.config import LLMConfig
        return LLMConfig().short_term_rounds

    def build_tools(self):
        """构建主动回复工具定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "判断是否延续当前话题，并输出主动回复内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "continue_topic": {"type": "boolean", "description": "是否延续当前话题"},
                        "reply_content": {"type": "string", "description": "主动回复内容"}
                    },
                    "required": ["continue_topic", "reply_content"]
                }
            }
        }]

    def build_tool_choice(self):
        """强制调用主动回复工具"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}

    def _read_topic(self):
        """读取 .temp/current_topic.json 中的当前话题"""
        try:
            with open(self.topic_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return str(data.get("topic", "") or "").strip()
        except Exception:
            return ""

    def _parse_tool(self, resp):
        """解析主动回复工具调用结果"""
        if not resp or not resp.choices:
            return None
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == self.TOOL_NAME:
                    return json.loads(tc.function.arguments)
        except Exception:
            self.log.exception("解析主动回复工具调用失败")
        return None
