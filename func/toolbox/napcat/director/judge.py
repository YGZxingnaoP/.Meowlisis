# -*- coding: utf-8 -*-
# func/toolbox/napcat/director/judge.py
# QQ 导演判官：判断「现在是不是没话题 / 当前走向要不要收」，只做判断、不写回复

import json

from func.log.default_log import DefaultLog
from func.toolbox.napcat.director.config import QQDirectorConfig

TOOL_NAME = "qq_director_judge"
RECENT_LIMIT = 12


class QQDirectorJudge:
    """判官：一次小 LLM 调用，输出 {cold, clear, reason, steps}"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    # ==================== 工具 ====================
    @staticmethod
    def build_tools():
        return [{
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": (
                    "判断这段 QQ 对话现在是不是没话题了，以及当前走向要不要收。"
                    "只做判断，不写回复；必须调用本工具。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cold": {
                            "type": "boolean",
                            "description": "是不是没话题了：对方/群里在敷衍、没有新内容，或明确说无聊",
                        },
                        "clear": {
                            "type": "boolean",
                            "description": "当前走向是否到此结束：对方已经接上话题，或明确说别烦/不想听",
                        },
                        "reason": {
                            "type": "string",
                            "description": "判断依据，必须引用原话片段",
                        },
                        "steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "cold=true 且当前没有走向时，给 1~3 步很短的走向（写做什么，不写台词）",
                        },
                    },
                    "required": ["cold", "clear", "reason"],
                },
            },
        }]

    # ==================== 判断 ====================
    def judge(self, channel: str, group_name: str, plan: dict,
              short_memory: list, current_text: str = "", material: dict = None):
        """返回 {cold, clear, reason, steps} 或 None（失败/无工具调用）"""
        cfg = QQDirectorConfig()
        if not cfg.enabled:
            return None
        llm = self._llm()
        if llm is None or not getattr(llm, "client", None):
            self.log.error("[QQ导演] 判官 LLM 不可用")
            return None
        messages = [
            {"role": "system", "content": self._system(channel, group_name, plan, material)},
            {"role": "user", "content": self._user(short_memory, current_text)},
        ]
        old_max = getattr(llm, "max_tokens", None)
        try:
            llm.max_tokens = max(64, int(cfg.judge_max_tokens))
            resp = llm.chat(
                messages, tools=self.build_tools(),
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
                enable_thinking=False,
            )
        except Exception:
            self.log.exception("[QQ导演] 判官调用失败")
            return None
        finally:
            if old_max is not None:
                llm.max_tokens = old_max
        args = self._parse(resp)
        if args is None:
            return None
        steps = args.get("steps")
        if isinstance(steps, str):
            steps = [steps]
        if not isinstance(steps, (list, tuple)):
            steps = []
        return {
            "cold": bool(args.get("cold")),
            "clear": bool(args.get("clear")),
            "reason": str(args.get("reason") or "").strip(),
            "steps": [str(s).strip() for s in steps if str(s).strip()][:max(1, int(cfg.max_steps))],
        }

    # ==================== 提示词 ====================
    @staticmethod
    def _system(channel: str, group_name: str, plan: dict, material: dict = None) -> str:
        scene = "私聊" if str(channel) != "group" else f"QQ群【{group_name or '未命名'}】"
        if plan and plan.get("active"):
            lines = []
            for step in plan.get("steps") or []:
                mark = "[x]" if step.get("done") else (
                    "[>]" if step.get("id") == plan.get("current_id") else "[ ]")
                lines.append(f"{mark} {step.get('id')} {step.get('goal')}")
            plan_text = "\n".join(lines) or "（空）"
            material_text = ""
        else:
            plan_text = "（当前没有走向）"
            brief = str((material or {}).get("brief") or "").strip()
            material_text = (
                f"\n【这次可用的由头】\n{brief}\n"
                "（之前分享过的视频；起戏时第一步优先用它当话头：问他看过没 / 让他猜是什么，别照念内容）\n"
                if brief else ""
            )
        return (
            f"你在判断一段{scene}对话现在是不是没话题了。只做判断，不写回复。\n\n"
            "【cold=true 的条件】\n"
            "- 对方/群里明显在敷衍（嗯、哦、好、随便、不知道），没有新内容，也不问你；\n"
            "- 对方明确说无聊、没事干、没意思。\n"
            "【cold=false】\n"
            "- 在讲自己的事、在问你问题、在认真聊；\n"
            "- 刚说要去忙 / 在做题 / 在打游戏（有事，不是无聊）；\n"
            "- 拿不准就不 cold。\n\n"
            "【当前走向】\n"
            f"{plan_text}\n"
            f"{material_text}\n"
            "【clear 怎么填】\n"
            "- 当前没有走向：clear 必须是 false；cold=true 时用 steps 给 1~3 步很短的走向"
            "（每步一句话，写做什么，不写台词；私聊对一个人，群聊面向全群）；\n"
            "- 当前有走向：对方已经接上话题 / 明确说别烦、不想听 → clear=true；"
            "还在敷衍、还想接着演 → clear=false。\n\n"
            "reason 必须引用原话片段。必须调用 qq_director_judge。"
        )

    @staticmethod
    def _user(short_memory: list, current_text: str) -> str:
        rows = []
        for m in (short_memory or [])[-RECENT_LIMIT:]:
            if not isinstance(m, dict):
                continue
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            who = "我" if m.get("role") == "assistant" else "对方"
            rows.append(f"{who}：{content}")
        body = "\n".join(rows) or "（暂无）"
        text = str(current_text or "").strip()
        parts = [f"【最近消息】\n{body}"]
        if text:
            parts.append(f"【这条消息】\n{text}")
        parts.append("只判断：现在是不是没话题、当前走向要不要收。必须调用 qq_director_judge。")
        return "\n\n".join(parts)

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
        """复用 QQ 链路现成的 toolbox 端口（与 followup_judge 同一个口）"""
        from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
        return TBNapcatAnalysis._llm()
