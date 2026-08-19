# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/get_grouplist.py
# 获取 QQ 群聊列表

from typing import List

from func.log.default_log import DefaultLog


class TBGetGroupList:
    """获取 NapCat 群聊列表（供主动发送选择目标）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def get(self) -> List[dict]:
        """返回群列表 [{group_id, group_name}]"""
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ret = TBNapCatCore().call_action_sync("get_group_list", {})
            data = self._extract(ret)
            result = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                result.append({
                    "group_id": str(item.get("group_id", "")),
                    "group_name": str(item.get("group_name", "") or ""),
                })
            return result
        except Exception:
            self.log.exception("获取群列表失败")
            return []

    @staticmethod
    def _extract(ret):
        if isinstance(ret, list):
            return ret
        if isinstance(ret, dict):
            return ret.get("data") or ret.get("groups") or []
        return []
