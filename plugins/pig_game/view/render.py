# -*- coding: utf-8 -*-
"""养猪游戏：消息段拼装与发送。

两种发法
    · 结算类（engine 返回 card）→ 渲染成图片，只发 [@] + [图片]
    · 提示类（参数缺失 / 报错）→ 直接发 [@] + [文字]

@ 段完全照抄主项目 `func/toolbox/napcat/napcat_core/api_client.py::send_group_at_text`：
    message = [{"type": "at", "data": {"qq": str(at_qq)}}]
    if text:
        # @ 与文字之间留一个空格，避免客户端显示粘连
        message.append({"type": "text", "data": {"text": " " + text}})
两个要点：
    1) qq 必须是**字符串**；
    2) @ 段后面**必须再跟一个文本段**（哪怕只有一个空格），否则 QQ 客户端可能把
       @ 当成纯文字显示（也就是「无效艾特」）。发图片时同理，中间垫一个空格段。
"""

import os
import pathlib

PIG_IMAGE = "image.png"      # 猪种图约定文件名：assets/<id>/image.png
SCENE_DIR = "scene"          # 场景图约定：assets/scene/<名字>.png
CARD_FALLBACK = "card.png"


# ============================================================================
# 路径
# ============================================================================
def plugin_root():
    """插件根目录（本文件在 view/ 下，上一级就是根）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fallback_image():
    """缺图兜底：插件卡面 card.png。"""
    path = os.path.join(plugin_root(), CARD_FALLBACK)
    return path if os.path.isfile(path) else None


def resolve_asset(assets_dir, filename):
    """优先 assets/<filename>；文件不存在（或没给名字）时回退 card.png。

    绝不生成灰色占位图 —— 缺图就直接用卡面顶。
    """
    if filename and assets_dir:
        path = os.path.join(assets_dir, filename)
        if os.path.isfile(path):
            return path
    return fallback_image()


def pig_image(cfg, book, species_id):
    """猪种素材：**约定优于配置** —— `assets/<id>/image.png` 放进去就生效。

    想用别的路径，才需要在 assets/<id>/species.json 里显式写 assets.image 覆盖。
    返回的是相对 assets/ 的路径；文件不存在会自动回退 card.png。
    """
    if not species_id:
        return None
    try:
        rel = book.asset(species_id, "image")      # 可选覆盖
    except Exception:
        rel = None
    return rel or f"{species_id}/{PIG_IMAGE}"


def scene_image(cfg, scene):
    """场景素材：约定 `assets/scene/<场景>.png`（相对 assets/）。"""
    if not scene:
        return None
    return f"{SCENE_DIR}/{scene}.png"


def _file_uri(path):
    """本地路径 → file URI（与主项目 _to_file_uri 同逻辑）。"""
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = p.resolve()
    return p.as_uri()


# ============================================================================
# 消息段
# ============================================================================
def _at(qq):
    return {"type": "at", "data": {"qq": str(qq)}}


_SPACE = {"type": "text", "data": {"text": " "}}


def build_segments(message_type, target, uid, text=None, image_path=None, at=True):
    """按主项目口径拼消息段。返回段列表（空表示不发）。"""
    group = str(message_type) == "group"
    segments = []

    if group and at and uid:
        segments.append(_at(uid))
        segments.append(dict(_SPACE))          # ← 有效艾特的保险丝

    if image_path and os.path.isfile(image_path):
        segments.append({"type": "image", "data": {"file": _file_uri(image_path)}})
    elif text:
        if segments:                            # 群聊：空格段直接换成 " " + 正文
            segments[-1] = {"type": "text", "data": {"text": " " + str(text)}}
        else:
            segments.append({"type": "text", "data": {"text": str(text)}})

    if not any(s["type"] in ("image", "text", "face", "record") for s in segments):
        return []
    return segments


def _submit(ctx, message_type, target, segments):
    action = "send_group_msg" if str(message_type) == "group" else "send_private_msg"
    params = {"message": segments}
    if str(message_type) == "group":
        params["group_id"] = int(target)
    else:
        params["user_id"] = int(target)
    try:
        ctx.napcat().call_action_sync(action, params)
        return True
    except Exception:
        try:
            ctx.log.exception("养猪游戏：发送消息失败")
        except Exception:
            pass
        return False


# ============================================================================
# 卡片落盘
# ============================================================================
def _card_path(cache_dir, card):
    import hashlib
    import json
    raw = json.dumps(card, ensure_ascii=False, sort_keys=True).encode("utf-8")
    name = hashlib.md5(raw).hexdigest()[:16] + ".png"
    cache_dir = cache_dir or os.path.join(plugin_root(), "data", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, name)


def render_card(card, cache_dir=None, ctx=None):
    """把 card 数据渲染成 PNG，返回路径；失败返回 None。"""
    try:
        from . import poster
    except Exception:
        try:
            import poster
        except Exception:
            return None
    try:
        out = _card_path(cache_dir, card)
        if not os.path.isfile(out):
            poster.make_card(card, out)
        return out if os.path.isfile(out) else None
    except Exception:
        if ctx is not None:
            try:
                ctx.log.exception("养猪游戏：卡片渲染失败，回退文字")
            except Exception:
                pass
        return None


# ============================================================================
# 对外
# ============================================================================
def send(ctx, qq_context, res, assets_dir=None, cache_dir=None, at=True):
    """发送一条回复。

    res = {"text": str, "image": 素材文件名, "card": {...}, "comment": str}
      · 有 card → 渲染图片，只发 [@] + [图片]
      · 没有 card（参数缺失 / 报错）→ 只发 [@] + [文字]
      · 有 card 但渲染失败 → 回退发文字，绝不让玩家收不到反馈
    """
    qq_context = dict(qq_context or {})
    message_type = str(qq_context.get("message_type") or "private")
    uid = str(qq_context.get("user_id") or "")
    target = str(qq_context.get("target_id") or uid or "")
    if not target:
        return False

    if not isinstance(res, dict):
        res = {"text": str(res or "")}
    text = str(res.get("text") or "")

    card = res.get("card")
    if card:
        data = dict(card)
        data["img"] = resolve_asset(assets_dir, res.get("image")) or ""
        if res.get("comment"):
            data["comment"] = str(res["comment"])
        png = render_card(data, cache_dir, ctx)
        if png:
            segs = build_segments(message_type, target, uid, image_path=png, at=at)
            if segs:
                return _submit(ctx, message_type, target, segs)

    segs = build_segments(message_type, target, uid, text=text, at=at)
    if not segs:
        return False
    return _submit(ctx, message_type, target, segs)
