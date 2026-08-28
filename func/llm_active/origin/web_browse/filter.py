# -*- coding: utf-8 -*-
# func/llm_active/origin/web_browse/filter.py
# 视频主题过滤：LLM 语义判断视频是否合适（function calling 决策，tool_choice=auto）

import json
from typing import Dict

from func.log.default_log import DefaultLog
from func.llm_active.origin.web_browse.config import AutoWebBrowseConfig


class AutoVideoFilter:
    """用 LLM 判断视频是否适合作为主动回复素材（tool 决策）

    - tool_choice=auto：让模型深入思考后自主决定是否调用工具；
    - 未调用工具：直接判定不合适（舍弃），换下一个候选；
    - 调用工具：解析结构化参数，杜绝 content 正则解析被截断/污染的问题。
    """

    TOOL_NAME = "judge_video"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoWebBrowseConfig()

    def is_suitable(self, video: Dict) -> Dict:
        """返回 {"suitable": bool, "topic": str, "reason": str}"""
        llm = self._llm()
        if llm is None or not llm.client:
            self.log.error("[WebBrowse] 过滤 LLM 不可用，按不合适处理")
            return {"suitable": False, "topic": "", "reason": "LLM不可用"}

        allow = self.config.allow_topics
        strict = self.config.strictness
        forbid = self.config.forbid_abstract

        system = (
            "你是一个内容审核助手。请深入理解给定B站视频的标题、标签与简介，"
            "判断它是否适合作为虚拟主播主动聊天的话题素材。"
            "判断结论必须通过调用 judge_video 工具输出。"
        )
        user = (
            f"允许的主题：{('、'.join(allow)) if allow else '（无配置，随机）'}\n"
            f"严格程度：{strict}（strict=只允许列表内主题；loose=允许其它主题）\n"
            f"是否禁止抽象视频：{forbid}\n\n"
            f"视频标题：{video.get('title', '')}\n"
            f"视频标签：{video.get('label', '')}\n"
            f"视频简介：{video.get('introduction', '')}\n\n"
            f"请深入思考后调用 judge_video 工具，给出该视频是否合适的结构化判断。"
        )

        resp = llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=self.build_tools(),
            tool_choice="auto",
        )
        if not resp or not resp.choices:
            self.log.warning("[WebBrowse] 过滤 LLM 无响应")
            return {"suitable": False, "topic": "", "reason": "无响应"}

        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            # 没有调工具就舍弃
            self.log.info("[WebBrowse] 过滤 LLM 未调用工具，舍弃该视频")
            return {"suitable": False, "topic": "", "reason": "未调用工具"}

        for tc in tool_calls:
            if tc.function.name != self.TOOL_NAME:
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                self.log.exception("[WebBrowse] 解析过滤工具参数失败")
                return {"suitable": False, "topic": "", "reason": "参数解析失败"}
            suitable = bool(args.get("suitable", False))
            topic = str(args.get("topic", "") or "").strip()
            reason = str(args.get("reason", "") or "").strip()
            return {"suitable": suitable, "topic": topic, "reason": reason}

        self.log.warning("[WebBrowse] 过滤 LLM 未调用目标工具")
        return {"suitable": False, "topic": "", "reason": "未调用目标工具"}

    def build_tools(self) -> list:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "判断B站视频是否适合作为虚拟主播主动聊天的话题素材",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "suitable": {
                            "type": "boolean",
                            "description": "是否适合作为主动回复素材",
                        },
                        "topic": {
                            "type": "string",
                            "description": "命中的主题（未命中填'其它'）",
                        },
                        "reason": {
                            "type": "string",
                            "description": "一句话判断理由",
                        },
                    },
                    "required": ["suitable", "reason"],
                },
            },
        }]

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
