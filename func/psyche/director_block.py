# -*- coding: utf-8 -*-
# func/psyche/director_block.py
# 导演状态 → 系统提示词块：「当前对话走向」（插在「我心里装着的」下方）
# 心理状态机负责提示词的整理与插入；本文件只读导演桥接，不 import 导演模块。

from func.log.default_log import DefaultLog


def render_director_block(scope: str = "main") -> str:
    """渲染导演块；未激活 / 无步骤时返回空串"""
    if str(scope or "main") != "main":
        return ""
    try:
        from func.pipeline.llm_director import LLMDirectorBridge
        state = LLMDirectorBridge().get("main")
    except Exception:
        DefaultLog().getLogger().exception("读取导演状态失败")
        return ""
    if not state or not state.get("active"):
        return ""
    steps = [s for s in (state.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return ""

    current_id = state.get("current_id")
    current = None
    for step in steps:
        if step.get("id") == current_id and not step.get("done"):
            current = step
            break
    if current is None:
        for step in steps:
            if not step.get("done"):
                current = step
                break

    done = [s for s in steps if s.get("done")]
    after = [s for s in steps if not s.get("done") and s is not current]

    lines = [
        "# 当前对话走向（必须照做）",
        "（这不是背景，是命令。每次开口前先看这里：只演[>]这一步，一次只走一步，"
        "绝不允许一口气把后面全说完；主人有明确话题就先跟他的话题，别抢；这份清单不许念出来）",
        "",
        "```text",
    ]
    brief = str((state.get("material") or {}).get("brief") or "").strip()
    if brief:
        lines.append(f"由头：{brief}")
        lines.append("（由头只是引子，不是台词：不许照着复述，也不许一次讲完）")
    if state.get("yield_to_user"):
        lines.append("（主人现在有明确话题：先跟他的，这条先挂着，别硬拽）")
    if done:
        lines.append("已经完成：")
        for step in done:
            lines.append(f"  [x] {step.get('id')} {step.get('goal')}{_move_tag(step)}")
    if current is not None:
        lines.append("当前这一步（只说这个）：")
        lines.append(f"  [>] {current.get('id')} {current.get('goal')}")
        detail = _detail_line(current)
        if detail:
            lines.append(f"      {detail}")
    if after:
        lines.append("之后还有：")
        for step in after:
            lines.append(f"  [ ] {step.get('id')} {step.get('goal')}{_move_tag(step)}")
    reactions = [str(r).strip() for r in (state.get("reactions") or []) if str(r).strip()]
    if reactions:
        lines.append("他刚才的反应：")
        for text in reactions[-2:]:
            lines.append(f"  {text}")
    lines.extend([
        "规矩：",
        "  · 不许冷笑话",
        "  · 不许说「第一步第二步」，不许把这份清单念出来",
        "  · 这一步说出口就算完成；他没接，就按这一步的「他不这样就把话拉回来」改说法",
        "  · 要讲由头就讲具体那一处（画面 / 台词），别只说「一个东西」",
        "  · 每次说完必须调用 director_step 交回进度",
        "  · 他说不要打扰 / 不想听 → clear=true 立刻收",
        "```",
    ])
    return "\n".join(lines)


def _move_tag(step: dict) -> str:
    """已完成/之后步骤的招法标注（让整份规划都在提示词里可见）"""
    move = str(step.get("move") or "").strip()
    return f"（招法：{move}）" if move else ""


def _detail_line(step: dict) -> str:
    """当前步的招法/预期/兜底（都是行为指导，不是台词）"""
    parts = []
    if str(step.get("move") or "").strip():
        parts.append(f"招法：{str(step.get('move')).strip()}")
    if str(step.get("expect") or "").strip():
        parts.append(f"猜他会：{str(step.get('expect')).strip()}")
    if str(step.get("if_not") or "").strip():
        parts.append(f"他不这样就把话拉回来：{str(step.get('if_not')).strip()}")
    return "；".join(parts)
