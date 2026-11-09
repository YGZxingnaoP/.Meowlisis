# -*- coding: utf-8 -*-
# func/toolbox/napcat/analysis/serious_judge.py
# QQ 严肃回复判官：收到新消息后一次严格工具决策，判断是否明确在要建议/决策/专业分析

import json
from typing import List, Optional

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig

TOOL_NAME = "qq_serious_judge"
RECENT_LIMIT = 6


class TBNapCatSeriousJudge:
    """严肃模式判官：只做判断，不写回复；拿不准一律 false"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.cfg = TBNapCatConfig()

    # ==================== 入口 ====================
    def judge(self, text: str, meowid: str, short_memory: Optional[List[dict]] = None,
              channel: str = "private", group_name: str = "") -> dict:
        empty = {"serious": False, "reason": "", "focus": ""}
        conf = self.cfg.serious_conf(channel)
        if not conf.get("enabled"):
            return empty
        body = str(text or "").strip()
        if len(body) < 4:
            return empty
        llm = self._llm()
        if llm is None or not getattr(llm, "client", None):
            self.log.error("[QQ严肃] 判官 LLM 不可用")
            return empty
        messages = [
            {"role": "system", "content": self._system(channel, group_name)},
            {"role": "user", "content": self._user(short_memory, body)},
        ]
        old_max = getattr(llm, "max_tokens", None)
        try:
            llm.max_tokens = max(64, int(conf.get("judge_max_tokens") or 160))
            resp = llm.chat(
                messages, tools=self.build_tools(),
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
                enable_thinking=False,
            )
        except Exception:
            self.log.exception("[QQ严肃] 判官调用失败")
            return empty
        finally:
            if old_max is not None:
                llm.max_tokens = old_max
        args = self._parse(resp)
        if not isinstance(args, dict):
            return empty
        serious = bool(args.get("serious"))
        reason = str(args.get("reason") or "").strip()
        if serious and not reason:
            return empty
        return {"serious": serious, "reason": reason,
                "focus": str(args.get("focus") or "").strip()}

    # ==================== 工具 ====================
    @staticmethod
    def build_tools() -> List[dict]:
        return [{
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": (
                    "判断这条 QQ 消息是否明确需要“严肃回复”。只做判断，不写回复；必须调用本工具。\n"
                    "serious=true 仅限：明确在征求建议、要一个决定、请求专业分析、要求教他/帮他权衡，"
                    "而且答案需要推理或取舍。\n"
                    "serious=false：打招呼、闲聊、吐槽、撒娇、角色扮演、单纯求安慰、事实查询、"
                    "让角色做事/调用工具、随口问“你觉得呢”。拿不准一律 false。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "serious": {
                            "type": "boolean",
                            "description": "是否明确需要严肃建议/决策/专业分析",
                        },
                        "reason": {
                            "type": "string",
                            "description": "判断依据，必须引用原话片段；serious=true 时必填",
                        },
                        "focus": {
                            "type": "string",
                            "description": "用户到底要你帮着决定/分析什么（一句话）",
                        },
                    },
                    "required": ["serious", "reason"],
                },
            },
        }]

    # ==================== 提示词 ====================
    @staticmethod
    def _system(channel: str, group_name: str) -> str:
        scene = "私聊" if str(channel) != "group" else f"QQ群【{group_name or '未命名'}】"
        return (
            f"你在判断一段{scene}对话里，对方这条消息是否明确需要你“认真给建议/做决策/做专业分析”。"
            "只做判断，不写回复。\n\n"
            "【serious=true 的条件】必须同时满足：\n"
            "1. 对方明确在要一个建议、一个决定、一个判断，或要求你分析利弊/方案/专业问题；\n"
            "2. 答案需要推理、取舍或专业信息，不是一句情绪回应就能解决。\n"
            "例子：我该不该答应他 / 这两个方案选哪个 / 帮我分析一下 / 给我个建议 / "
            "你觉得我该怎么跟他说 / 这道题/这件事你怎么看（明确要判断时）。\n\n"
            "【serious=false】\n"
            "- 打招呼、闲聊、吐槽、撒娇、角色扮演、玩梗；\n"
            "- 单纯求安慰、求夸奖、求陪伴；\n"
            "- 事实查询（天气/新闻/时间/怎么操作），或让角色做事/调用工具；\n"
            "- 随口问“你觉得呢”“好不好呀”，没有真的在要决策；\n"
            "- 拿不准。\n\n"
            "reason 必须引用对方原话片段；focus 写清对方到底要你帮着决定什么。"
            f"必须调用 {TOOL_NAME}。"
        )

    @staticmethod
    def _user(short_memory, current_text: str) -> str:
        rows = []
        for m in (short_memory or [])[-RECENT_LIMIT:]:
            if not isinstance(m, dict):
                continue
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            who = "我" if m.get("role") == "assistant" else "对方"
            rows.append(f"{who}：{content[:240]}")
        body = "\n".join(rows) or "（暂无）"
        return (f"【最近对话】\n{body}\n\n"
                f"【这条消息】\n{current_text}\n\n"
                f"只判断是否需要严肃回复。必须调用 {TOOL_NAME}。")

    # ==================== 解析 ====================
    @staticmethod
    def _parse(resp):
        if not resp or not getattr(resp, "choices", None):
            return None
        msg = resp.choices[0].message
        for tc in (getattr(msg, "tool_calls", None) or []):
            fn = getattr(tc, "function", None)
            if str(getattr(fn, "name", "")) != TOOL_NAME:
                continue
            try:
                data = json.loads(getattr(fn, "arguments", "") or "{}")
            except Exception:
                return None
            return data if isinstance(data, dict) else None
        return None

    @staticmethod
    def _llm():
        from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
        return TBNapcatAnalysis._llm()
