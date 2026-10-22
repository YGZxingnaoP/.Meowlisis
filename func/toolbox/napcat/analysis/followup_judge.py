# -*- coding: utf-8 -*-
# func/toolbox/napcat/analysis/followup_judge.py
# 群聊续聊判断：非角色扮演的纯工具判断，不产出回复、不接 QQ 回复链路

import json
import re
from typing import List

from func.log.default_log import DefaultLog


FOLLOWUP_TOOL_NAME = "judge_group_continue"

FOLLOWUP_RULES = (
    "【续聊判断原则】\n"
    "你只回答一件事：这批新消息里，有没有「必须由角色来接」的话。\n"
    "默认结论是 pass。只有能明确指出「哪一句 + 凭哪条原则」时才 continue。\n"
    "\n"
    "正向（满足任意一条 → continue）\n"
    "正1 点名：叫角色的名字/昵称/常见错字谐音/代称（猫、小猫、喵、你们家猫），或用「你」明确指向角色。\n"
    "正2 接话：在回答角色提出的问题、反驳或附和角色的观点、追问角色上一条提到的那个东西。\n"
    "正3 同一条话题线在推进：延续的是角色参与过的那条话题（同一件事/同一个人/同一个话题），角色是这条线的重要一环。\n"
    "正4 引用/回复角色：引用了角色的消息，或「回复」了角色的消息。\n"
    "正5 群体喊话且角色在列：「你们」「谁会……」「有人能……」这类需要应答的话。\n"
    "正6 挑衅/逗/要表态：明显在挑角色、逗角色、「你咋不说话」。\n"
    "正7 对角色这句话的直接反应：紧接角色的话的「哈哈哈」「6」「？」这类短反应。\n"
    "\n"
    "反向（满足任意一条 → pass，哪怕话题看起来有关）\n"
    "反1 别人之间的对话：两个以上群友在互相说话，没指向角色，也不需要角色插话。\n"
    "反2 话题已漂移：转到了跟角色无关的事，角色只是旁观者。\n"
    "反3 已经自然收尾：角色答完了，对方是「懂了/谢谢/嗯/好」这类收尾，没有新问题新信息。\n"
    "反4 无内容：纯表情、复读、数字、111、广告、群公告、打卡、接龙、抽奖、管理操作。\n"
    "反5 不是对角色说的：@ 的是别人，或叫的是和角色同名的另一个人。\n"
    "反6 其他机器人的输出：群机器人（如幻梦）的菜单、卡片、自动回复；除非有人在拿它跟角色开玩笑。\n"
    "反7 只是想热闹：冷场、有人说话、话题有意思——都不是理由。\n"
    "\n"
    "补充约束\n"
    "· 时间不是硬条件，但可作线索：距今很久 + 明显是另一个话题 → pass。\n"
    "· 不要因为「上一条是角色说的」「想保持存在感」就自动接。\n"
    "· 只看这批新消息；里面有多人说话时，只算指向角色的那部分，其余忽略。\n"
    "· 这批里有多人分别对角色说话 → continue，target 填最该回的那个人。\n"
    "· 拿不准选 pass：漏接的代价远小于硬接。\n"
    "· reason 必须写出命中的原则编号和对应的原话片段。"
)


