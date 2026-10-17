# -*- coding: utf-8 -*-
"""QQ 主动发送链路自检（真实发送 + 打印原始 OneBot 响应）

用法：
    python scripts/qq_send_check.py                  # 只查状态：连接/好友表里有没有"卡戎星"，不发消息
    python scripts/qq_send_check.py send <QQ号> "文本"  # 真发一条私聊，并打印原始响应
    python scripts/qq_send_check.py group <群号> "文本"  # 真发一条群消息

安全说明：
    · 只建最小连接（TBNapCatConnection + TBNapCatApiClient），**不绑定任何事件回调**
      → 本脚本不会接收/回复任何 QQ 消息（用 TBNapCatCore 门面会绑定事件处理，故不用它）。
    · 不打印 access_token；好友表只打印与关键词相关的少数条目。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.napcat_core.connection import TBNapCatConnection
from func.toolbox.napcat.napcat_core.api_client import TBNapCatApiClient

KEY = sys.argv[1] if len(sys.argv) > 1 else ""
TARGET = sys.argv[2] if len(sys.argv) > 2 else "1149942002"
TEXT = sys.argv[3] if len(sys.argv) > 3 else "【发送链路自检】这条消息由 scripts/qq_send_check.py 直连 NapCat 发出，收到即说明发送链路正常。"

log = DefaultLog().getLogger()
cfg = TBNapCatConfig()
print("===== 配置状态 =====")
print("  napcat.enabled          = %s" % cfg.enabled)
print("  ws_url                  = %s" % cfg.ws_url)
print("  access_token 已配置     = %s" % bool(cfg.access_token))
print("  active_sender.enabled   = %s   cooldown=%ss" % (cfg.active_send_enabled, cfg.active_send_cooldown))
print("")

if not cfg.enabled:
    print("!! napcat.enabled=false，发送链路整体关闭，工具自然发不出去")
    sys.exit(0)

conn = TBNapCatConnection(log, cfg)          # 不绑定任何事件回调
api = TBNapCatApiClient(log, cfg, conn)
conn.start()
print("正在连接 %s ..." % cfg.ws_url)
for _ in range(30):
    time.sleep(0.5)
    if conn.ws is not None:
        break
print("  ws 已连接 = %s" % (conn.ws is not None))
print("  事件循环就绪 = %s" % conn._loop_ready.is_set())
if conn.ws is None:
    print("!! 连不上 NapCat：这正是'发送静默失败'的第一种原因（call_action_sync 此时返回 None 且不报错）")
    sys.exit(1)
time.sleep(0.5)
print("")


def show(tag, resp):
    print("  [%s] 原始响应 = %s" % (tag, resp))
    if resp is None:
        print("      ⇒ 返回 None：未启用 / 循环未就绪 / ws 断开 / 5 秒超时（且不抛异常）")
        return False
    rc = resp.get("retcode")
    if rc in (0, "0", None):
        mid = (resp.get("data") or {}).get("message_id", "")
        print("      ⇒ 成功，message_id=%s" % mid)
        return True
    print("      ⇒ 失败 retcode=%s msg=%s" % (rc, resp.get("msg") or resp.get("wording") or resp))
    return False


if KEY == "send":
    print("===== 真实发送私聊 → %s =====" % TARGET)
    resp = api.call_action_sync("send_private_msg", {
        "user_id": int(TARGET),
        "message": [{"type": "text", "data": {"text": TEXT}}],
    })
    ok = show("send_private_msg", resp)
    print("")
    print("===== 对照：工具 napcat_send 的实现会怎么报 =====")
    print("  sender.py 里丢掉了 call_action_sync 的返回值，无条件 return '已发送：…'")
    print("  本次真实结果 = %s，而工具会告诉你 = 已发送" % ("成功" if ok else "失败"))
elif KEY == "group":
    print("===== 真实发送群聊 → %s =====" % TARGET)
    resp = api.call_action_sync("send_group_msg", {
        "group_id": int(TARGET),
        "message": [{"type": "text", "data": {"text": TEXT}}],
    })
    show("send_group_msg", resp)
elif KEY == "why":
    print("===== 目标解析逻辑实测（纯函数，不连网）=====")
    from func.toolbox.napcat.active_sender.sender import TBSender
    s = TBSender()
    for tt, tid in [("friend", "爱你的卡戎星"), ("friend", "3898266363"),
                    ("group", "上理GM电竞方块幻想MC社团分部"), ("group", "174127179")]:
        gid, err = s._group_target(tt, tid)
        print("  target_type=%-7s target_id=%-30s → 解析结果=%r  err=%r" % (tt, tid, gid, err))
    print("")
    print("  再走下一步 int(gid)：")
    for v in ["爱你的卡戎星", "3898266363"]:
        try:
            print("    int(%-16r) = %s" % (v, int(v)))
        except Exception as e:
            print("    int(%-16r) → %s: %s" % (v, type(e).__name__, e))
    print("")
    print("  结论：好友目标不做昵称解析、也不校验是否存在；")
    print("        号码正确但发错人 / 5 秒超时没发出去，send_text 都一律回'已发送'。")
else:
    print("===== 好友表里能不能解析出'卡戎星'这类昵称 =====")
    resp = api.call_action_sync("get_friend_list", {})
    if resp is None:
        print("  get_friend_list 返回 None（同上：静默失败）")
    else:
        data = resp.get("data") or []
        print("  好友总数 = %d   retcode=%s" % (len(data), resp.get("retcode")))
        for kw in ("卡戎", "喵呜", "爱你的"):
            hit = [f for f in data if kw in str(f.get("nickname", "")) or kw in str(f.get("remark", ""))]
            print("  含'%s'的好友 = %d 个" % (kw, len(hit)))
            for f in hit[:5]:
                print("      user_id=%s nickname=%s remark=%s"
                      % (f.get("user_id"), f.get("nickname"), f.get("remark")))
    print("")
    print("  （若这里查不到该昵称，说明 AI 只能拿到昵称却拿不到 QQ 号，")
    print("    而 send_qq_message 要求 target_id 是号码 → 发送必然落空）")

conn.stop()
print("")
print("完成。")
