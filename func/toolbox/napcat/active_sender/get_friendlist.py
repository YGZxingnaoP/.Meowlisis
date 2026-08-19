# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/get_friendlist.py
# 获取 QQ 好友列表

from typing import List

from func.log.default_log import DefaultLog


class TBGetFriendList:
    """获取 NapCat 好友列表（供主动发送选择目标）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def get(self) -> List[dict]:
        """返回好友列表 [{user_id, nickname, remark}]"""
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ret = TBNapCatCore().call_action_sync("get_friend_list", {})
            data = self._extract(ret)
            result = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                result.append({
                    "user_id": str(item.get("user_id", "")),
                    "nickname": str(item.get("nickname", "") or ""),
                    "remark": str(item.get("remark", "") or ""),
                })
            return result
        except Exception:
            self.log.exception("获取好友列表失败")
            return []

    @staticmethod
    def _extract(ret):
        if isinstance(ret, list):
            return ret
        if isinstance(ret, dict):
            return ret.get("data") or ret.get("friends") or []
        return []
