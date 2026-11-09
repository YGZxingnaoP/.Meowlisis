# -*- coding: utf-8 -*-
# func/pipeline/deep_recall_core.py
# 深度回忆编排（平台无关）：严格判官 → 摘要优先取数 → 只读工具循环 → 续写一段

import json
import time

from func.log.default_log import DefaultLog
from func.pipeline.config_reader import ConfigReader
from func.catbrain.AbstractMem.process.deep_recall import MeowDeepRecallEvidence

JUDGE_TOOL_NAME = "deep_recall_judge"

JUDGE_TOOL = {
    "type": "function",
    "function": {
        "name": JUDGE_TOOL_NAME,
        "description": (
            "判断要不要在已经回复之后，再深入回忆并多说一点。只做判断，不写正文；必须调用本工具。\n"
            "need=true 仅限：对方明确在问你怎么看他/你们的关系/以前发生的事/还记不记得某件事/"
            "让你根据回忆多说；或今天是TA生日。\n"
            "need=false：普通问答、闲聊、求助工具、情绪宣泄、事实查询、拿不准。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "need": {"type": "boolean", "description": "是否需要再深入回忆并补充"},
                "kind": {"type": "string",
                         "enum": ["self_view", "shared_past", "remember", "birthday", "other"]},
                "reason": {"type": "string", "description": "判断依据，必须引用原话片段"},
                "query": {"type": "string", "description": "要回忆什么（关键词/事件）"},
                "months": {"type": "array", "items": {"type": "string"},
                           "description": "明确提到的时间窗口（YYYY-MM，可空）"},
            },
            "required": ["need", "reason"],
        },
    },
}


def load_options(scope: str = "llm") -> dict:
    """读取 llm.deep_recall / napcat.deep_recall；缺省值按“严格但默认开启”"""
    root = ConfigReader().get() or {}
    if str(scope) == "qq":
        node = (root.get("napcat", {}) or {}).get("deep_recall", {}) or {}
    else:
        node = (root.get("llm", {}) or {}).get("deep_recall", {}) or {}
    return {
        "enabled": bool(node.get("enabled", True)),
        "judge_max_tokens": int(node.get("judge_max_tokens", 160) or 160),
        "max_rounds": int(node.get("max_rounds", 12) or 12),
        "prompt_rounds": int(node.get("prompt_rounds", 9) or 9),
        "timeout_s": float(node.get("timeout_s", 20) or 20),
        "max_extra_chars": int(node.get("max_extra_chars", 180) or 180),
        "max_evidence_chars": int(node.get("max_evidence_chars", 6000) or 6000),
        "raw_days": int(node.get("raw_days", 7) or 7),
        "raw_limit": int(node.get("raw_limit", 30) or 30),
        "summary_limit": int(node.get("summary_limit", 6) or 6),
        "max_messages": int(node.get("max_messages", 2) or 2),
    }


def chat_complete(port, messages, tools=None, tool_choice=None, max_tokens: int = 512) -> dict:
    """统一“非流式结果”：优先 port.chat，没有就累计 chat_stream"""
    if port is None or not getattr(port, "client", None):
        return {"content": "", "calls": []}
    if hasattr(port, "chat"):
        old_max = getattr(port, "max_tokens", None)
        try:
            if old_max is not None:
                port.max_tokens = max(int(old_max), int(max_tokens))
            try:
                resp = port.chat(messages, tools=tools, tool_choice=tool_choice,
                                 enable_thinking=False)
            except TypeError:
                resp = port.chat(messages, tools=tools, tool_choice=tool_choice)
            return _read_resp(resp)
        finally:
            if old_max is not None:
                port.max_tokens = old_max
    try:
        stream = port.chat_stream(messages, tools=tools, tool_choice=tool_choice,
                                  options={"max_tokens": max_tokens},
                                  enable_thinking=False)
    except TypeError:
        stream = port.chat_stream(messages, tools=tools, tool_choice=tool_choice,
                                  options={"max_tokens": max_tokens})
    from func.pipeline.llm_toolbox import ToolCallAccumulator
    acc = ToolCallAccumulator()
    content = ""
    try:
        for chunk in stream or []:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                content += delta.content
            if getattr(delta, "tool_calls", None):
                acc.add(delta.tool_calls)
    except Exception:
        DefaultLog().getLogger().exception("[深度回忆] 流式读取失败")
    return {"content": str(content or "").strip(),
            "calls": acc.payload() if acc.has_calls() else []}


