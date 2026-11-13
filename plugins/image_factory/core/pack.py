# -*- coding: utf-8 -*-
"""把图片打包成一条 QQ 聊天记录（合并转发），末尾附打赏码。"""

import os


def _file_uri(path):
    """本地路径 → NapCat 能读的 file:// URI。"""
    p = os.path.abspath(str(path or ""))
    return "file:///" + p.replace("\\", "/").lstrip("/")


def _image_seg(path):
    """单张图片的消息段。"""
    return {"type": "image", "data": {"file": _file_uri(path)}}


def _client(ctx):
    """兼容两种入参：框架 ctx（有 napcat()）或直接的 napcat 客户端。"""
    if hasattr(ctx, "napcat"):
        return ctx.napcat()
    return ctx


def build_nodes(images, sender="图片工厂", uin="", pay_image=""):
    """构造合并转发节点：每张图一条，最后一条是打赏码。"""
    nodes = []
    for path in (images or []):
        if not path or not os.path.isfile(path):
            continue
        nodes.append({"type": "node",
                      "data": {"name": sender, "uin": str(uin or ""),
                               "content": [_image_seg(path)]}})
    if pay_image and os.path.isfile(pay_image):
        nodes.append({"type": "node",
                      "data": {"name": sender, "uin": str(uin or ""),
                               "content": [_image_seg(pay_image)]}})
    return nodes


def _ok(resp):
    """NapCat 返回是否算成功。"""
    if isinstance(resp, dict):
        if resp.get("status") in ("ok", "async"):
            return True
        if resp.get("retcode") in (0, None) and resp.get("data") is not None:
            return True
        return bool(resp.get("message_id") or resp.get("message_seq"))
    return bool(resp)


def _why(resp):
    """把失败原因压成一行文本。"""
    if isinstance(resp, dict):
        return str(resp.get("message") or resp.get("wording") or resp.get("msg")
                   or resp.get("retcode") or resp)[:200]
    return str(resp)[:200]


def send(ctx, qq_context, images, pay_image="", sender="图片工厂",
         fallback_single=True):
    """发一条聊天记录（失败可退回逐张）；返回 (ok, detail)。"""
    qq = dict(qq_context or {})
    target = str(qq.get("target_id") or qq.get("group_id") or qq.get("user_id") or "")
    if not target or not images:
        return False, "缺少目标或图片"
    is_group = str(qq.get("message_type") or "") == "group"
    self_id = str(qq.get("self_id") or "")
    nodes = build_nodes(images, sender=sender, uin=self_id, pay_image=pay_image)
    if not nodes:
        return False, "没有可发送的图片"

    action = "send_group_forward_msg" if is_group else "send_private_forward_msg"
    params = {"group_id": target, "messages": nodes} if is_group \
        else {"user_id": target, "messages": nodes}
    detail = ""
    try:
        resp = _client(ctx).call_action_sync(action, params, timeout=30)
        if _ok(resp):
            return True, "合并转发已发送（%d 条）" % len(nodes)
        detail = _why(resp)
    except Exception as e:
        detail = "%s: %s" % (type(e).__name__, e)

    if not fallback_single:
        return False, detail
    sent = 0
    try:
        core = _client(ctx)
        for path in images:
            if not path or not os.path.isfile(path):
                continue
            if is_group:
                core.send_group_image(target, path)
            else:
                core.send_private_image(target, path)
            sent += 1
    except Exception as e:
        return False, "合并转发失败(%s)，逐张也失败: %s" % (detail, e)
    return sent > 0, "合并转发失败(%s)，已改为逐张发送 %d 张" % (detail, sent)
