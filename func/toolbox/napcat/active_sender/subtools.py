# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/subtools.py
# QQ 链路内部子工具：只读取数（好友/群/群成员/文件搜索/链接校验）+ 终态发送动作。
#
# 层级约定：
#   * 父级只暴露 napcat_send / napcat_ask_bot 两个动作入口；
#   * 本文件的任何东西都不注册到父级工具表（analysis.SUBTOOL_BLOCKLIST 会拒绝）；
#   * 「查群名 / 查 @ 成员」这类查找全部在链路内部由模块自己触发这里的方法完成，
#     解析不出来或出现歧义时不猜、不瞎发，由模块发起 excuse 向用户追问。

from typing import Dict, Optional, Tuple

# 只读子工具：取数 / 解析
READ_TOOLS = (
    "get_friend_list", "get_group_list", "get_group_member_list",
    "search_file", "check_link",
)

# 终态子工具：真正产生副作用的发送动作
ACTION_TOOLS = (
    "send_qq_message", "send_qq_link", "send_qq_image",
    "send_qq_file", "send_qq_chat_record", "send_qq_at",
)


# ==================== 内容归类 ====================
def direct_content(content_type: str, text: str, url: str, file_path: str) -> dict:
    """把上层直传的内容字段归类为 {type, text, url, file_path}"""
    ct = str(content_type or "").strip().lower()
    t = str(text or "").strip()
    u = str(url or "").strip()
    f = str(file_path or "").strip()
    if ct not in ("text", "link", "file", "image"):
        ct = "link" if u else ("file" if f else ("text" if t else ""))
    out = {"type": ct, "text": "", "url": "", "file_path": ""}
    if ct == "text":
        out["text"] = t
    elif ct == "link":
        out["url"] = u
        out["text"] = t
    elif ct in ("file", "image"):
        out["file_path"] = f
    return out


# ==================== 目标查找（内部子工具，零 LLM） ====================
def resolve_group(value) -> Tuple[Optional[str], str]:
    """群号/群名 → 群号；返回 (group_id, err)，err 里带候选群便于追问"""
    from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList
    return TBGetGroupList().resolve_id(value)


def find_friend(query) -> Tuple[Optional[str], str, list]:
    """好友搜索：拉全量好友列表 → 归一化/拼音/相似度排序 → 命中或给候选

    返回 (user_id 或 None, 失败原因, 候选 [(分数, 名字)])。
    多个都像、只有错字级相似时不会自己挑一个发，交给追问确认。
    """
    from func.toolbox.napcat.active_sender.get_friendlist import TBGetFriendList
    raw = str(query or "").strip()
    if not raw:
        return None, "还不知道这条消息要发给谁", []
    if raw.isdigit():
        return raw, "", []
    fl = TBGetFriendList()
    rows = fl.get()
    if not rows:
        detail = str(getattr(fl, "last_error", "") or "").strip()
        return None, "好友列表拉不到" + (f"（{detail}）" if detail else ""), []
    from func.toolbox.napcat.active_sender.target_search import pick

    def _name(row):
        return str(row.get("remark") or "").strip() or str(row.get("nickname") or "").strip()

    item, candidates = pick(raw, rows, _name)
    if item is not None:
        return str(item.get("user_id") or ""), "", candidates
    return None, f"好友里没有能确定是「{raw}」的人", candidates


def find_group(query) -> Tuple[Optional[str], str, list]:
    """群搜索：拉全量群列表 → 归一化/拼音/相似度排序 → 命中或给候选

    返回 (group_id 或 None, 失败原因, 候选 [(分数, 名字)])。
    """
    from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList
    raw = str(query or "").strip()
    if not raw:
        return None, "还不知道这条消息要发到哪个群", []
    if raw.isdigit():
        return raw, "", []
    gl = TBGetGroupList()
    rows = gl.get()
    if not rows:
        return None, "群列表拉不到（NapCat 未连接或超时）", []
    from func.toolbox.napcat.active_sender.target_search import pick
    item, candidates = pick(raw, rows, lambda row: str(row.get("group_name") or ""))
    if item is not None:
        return str(item.get("group_id") or ""), "", candidates
    return None, f"群列表里没有能确定是「{raw}」的群", candidates


def find_member(group_id, name) -> Optional[dict]:
    """按群名片/昵称/QQ 号查群成员；QQ 号直接构造结果"""
    from func.toolbox.napcat.active_sender.get_group_memberlist import TBGetGroupMemberList
    target = str(name or "").strip()
    if not target:
        return None
    if target.isdigit():
        return {"user_id": target, "card": "", "nickname": target}
    return TBGetGroupMemberList().find_by_name(group_id, target)


