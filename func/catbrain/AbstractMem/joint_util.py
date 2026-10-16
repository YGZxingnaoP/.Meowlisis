# -*- coding: utf-8 -*-
import re

PAIR_RE = re.compile(r"^(?P<nickname>.*?)\s*[（(]\s*(?P<uid>\d{6})\s*[)）]\s*$")


def _bridge():
    try:
        from func.pipeline.id_signup import IdSignupBridge
        return IdSignupBridge()
    except Exception:
        return None


def uid_of(name):
    """按昵称查编号，查不到回空串"""
    text = str(name or "").strip()
    if not text:
        return ""
    if len(text) == 6 and text.isdigit():
        return text
    match = PAIR_RE.match(text)
    if match:
        return match.group("uid")
    bridge = _bridge()
    if not bridge:
        return ""
    try:
        return bridge.id_by_name(text) or ""
    except Exception:
        return ""


def resolve(value):
    """把一条参与人整成 {"meowid": 编号, "nickname": 昵称}"""
    if isinstance(value, dict):
        uid = str(value.get("meowid") or "").strip()
        nickname = str(value.get("nickname") or "").strip()
        return {"meowid": uid, "nickname": nickname or uid}
    text = str(value or "").strip()
    uid = ""
    match = PAIR_RE.match(text)
    if match:
        text = match.group("nickname").strip()
        uid = match.group("uid")
    if not uid:
        uid = uid_of(text)
    if uid:
        # 展示名唯一规则：有编号一律按编号取昵称，禁止用文本里猜到的名字兜底
        from func.pipeline.id_signup import display_name
        text = display_name(uid)
    return {"meowid": uid, "nickname": text}


def key_of(entry):
    """取一条参与人的去重键：有编号用编号，没有就用昵称"""
    if isinstance(entry, dict):
        return str(entry.get("meowid") or "").strip() or str(entry.get("nickname") or "").strip()
    return str(entry or "").strip()


def normalize(values):
    """规范 joint 列表为 [{id, nickname}]，去重保序"""
    if isinstance(values, (str, dict)):
        values = [values]
    result = []
    keys = set()
    for v in (values or []):
        entry = resolve(v)
        if not (entry["meowid"] or entry["nickname"]):
            continue
        key = entry["meowid"] or entry["nickname"]
        if key in keys:
            continue
        keys.add(key)
        result.append(entry)
    return result


def merge(current, values):
    """把两个 joint 列表并起来去重"""
    return normalize(list(current or []) + list(values or []))


def match(item, uid="", nickname=""):
    """当前说话人是不是这条记忆的参与人：有条目编号就比编号，没编号才比昵称"""
    uid = str(uid or "").strip()
    nickname = str(nickname or "").strip()
    if not uid and not nickname:
        return False
    for entry in ((item or {}).get("joint") or []):
        if isinstance(entry, dict):
            eid = str(entry.get("meowid") or "").strip()
            ename = str(entry.get("nickname") or "").strip()
        else:
            eid, ename = "", str(entry or "").strip()
        if eid:
            if uid and eid == uid:
                return True
            continue
        if ename and nickname and ename == nickname:
            return True
    return False


def owner(item):
    """取首个参与人（用于事件主键，优先编号）"""
    joint = (item or {}).get("joint") or []
    if not joint:
        return ""
    entry = resolve(joint[0])
    return entry["meowid"] or entry["nickname"]


def text(item):
    """拼成给提示词看的「昵称(编号)」串"""
    parts = []
    for entry in ((item or {}).get("joint") or []):
        one = resolve(entry)
        if one["meowid"] and one["nickname"] and one["meowid"] != one["nickname"]:
            parts.append(f"{one['nickname']}({one['meowid']})")
        else:
            parts.append(one["nickname"] or one["meowid"])
    return "、".join(p for p in parts if p)
