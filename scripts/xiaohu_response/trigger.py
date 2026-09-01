# -*- coding: utf-8 -*-
# scripts/xiaohu_response/trigger.py
# 筱狐必回机器人：触发过滤 + 消息解析
#
# 目标群内任何人的消息都会解析返回（分类标注），由 main 回调层决策是否入缓冲：
#   - 筱狐（TARGET_USER_ID）任何消息 → is_xiaohu=True
#   - 其它人 @ 角色（at_self）→ is_at_self=True
#   - 其它人普通消息 → 两者均 False（是否合并取决于该用户是否已在缓冲中）
# 解析逻辑复用主项目 TBGetGroupMessage（提取 text/username/at_list 等），不改主项目。

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class XHTrigger:
    """事件解析与分类：命中目标群返回分类结果 dict，未命中返回 None"""

    def __init__(self, log, config):
        self.log = log
        self.config = config
        from func.toolbox.napcat.groupchat.get_group_message import TBGetGroupMessage
        self.get_group_message = TBGetGroupMessage()

    def parse(self, event: dict):
        """解析目标群群消息并分类。

        返回 None：非群聊事件 / 非目标群 / 自己发的消息。
        返回 {
            "parsed": {group_id, group_name, username, user_id, self_id, text,
                       segments, at_list, at_self, is_self, raw_message},
            "is_xiaohu": bool,   # 是否为筱狐
            "is_at_self": bool,  # 是否其它人 @ 角色
        }
        """
        if not isinstance(event, dict):
            return None
        # 只收群聊消息事件
        if event.get("post_type") != "message" or event.get("message_type") != "group":
            return None

        parsed = self.get_group_message.parse(event)
        if not parsed:
            return None

        # 目标群过滤
        gid = str(parsed.get("group_id", "") or "")
        if gid != self.config.GROUP_ID:
            return None

        # 自己发的消息忽略（防御）
        uid = str(parsed.get("user_id", "") or "")
        if parsed.get("is_self") or uid == str(parsed.get("self_id", "") or ""):
            return None

        # 补充群名（事件自带 group_name，缺省用配置兜底）
        parsed["group_name"] = str(event.get("group_name", "") or "") or self.config.GROUP_NAME

        # 顺带记录 QQ 号 → 昵称映射（与主项目 event_handler 一致，供稳定档案昵称使用）
        try:
            from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
            sender = event.get("sender") or {}
            TBUserNicknameMap().observe(
                uid,
                card=sender.get("card", ""),
                nickname=sender.get("nickname", ""),
            )
        except Exception:
            self.log.exception("记录 QQ 昵称映射失败")

        # 分类
        is_xiaohu = (uid == self.config.TARGET_USER_ID)
        is_at_self = (not is_xiaohu) and bool(parsed.get("at_self"))
        return {
            "parsed": parsed,
            "is_xiaohu": is_xiaohu,
            "is_at_self": is_at_self,
        }