def _candidates(names: list, query: str = "", limit: int = 12) -> str:
    """候选名提示：先按用户说的词过滤，再截断；超限时给出总数

    limit 只影响「追问时展示几个」，与解析/发送无关（解析走全量列表）。
    给了 query 且在列表里完全找不到相似项时返回空串——不拿无关的名字凑数。
    """
    cleaned = [str(n or "").strip() for n in names if str(n or "").strip()]
    q = str(query or "").strip()
    if q:
        matched = [n for n in cleaned if q in n or n in q]
        if not matched:
            return ""
        cleaned = matched
    if not cleaned:
        return ""
    shown = "、".join(cleaned[:limit])
    total = len(cleaned)
    return shown + (f"…（共{total}个）" if total > limit else "")


def member_names(group_id, query: str = "", limit: int = 12) -> str:
    """群成员候选名（追问时附在问题里；@ 链路命中规则不变，这里只做展示筛选）"""
    from func.toolbox.napcat.active_sender.get_group_memberlist import TBGetGroupMemberList
    rows = TBGetGroupMemberList().get(group_id)
    names = [str(row.get("card") or row.get("nickname") or row.get("user_id") or "")
             for row in rows]
    return _candidates(names, query, limit)


# ==================== 内部 LLM（拟稿用） ====================
def toolbox_llm():
    """QQ 链路内部 LLM：沿用 toolbox 独立配置"""
    from func.toolbox.config import TBoxConfig
    cfg = TBoxConfig()
    if cfg.llm_type == "meowllm":
        from func.toolbox.port.meowllm import TBoxMeowLLM
        return TBoxMeowLLM(cfg)
    if cfg.llm_type == "gemini":
        from func.toolbox.port.gemini import TBoxGeminiLLM
        return TBoxGeminiLLM(cfg)
    if cfg.llm_type == "aliyun":
        from func.toolbox.port.aliyun import TBoxAliyunLLM
        return TBoxAliyunLLM(cfg)
    from func.toolbox.port.deepseek import TBoxDeepSeekLLM
    return TBoxDeepSeekLLM(cfg)


# 拟稿指令：只在「只有意图、没有现成内容」时用，产出的是发给对方的消息正文
DRAFT_HINT = """【当前任务：替主人发一条 QQ 消息，先把正文写出来】
- 以你自己的身份、自己的口吻写，不是复述主人的要求；
- 只输出要发送的消息正文本身：不要解释、不要加引号、不要写「好的/我就发/已发送」、不要带说话人或【】前缀；
- 口语化、简短，像在 QQ 里直接说话；对方能一眼看懂；
- 内容贴住主人的要求，不要自作主张加无关话题。"""


def draft_prompt(meowid: str, request: str) -> str:
    """拟稿用系统提示词：角色人设（前置词+角色卡+价值观+后置词）+ 拟稿指令"""
    base = ""
    try:
        from func.toolbox.get_prompt import TBoxGetPrompt
        base = TBoxGetPrompt().get_tool_prompt(meowid, request) or ""
    except Exception:
        base = ""
    return f"{base}\n\n{DRAFT_HINT}" if base else DRAFT_HINT


# ==================== 子工具执行 ====================
def _send_at(args: Dict) -> str:
    from func.toolbox.napcat.active_sender.sender import TBSender
    gid, err = resolve_group((args or {}).get("group_id"))
    if not gid:
        return f"发送失败：{err}"
    # 已解析出 QQ 号时直接用，避免重复查成员列表
    member_qq = str((args or {}).get("user_id") or "").strip()
    if member_qq:
        text = str((args or {}).get("text") or "")
        return TBSender().send_group_at(gid, member_qq, text)
    member = str((args or {}).get("member") or "").strip()
    row = find_member(gid, member)
    if not row:
        return f"发送失败：群 {gid} 里没找到成员「{member}」"
    text = str((args or {}).get("text") or "")
    return TBSender().send_group_at(gid, row.get("user_id"), text)


def dispatch(name: str, arguments: Dict) -> str:
    """执行一个内部子工具（只读或发送动作），返回结果字符串"""
    args = arguments or {}
    from func.toolbox.napcat.active_sender.sender import TBSender
    if name == "send_qq_at":
        result = _send_at(args)
    elif name == "get_group_member_list":
        from func.toolbox.napcat.active_sender.get_group_memberlist import TBGetGroupMemberList
        result = TBGetGroupMemberList().dispatch_subtool(name, args)
    else:
        result = TBSender().dispatch(name, args)
    if name in ACTION_TOOLS and result and not str(result).startswith("发送失败"):
        try:
            TBSender.mark_active_send()
        except Exception:
            pass
    return result