class TBNapcatFollowupJudge:
    """群聊续聊判断器：只产出 {decision, target, reason}。

    - 不使用角色提示词、不产出回复正文，与 QQ 回复链路完全隔离；
    - LLM 客户端直接复用 toolbox 端口（与 TBNapcatAnalysis 同一套）；
    - 任何异常 / 无效输出一律按 pass 处理。
    """

    RULE_REF = re.compile(r"[正反]\s*[0-9１-９]")

    def __init__(self):
        self.log = DefaultLog().getLogger()

    # ==================== 工具 schema ====================
    def build_tools(self) -> List[dict]:
        return [{
            "type": "function",
            "function": {
                "name": FOLLOWUP_TOOL_NAME,
                "description": (
                    "判断一批新的群聊消息是否需要角色接着回复。只做判断，不写回复。\n"
                    + FOLLOWUP_RULES
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                            "enum": ["continue", "pass"],
                            "description": "continue=需要角色接着回复；pass=不需要，保持沉默",
                        },
                        "target": {
                            "type": "string",
                            "description": "continue 时填：这批里最该接话的那个人的 QQ 号或群名片",
                        },
                        "reason": {
                            "type": "string",
                            "description": (
                                "必须写「原则编号 + 对应原话片段」，例如：正2「那个电影我也看过」；"
                                "拿不准就 pass"
                            ),
                        },
                    },
                    "required": ["decision", "reason"],
                },
            },
        }]

    # ==================== 判断入口 ====================
    def judge(self, ctx: dict) -> dict:
        result = {"decision": "pass", "target": "", "reason": ""}
        ctx = dict(ctx or {})
        if not str(ctx.get("batch") or "").strip():
            return result
        llm = self._llm()
        if llm is None or not getattr(llm, "client", None):
            self.log.error("[群续聊判断] LLM 不可用")
            return result

        messages = [
            {"role": "system", "content": self._system(ctx)},
            {"role": "user", "content": self._user(ctx)},
        ]
        from func.toolbox.napcat.config import TBNapCatConfig
        tokens = max(64, int(getattr(TBNapCatConfig(), "group_followup_judge_max_tokens", 256) or 256))
        old_max = getattr(llm, "max_tokens", None)
        try:
            llm.max_tokens = tokens
            resp = llm.chat(
                messages,
                tools=self.build_tools(),
                tool_choice={"type": "function", "function": {"name": FOLLOWUP_TOOL_NAME}},
                enable_thinking=False,
            )
        except Exception:
            self.log.exception("[群续聊判断] 调用失败")
            return result
        finally:
            if old_max is not None:
                llm.max_tokens = old_max

        if not resp or not resp.choices:
            self.log.warning("[群续聊判断] 无有效响应，按 pass 处理")
            return result
        message = resp.choices[0].message
        args = {}
        for call in (getattr(message, "tool_calls", None) or []):
            function = getattr(call, "function", None)
            if str(getattr(function, "name", "")) != FOLLOWUP_TOOL_NAME:
                continue
            try:
                args = json.loads(getattr(function, "arguments", "") or "{}")
            except Exception:
                args = {}
            break
        if not isinstance(args, dict) or not args:
            self.log.info("[群续聊判断] 未产出工具调用，按 pass 处理")
            return result

        decision = str(args.get("decision") or "").strip().lower()
        reason = str(args.get("reason") or "").strip()
        if decision not in ("continue", "pass"):
            return result
        if decision == "continue" and not self.RULE_REF.search(reason):
            self.log.info(f"[群续聊判断] continue 未引用原则编号，按 pass 处理: {reason[:40]}")
            return result
        return {
            "decision": decision,
            "target": str(args.get("target") or "").strip(),
            "reason": reason,
        }

    # ==================== 提示词 ====================
    @staticmethod
    def _system(ctx: dict) -> str:
        aliases = "、".join([str(a) for a in (ctx.get("aliases") or []) if str(a).strip()]) or "无"
        members = "、".join([str(n) for n in (ctx.get("members") or []) if str(n).strip()]) or "未知"
        history = "\n".join([str(x) for x in (ctx.get("history") or []) if str(x).strip()]) or "（暂无）"
        anchor = ctx.get("anchor") or {}
        anchor_name = str(anchor.get("username") or anchor.get("user_id") or "某人")
        return (
            "你是群聊消息分流器，只判断一批新的群聊消息要不要交给角色接着回复。\n"
            "你不扮演角色、不写回复、不做分析，只调用工具给出判断；"
            f"判断原则见 {FOLLOWUP_TOOL_NAME} 的工具说明，必须严格遵守。\n\n"
            f"【角色】{ctx.get('self_name') or '角色'}\n"
            f"可能被这样称呼或提及：{aliases}（这些词也会触发角色，但可能只是群友昵称）\n"
            f"群里在的人：{members}\n"
            f"群名：{ctx.get('group_name') or '未知'}\n\n"
            "【背景】\n"
            f"· 角色最近一次在这个群说话：{ctx.get('elapsed') or '未知'}（「{ctx.get('last_reply') or '还没说话'}」）\n"
            f"· 角色是被【{anchor_name}】用{ctx.get('trigger') or '@'}叫出来的，"
            f"当时说的是：「{ctx.get('anchor_text') or ''}」\n\n"
            "【最近的群聊记录】（旧 → 新；可能已包含本批消息，一切以【本批新消息】为准）\n"
            f"{history}"
        )

    @staticmethod
    def _user(ctx: dict) -> str:
        return (
            f"【本批新消息】共 {ctx.get('batch_count') or 0} 人发言\n"
            f"{ctx.get('batch') or ''}\n\n"
            f"只针对这批消息判断：有没有必须由角色来接的话。必须调用 {FOLLOWUP_TOOL_NAME}。"
        )

    # ==================== LLM 客户端（直接接 toolbox 端口） ====================
    @staticmethod
    def _llm():
        from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
        return TBNapcatAnalysis._llm()
