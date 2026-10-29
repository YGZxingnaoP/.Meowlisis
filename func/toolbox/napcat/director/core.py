# -*- coding: utf-8 -*-
# func/toolbox/napcat/director/core.py
# QQ 导演核心（简化版）：私聊 / 群聊 @ 触发 → 判官 → 起一段迷你走向 → 每说一次推进一步 → clear
# 与主链路导演完全独立：自己的 store / 判官 / 块 / 素材，不引用 func.llm_active、func.pipeline.llm_director、func.psyche。

import datetime

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.director.config import QQDirectorConfig
from func.toolbox.napcat.director.judge import QQDirectorJudge
from func.toolbox.napcat.director.material import QQDirectorMaterial
from func.toolbox.napcat.director.store import QQDirectorStore

STEP_LIMIT = 60


@singleton
class QQDirectorCore:
    """QQ 导演：只在私聊 / 群聊 @（含其续聊）时被调用；冒泡路径不接入"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.store = QQDirectorStore()
        self.judge = QQDirectorJudge()
        self.material = QQDirectorMaterial()

    # ==================== session ====================
    @staticmethod
    def session_private(user_id) -> str:
        return f"qq_private:{user_id}"

    @staticmethod
    def session_group(group_id) -> str:
        return f"qq_group:{group_id}"

    def is_active(self, session: str) -> bool:
        return bool(self.store.get(session).get("active"))

    # ==================== 回合入口 ====================
    def before_turn(self, session: str, channel: str, short_memory: list = None,
                    current_text: str = "", group_name: str = "",
                    maintain_only: bool = False) -> bool:
        """回复前调用：判断要不要起戏/要不要收。返回该 session 是否有激活走向。

        - maintain_only=True（续聊）：没有走向时不起戏，只做「收不收」判断；
        - 私聊 / 群聊 @：没有走向时可以起戏。
        """
        if not QQDirectorConfig().enabled:
            return False
        plan = self.store.get(session)
        active = bool(plan.get("active"))
        if maintain_only and not active:
            return False
        # 没走向时先抽由头，判官看得到它，第一步才好拿它当话头；有走向时不再换由头
        material = None if active else self.material.pick()
        verdict = self.judge.judge(channel, group_name, plan, short_memory, current_text,
                                   material=material)
        if verdict is None:
            return active
        if active:
            if verdict.get("clear"):
                self.clear(session, verdict.get("reason") or "对方接上了")
                return False
            return True
        if not verdict.get("cold"):
            return False
        steps = verdict.get("steps") or []
        if not steps:
            return False
        plan = self._build_plan(session, channel, verdict, steps, material)
        if not plan.get("steps"):
            return False
        self.store.set(session, plan)
        self.log.info(f"[QQ导演] 起戏（{session}）：{verdict.get('reason', '')[:50]}")
        return True

    def advance(self, session: str):
        """真的说出去一句之后调用：当前步打勾、进入下一步；全部走完就 clear"""
        plan = self.store.get(session)
        if not plan.get("active"):
            return
        steps = plan.get("steps") or []
        current = None
        for step in steps:
            if step.get("id") == plan.get("current_id") and not step.get("done"):
                current = step
                break
        if current is None:
            for step in steps:
                if not step.get("done"):
                    current = step
                    break
        if current is None:
            self.clear(session, "全部完成")
            return
        current["done"] = True
        plan["turns"] = int(plan.get("turns") or 0) + 1
        plan["updated_at"] = self._now()
        nxt = None
        for step in steps:
            if not step.get("done"):
                nxt = step
                break
        if nxt is None:
            self.store.set(session, plan)
            self.clear(session, "全部完成")
            return
        plan["current_id"] = nxt.get("id")
        self.store.set(session, plan)

    def clear(self, session: str, reason: str = ""):
        """结束某个 session 的走向（保留内容备查）"""
        plan = self.store.clear(session, reason)
        if plan:
            self.log.info(f"[QQ导演] 收（{session}）：{reason or '未注明'}")

    # ==================== 内部 ====================
    def _build_plan(self, session: str, channel: str, verdict: dict, steps: list,
                    material: dict = None) -> dict:
        now = self._now()
        rows = []
        for idx, text in enumerate(steps[:max(1, int(QQDirectorConfig().max_steps))]):
            goal = str(text).strip()[:STEP_LIMIT]
            if not goal:
                continue
            rows.append({"id": len(rows) + 1, "goal": goal, "done": False})
        if material is None:
            material = self.material.pick()
        return {
            "session": session,
            "channel": "group" if str(channel) == "group" else "private",
            "active": True,
            "created_at": now,
            "updated_at": now,
            "reason": str(verdict.get("reason") or "").strip(),
            "material": material,
            "steps": rows,
            "current_id": rows[0]["id"] if rows else 0,
            "turns": 0,
            "clear_reason": "",
        }

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
