# -*- coding: utf-8 -*-
# func/llm_active/director/planner.py
# 导演规划器：判「要不要开始」+ 用工具输出一份只含行为与思路的表演清单

import os
import json
from typing import Optional

from func.log.default_log import DefaultLog
from func.llm_active.director.config import AutoDirectorConfig
from func.llm_active.director.material import DirectorMaterial
from func.llm_active.director.state import new_plan
from func.llm_active.director.tools import PLAN_TOOL_NAME, plan_tool
from func.pipeline.llm_toolbox import LLMToolboxBridge
from func.pipeline.llm_psyche import LLMPsycheBridge
from func.pipeline.short_memory import ShortMemory
from func.pipeline.system_prompt import SystemPromptBridge
from func.config.app_config import AppConfig


class DirectorPlanner:
    """规划器：一次规划 = 抽素材 → 角色身份 + 心理 + 最近对话 → 工具循环 → 计划"""

    KIND_DESC = {
        "start_bored": "你自己觉得主人现在有点没意思了，想立刻开口带他做点什么。",
        "start_idle": "已经有一段时间没人说话了，你想主动找点事，把他拉回来。",
        "rewrite": "上一条路走不通了（他一直没接），这次换一个方向重新开始。",
    }

    def __init__(self, core):
        self.log = DefaultLog().getLogger()
        self.core = core
        self.material = DirectorMaterial()

    # ==================== 入口 ====================
    def plan(self, kind: str, uid=None, reason: str = "") -> Optional[dict]:
        """生成一份计划；返回 None 表示「不开始导演」（调用方回落原主动回复）"""
        cfg = AutoDirectorConfig()
        material = self.material.pick()
        messages = [
            {"role": "system", "content": self._system()},
            {"role": "user", "content": self._user(kind, reason, material)},
        ]
        tools = LLMToolboxBridge().get_memory_schemas() + [plan_tool()]
        max_rounds = max(1, int(cfg.planner_max_tool_rounds))
        for round_idx in range(max_rounds):
            try:
                resp = self.core.plan_llm.chat(messages, tools=tools,
                                               options={"enable_thinking": False})
            except Exception:
                self.log.exception("[导演] 规划器调用异常")
                return None
            if not resp or not getattr(resp, "choices", None):
                self.log.warning("[导演] 规划器无响应")
                return None
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                messages.append({"role": "assistant", "content": msg.content or ""})
                messages.append({"role": "user",
                                 "content": f"请调用 {PLAN_TOOL_NAME} 输出计划，不要输出解释性正文。"})
                continue
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [{"id": tc.id or f"call_{round_idx}_{idx}", "type": "function",
                                "function": {"name": tc.function.name,
                                             "arguments": tc.function.arguments or "{}"}}
                               for idx, tc in enumerate(calls)],
            })
            plan_args = None
            for idx, tc in enumerate(calls):
                name = str(getattr(tc.function, "name", "") or "")
                if name == PLAN_TOOL_NAME:
                    plan_args = self._parse(tc.function.arguments)
                    continue
                result = LLMToolboxBridge().dispatch_memory_tool(
                    name, tc.function.arguments or "{}")
                messages.append({"role": "tool", "tool_call_id": tc.id or f"call_{round_idx}_{idx}",
                                 "content": str(result)[:4000]})
            if plan_args is None:
                continue
            if not bool(plan_args.get("start")):
                self.log.info(f"[导演] 规划器判断不开始：{str(plan_args.get('reason') or '')[:40]}")
                return None
            plan = new_plan(kind, str(plan_args.get("reason") or reason),
                            self._material_meta(material), plan_args.get("steps"))
            if plan is None:
                self.log.warning("[导演] 计划没有有效步骤，放弃本次开始")
                return None
            moved = self.material.consume(material)
            if moved:
                # 视频已从缓存移到收藏目录：把计划里的路径同步过去，后续要做「回看/引用」时找得到
                plan.setdefault("material", {})["path"] = moved
            self.log.info(f"[导演] 计划已生成：{len(plan.get('steps') or [])} 步 / "
                          f"素材={plan.get('material', {}).get('type', '')}")
            return plan
        self.log.warning(f"[导演] 规划超出最大工具轮数 {max_rounds}，放弃本次开始")
        return None

    # ==================== 提示词 ====================
    def _system(self) -> str:
        ai_name = str(AppConfig().ai_name or "")
        persona = ""
        try:
            persona = SystemPromptBridge().get_character_prompt() or ""
        except Exception:
            self.log.exception("[导演] 读取角色卡失败")
        psyche = self._psyche_text()
        recent = self._recent_text()
        instruction = self._load_prompt().replace("{ai_name}", ai_name)
        parts = [
            f"你现在就是{ai_name}，整个过程用第一人称想事情，不要跳出角色。",
            f"【你的角色设定】\n{persona}" if persona else "",
            f"【你现在的心理】\n{psyche}" if psyche else "",
            f"【最近的对话】\n{recent}" if recent else "",
            f"【任务指令】\n{instruction}",
        ]
        return "\n\n".join(p for p in parts if p)

    def _user(self, kind: str, reason: str, material) -> str:
        parts = [
            f"【这一次的情况】{self.KIND_DESC.get(kind, self.KIND_DESC['start_idle'])}",
            f"【判断依据】{reason}" if reason else "",
            self.material.describe(material),
            f"想清楚这一场怎么演，然后调用 {PLAN_TOOL_NAME} 输出计划。",
        ]
        return "\n\n".join(p for p in parts if p)

    def _psyche_text(self) -> str:
        try:
            data = LLMPsycheBridge().get_psyche("main") or {}
            theme = str(data.get("theme", "") or "").strip()
            content = [str(c).strip() for c in (data.get("content") or []) if str(c).strip()]
            return "\n".join(([theme] if theme else []) + content)
        except Exception:
            return ""

    def _recent_text(self) -> str:
        try:
            rounds = max(1, int(AutoDirectorConfig().judge_history_rounds))
            rows = ShortMemory().load_by_type(("llm_fast_response",))[-rounds * 2:]
        except Exception:
            self.log.exception("[导演] 读取最近对话失败")
            return ""
        lines = []
        for m in rows:
            who = "主人" if m.get("role") == "user" else "我"
            lines.append(f"{who}：{m.get('content', '')}")
        return "\n".join(lines)

    @staticmethod
    def _material_meta(material) -> dict:
        """计划里留存的素材元信息（含 brief：执行回合靠它记住"这一场在聊什么"）"""
        material = material or {}
        if material.get("type") == "video":
            data = material.get("data") or {}
            title = str(data.get("title", "") or "").strip()
            content = str(data.get("content", "") or "").strip()
            brief = f"{title}｜{content}" if content else title
            return {"type": "video",
                    "title": title,
                    "topic": str(data.get("topic", "") or ""),
                    "path": str(material.get("path", "") or ""),
                    "brief": brief[:400]}
        topic = str(material.get("topic", "") or "").strip()
        tag = str(material.get("tag", "") or "").strip()
        brief = f"{topic}（{tag}）" if tag else topic
        return {"type": "topic",
                "topic": topic,
                "tag": tag,
                "brief": brief}

    @staticmethod
    def _parse(raw) -> Optional[dict]:
        try:
            data = json.loads(raw or "{}", strict=False)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _load_prompt() -> str:
        path = os.path.join("func", "llm_active", "director", "prompts", "planner_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ("你是{ai_name}。想清楚这一场怎么演，只写行为与思路、不写台词，"
                    "禁止冷笑话；必须调用 director_plan。")
