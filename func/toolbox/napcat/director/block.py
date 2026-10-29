# -*- coding: utf-8 -*-
# func/toolbox/napcat/director/block.py
# QQ 导演提示词块：把当前走向渲染成「当前对话走向（QQ·简化版）」，附在 QQ 提示词末尾
# 本模块只读 QQ 自己的状态，不引用主链路/心理状态机。

from func.log.default_log import DefaultLog
from func.toolbox.napcat.director.config import QQDirectorConfig
from func.toolbox.napcat.director.store import QQDirectorStore


def render_block(session: str) -> str:
    """渲染 QQ 走向块；没有激活的走向（或总开关关闭）时返回空串"""
    if not QQDirectorConfig().enabled:
        return ""
    plan = QQDirectorStore().get(session)
    if not plan or not plan.get("active"):
        return ""
    steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return ""
    current_id = plan.get("current_id")
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
    is_group = str(plan.get("channel") or "") == "group"

    lines = [
        "# 当前对话走向（QQ·简化版）",
        "（只在 @ / 私聊生效；一次只做一步，别把清单念出来）",
        "",
        "```text",
    ]
    brief = str((plan.get("material") or {}).get("brief") or "").strip()
    if brief:
        lines.append(f"由头：{brief}")
        lines.append("（这是之前分享过的视频，可以拿来当话头，别照着念）")
    if done:
        lines.append("已经完成：")
        for step in done:
            lines.append(f"  [x] {step.get('id')} {step.get('goal')}")
    if current is not None:
        lines.append("当前这一步：")
        lines.append(f"  [>] {current.get('id')} {current.get('goal')}")
    if after:
        lines.append("之后还有：")
        for step in after:
            lines.append(f"  [ ] {step.get('id')} {step.get('goal')}")
    lines.extend([
        "规矩：",
        "  · " + ("群聊时面向全群，别只对一个人" if is_group else "这是私聊，只对他一个人说"),
        "  · 对方有明确话题就先跟他的，别硬拽",
        "  · 一次只走一步，别一口气说完",
        "  · 对方说别烦 / 不想听 → 收",
        "```",
    ])
    return "\n".join(lines)


def attach_block(prompt: str, session: str) -> str:
    """把走向块附到提示词末尾；没有走向时原样返回"""
    try:
        block = render_block(session)
    except Exception:
        DefaultLog().getLogger().exception("[QQ导演] 渲染走向块失败")
        return prompt
    if not block:
        return prompt
    return f"{prompt}\n\n{block}" if prompt else block
