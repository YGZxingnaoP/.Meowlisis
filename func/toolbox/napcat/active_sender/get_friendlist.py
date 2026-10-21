# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/get_friendlist.py
# 获取 QQ 好友列表

from typing import List

from func.log.default_log import DefaultLog


class TBGetFriendList:
    """获取 NapCat 好友列表（供主动发送选择目标）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        # 最近一次失败的真实原因（供上层把话说清楚，而不是只回一句"未获取到"）
        self.last_error = ""

    def get(self) -> List[dict]:
        """返回好友列表 [{user_id, nickname, remark}]；失败原因写在 last_error"""
        self.last_error = ""
        resp = None
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            resp = TBNapCatCore().call_action_sync("get_friend_list", {})
        except Exception:
            self.log.exception("获取好友列表失败")
            self.last_error = "调用 get_friend_list 异常"
            return []
        if resp is None:
            # call_action_sync 在未启用/循环未就绪/ws 断开/5 秒超时时都返回 None，且不抛异常
            self.last_error = "NapCat 无响应（未连接或超时）"
            self.log.warning("[好友列表] NapCat 无响应：get_friend_list 返回 None")
            return []
        if isinstance(resp, dict):
            code = resp.get("retcode")
            status = resp.get("status")
            if (status and status != "ok") or (code not in (None, 0, "0")):
                self.last_error = "NapCat 返回错误 retcode=%s %s" % (
                    code, resp.get("wording") or resp.get("message") or resp.get("msg") or "")
                self.log.warning("[好友列表] %s | raw=%s" % (self.last_error, str(resp)[:300]))
                return []
        data = self._extract(resp)
        if not data:
            self.last_error = "NapCat 返回空好友列表"
            self.log.warning("[好友列表] 空数据 | raw=%s" % str(resp)[:300])
            return []
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            result.append({
                "user_id": str(item.get("user_id", "")),
                "nickname": str(item.get("nickname", "") or ""),
                "remark": str(item.get("remark", "") or ""),
            })
        if not result:
            self.last_error = "好友列表格式无法解析"
            self.log.warning("[好友列表] 格式无法解析 | raw=%s" % str(resp)[:300])
        return result

    @staticmethod
    def _extract(ret):
        """从 OneBot 响应里取出好友数组（兼容 data / data.friends / friends 几种包法）"""
        if isinstance(ret, list):
            return ret
        if not isinstance(ret, dict):
            return []
        for node in (ret, ret.get("data")):
            if isinstance(node, list):
                return node
            if isinstance(node, dict):
                for key in ("friends", "list", "data"):
                    val = node.get(key)
                    if isinstance(val, list):
                        return val
        return []
