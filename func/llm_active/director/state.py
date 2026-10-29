# -*- coding: utf-8 -*-
# func/llm_active/director/state.py
# 导演计划数据模型：构造 / 规范化 / 推进 / 判定结束
# 纯函数，不碰网络与文件，状态由 func/pipeline/llm_director.py 落盘

import datetime
from typing import Dict, List, Optional

MAX_REACTIONS = 2


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _text(value, limit: int = 0) -> str:
    body = str(value or "").strip()
    if limit > 0:
        body = body[:limit]
    return body


def normalize_steps(raw_steps) -> List[Dict]:
    """把工具输出的 steps 规范成内部结构（id 连续、字段齐全、不设步数上限）"""
    steps = []
    for row in (raw_steps or []):
        if not isinstance(row, dict):
            continue
        goal = _text(row.get("goal"))
        if not goal:
            continue
        steps.append({
            "id": len(steps) + 1,
            "goal": goal,
            "move": _text(row.get("move")),
            "expect": _text(row.get("expect")),
            "if_not": _text(row.get("if_not")),
            "done": False,
        })
    return steps


def new_plan(kind: str, reason: str, material: Optional[Dict], raw_steps) -> Optional[Dict]:
    """构造一份新计划；没有有效步骤时返回 None（调用方回落原主动回复）"""
    steps = normalize_steps(raw_steps)
    if not steps:
        return None
    now = _now()
    return {
        "scope": "main",
        "active": True,
        "start_reason": _text(kind),
        "reason": _text(reason),
        "created_at": now,
        "updated_at": now,
        "material": dict(material or {}),
        "silent_rounds": 0,
        "turns": 0,
        "yield_to_user": False,
        "current_id": steps[0]["id"],
        "steps": steps,
        "reactions": [],
        "clear_reason": "",
    }


def current_step(plan: Dict) -> Optional[Dict]:
    """当前这一步（[>]）：优先 current_id，其次第一条未完成"""
    steps = plan.get("steps") or []
    if not steps:
        return None
    cur = plan.get("current_id")
    for step in steps:
        if step.get("id") == cur and not step.get("done"):
            return step
    for step in steps:
        if not step.get("done"):
            plan["current_id"] = step.get("id")
            return step
    return None


def first_pending_id(plan: Dict) -> int:
    """第一条未完成步骤的 id（全完成返回 0）"""
    for step in plan.get("steps") or []:
        if not step.get("done"):
            return int(step.get("id") or 0)
    return 0


def is_all_done(plan: Dict) -> bool:
    """计划是否全部完成（没有步骤时不算完成）"""
    steps = plan.get("steps") or []
    return bool(steps) and all(step.get("done") for step in steps)


def _apply_adjust(plan: Dict, rows) -> bool:
    """按 id 替换已有步骤字段；没有 id 的当作新增步骤追加"""
    steps = plan.get("steps") or []
    changed = False
    next_id = max([int(s.get("id") or 0) for s in steps] or [0]) + 1
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        goal = _text(row.get("goal"))
        try:
            sid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            sid = 0
        target = None
        if sid:
            for step in steps:
                if int(step.get("id") or 0) == sid:
                    target = step
                    break
        if target is not None:
            for key in ("goal", "move", "expect", "if_not"):
                value = _text(row.get(key))
                if value:
                    target[key] = value
                    changed = True
            continue
        if not goal:
            continue
        steps.append({
            "id": next_id,
            "goal": goal,
            "move": _text(row.get("move")),
            "expect": _text(row.get("expect")),
            "if_not": _text(row.get("if_not")),
            "done": False,
        })
        next_id += 1
        changed = True
    return changed


def apply_step(plan: Dict, payload: Dict) -> Dict:
    """应用一次 director_step：打标完成 / 调整步骤 / 推进当前 / 记反应 / 判 clear

    返回 {"clear": bool, "reason": str, "changed": bool}
    """
    result = {"clear": False, "reason": "", "changed": False}
    if not isinstance(plan, dict) or not isinstance(payload, dict):
        return result
    steps = plan.get("steps") or []
    if not steps:
        result["clear"] = True
        result["reason"] = "状态损坏"
        return result

    # 1) 打标完成（容忍模型把数组写成单值）
    done_ids = set()
    completed = payload.get("completed")
    if isinstance(completed, (int, float, str)):
        completed = [completed]
    for raw in (completed if isinstance(completed, (list, tuple)) else []):
        try:
            done_ids.add(int(raw))
        except (TypeError, ValueError):
            continue
    for step in steps:
        if int(step.get("id") or 0) in done_ids and not step.get("done"):
            step["done"] = True
            result["changed"] = True

    # 2) 调整/新增步骤（容忍模型把数组写成对象）
    adjust = payload.get("adjust")
    if isinstance(adjust, dict):
        adjust = [adjust]
    if _apply_adjust(plan, adjust if isinstance(adjust, (list, tuple)) else []):
        result["changed"] = True

    # 3) 推进当前步
    try:
        want = int(payload.get("current") or 0)
    except (TypeError, ValueError):
        want = 0
    target = None
    if want:
        for step in steps:
            if int(step.get("id") or 0) == want and not step.get("done"):
                target = step
                break
    if target is not None:
        if plan.get("current_id") != want:
            plan["current_id"] = want
            result["changed"] = True
    else:
        pending = first_pending_id(plan)
        if pending and plan.get("current_id") != pending:
            plan["current_id"] = pending
            result["changed"] = True

    # 4) 记他这一下的反应（只留最近两条）
    reaction = _text(payload.get("reaction"), 120)
    if reaction:
        reactions = list(plan.get("reactions") or [])
        reactions.append(reaction)
        plan["reactions"] = reactions[-MAX_REACTIONS:]
        result["changed"] = True

    # 5) 让位标志
    if "yield_to_user" in payload:
        yield_now = bool(payload.get("yield_to_user"))
        if plan.get("yield_to_user") != yield_now:
            plan["yield_to_user"] = yield_now
            result["changed"] = True

    plan["turns"] = int(plan.get("turns") or 0) + 1
    plan["updated_at"] = _now()

    # 6) 结束判定：工具显式 clear，或全部步骤完成（本地确定性兜底）
    if bool(payload.get("clear")):
        result["clear"] = True
        result["reason"] = _text(payload.get("clear_reason")) or "没意思了"
    elif is_all_done(plan):
        result["clear"] = True
        result["reason"] = "全部完成"
    return result


def render_status(plan: Dict) -> str:
    """把计划渲染成一行行状态（日志/排查用；提示词块由 func/psyche/director_block.py 渲染）"""
    if not isinstance(plan, dict) or not plan.get("active"):
        return ""
    lines = []
    for step in plan.get("steps") or []:
        mark = "[x]" if step.get("done") else (
            "[>]" if step.get("id") == plan.get("current_id") else "[ ]")
        lines.append(f"{mark} {step.get('id')} {step.get('goal')}")
    return "\n".join(lines)