def _read_resp(resp) -> dict:
    if not resp or not getattr(resp, "choices", None):
        return {"content": "", "calls": []}
    msg = resp.choices[0].message
    calls = []
    for idx, tc in enumerate(getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        calls.append({
            "id": getattr(tc, "id", "") or f"call_{idx}",
            "type": "function",
            "function": {"name": str(getattr(fn, "name", "") or ""),
                         "arguments": str(getattr(fn, "arguments", "") or "{}")},
        })
    return {"content": str(getattr(msg, "content", "") or "").strip(), "calls": calls}


def judge(chat_fn, uid: str, user_text: str, quick_reply: str,
          birthday: bool = False, opts: dict = None) -> dict:
    """严格判官：只认明确回忆/看法/生日；拿不准 false"""
    opts = opts or {}
    empty = {"need": False, "kind": "", "reason": "", "query": "", "months": []}
    if not opts.get("enabled", True):
        return empty
    if birthday:
        return {"need": True, "kind": "birthday", "reason": "今天是TA生日",
                "query": "生日 之前一起做过的事", "months": []}
    system = (
        "你在判断：已经回了一句之后，要不要再深入回忆并多补充一点。只做判断，不写正文。\n"
        "【need=true 仅限】\n"
        "1. 对方明确在问“你怎么看我/你觉得我怎么样/我们之间/我们以前/你还记得吗/那次/那时候”；\n"
        "2. 对方明确要你根据你们发生过的事多说一点；\n"
        "3. 今天是TA生日。\n"
        "【need=false】\n"
        "- 普通问答、闲聊、吐槽、撒娇、角色扮演、求安慰；\n"
        "- 事实查询、让角色做事/调用工具；\n"
        "- 只是随口问“你觉得呢”，没有真的在问关系/过去；\n"
        "- 拿不准。\n"
        "reason 必须引用原话片段；query 写要回忆的关键词/事件。"
        f"必须调用 {JUDGE_TOOL_NAME}。"
    )
    user = (f"【TA这条消息】\n{str(user_text or '')[:800]}\n\n"
            f"【你刚才的回复】\n{str(quick_reply or '')[:600]}\n\n"
            f"只判断是否需要深入回忆。必须调用 {JUDGE_TOOL_NAME}。")
    try:
        resp = chat_fn([{"role": "system", "content": system},
                        {"role": "user", "content": user}],
                       [JUDGE_TOOL], {"type": "function",
                                      "function": {"name": JUDGE_TOOL_NAME}},
                       int(opts.get("judge_max_tokens") or 160))
    except Exception:
        DefaultLog().getLogger().exception("[深度回忆] 判官调用失败")
        return empty
    for call in resp.get("calls") or []:
        fn = call.get("function") or {}
        if str(fn.get("name") or "") != JUDGE_TOOL_NAME:
            continue
        try:
            data = json.loads(fn.get("arguments") or "{}")
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        months = [str(m).strip() for m in (data.get("months") or []) if str(m).strip()]
        return {"need": bool(data.get("need")),
                "kind": str(data.get("kind") or ""),
                "reason": str(data.get("reason") or "").strip(),
                "query": str(data.get("query") or "").strip(),
                "months": months}
    return empty


def build_system(uid: str, opts: dict, persona: str = "", birthday: bool = False) -> str:
    rounds = max(1, int(opts.get("prompt_rounds") or 9))
    limit = max(40, int(opts.get("max_extra_chars") or 180))
    parts = [
        persona or "",
        "# 现在是“深度回忆”工作流",
        "你刚才已经回过一句了。现在不是重写那句，也不是把记忆整段念出来；"
        "你要先自己决定查什么记忆，查完再直接说 1~3 句更具体的话。",
        "工作流：\n"
        "1. 先用 recall_memory 查记忆摘要（优先）；\n"
        "2. 摘要不够，再用 search_chat / read_chat_day 看具体那一天的原文；\n"
        "3. 查够了就直接开口，不要解释“我查了什么”，不要列清单。",
        f"你最多有 {rounds} 轮工具调用。不要重复查同一件事；查不到就凭你们已有的关系说一句，不要编。",
        f"最终补充不超过 {limit} 字；不要重复刚才的话；不要提“根据记忆/摘要/档案”；不要用序号。",
        "只补充记忆里真实存在的事；专名、称呼、数字、时间不要改。",
    ]
    if birthday:
        parts.append("今天是TA的生日：可以结合你记得的旧事说一句具体的祝福，不要泛泛地说“生日快乐”。")
    return "\n\n".join(p for p in parts if p)


def build_user(user_text: str, quick_reply: str) -> str:
    return (f"【TA说的】\n{str(user_text or '')[:1000]}\n\n"
            f"【你刚才回的】\n{str(quick_reply or '')[:800]}\n\n"
            "现在补充 1~3 句更具体的内容；不要重复刚才的话，不要解释。")


def _clip(text: str, limit: int) -> str:
    """按字数上限截断，优先保留完整句子"""
    s = str(text or "").strip()
    limit = max(40, int(limit))
    if len(s) <= limit:
        return s
    head = s[:limit]
    pos = max(head.rfind("。"), head.rfind("\n"))
    if pos >= max(8, limit // 3):
        return head[:pos + 1].strip()
    return head.strip()


def run(chat_fn, uid: str, user_text: str, quick_reply: str,
        opts: dict = None, persona: str = "", emit=None,
        query: str = "", stop=None, birthday: bool = False) -> str:
    """深度回忆 agent：先查摘要，再按需查原文，最后直接开口（不预注入记忆）"""
    opts = opts or {}
    log = DefaultLog().getLogger()
    if not opts.get("enabled", True):
        return ""
    evidence = MeowDeepRecallEvidence(
        uid, query or user_text,
        summary_limit=opts.get("summary_limit", 6),
        raw_days=opts.get("raw_days", 7),
        raw_limit=opts.get("raw_limit", 30))
    tools = evidence.build_tools()
    rounds = max(1, int(opts.get("max_rounds") or 12))
    limit = max(40, int(opts.get("max_extra_chars") or 180))
    cap = max(500, int(opts.get("max_evidence_chars") or 6000))
    messages = [
        {"role": "system", "content": build_system(uid, opts, persona, birthday=birthday)},
        {"role": "user", "content": build_user(user_text, quick_reply)},
    ]
    deadline = time.time() + max(3.0, float(opts.get("timeout_s") or 20))
    forced_recall = {"type": "function", "function": {"name": "recall_memory"}}
    used = 0
    for idx in range(rounds):
        if stop is not None and stop():
            return ""
        if time.time() > deadline:
            log.warning("[深度回忆] 工具循环超时，停止补读")
            break
        # 第一轮强制先查摘要（摘要优先）；之后由模型自己决定要不要看原文
        choice = forced_recall if idx == 0 else "auto"
        resp = chat_fn(messages, tools, choice, 700)
        calls = resp.get("calls") or []
        content = str(resp.get("content") or "").strip()
        if not calls:
            if content:
                final = _clip(content, limit)
                if final and emit and (stop is None or not stop()):
                    emit(final)
                return final
            break
        messages.append({
            "role": "assistant", "content": content or "",
            "tool_calls": calls,
        })
        for call in calls:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            args = fn.get("arguments") or "{}"
            result = evidence.dispatch(name, args)
            if used >= cap:
                result = "（记忆结果已达上限，不再继续读）"
            elif used + len(result) > cap:
                result = result[:max(0, cap - used)] + "\n（记忆结果已截断）"
            used += len(result)
            messages.append({"role": "tool",
                             "tool_call_id": call.get("id") or "call_0",
                             "content": result})
            if used >= cap:
                break
    if stop is not None and stop():
        return ""
    resp = chat_fn(
        messages + [{"role": "user", "content": "用你自己的语气，把刚才回忆到的内容自然地说出来。不要调用工具，不要解释。"}],
        None, None, 400)
    final = _clip(str(resp.get("content") or "").strip(), limit)
    if final and emit and (stop is None or not stop()):
        emit(final)
    return final
