# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/get_grouplist.py
# 获取 QQ 群聊列表 / 群名→群号解析

import re
from typing import List, Tuple, Optional

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

    def resolve_id(self, value) -> Tuple[Optional[str], str]:
        """把「群号或群名」解析为群号，返回 (group_id, err)。

        纯数字原样返回；群名按 精确→前缀→包含 匹配在线真实群列表。
        匹配到唯一群返回群号；多个同名/无匹配返回 err（附可用群，引导 LLM 用群号或先 get_group_list）。
        """
        raw = str(value or "").strip().strip("\"'")
        if not raw:
            return None, "目标群为空"
        if re.fullmatch(r"\d+", raw):
            return raw, ""
        groups = self.get()
        if not groups:
            return None, "获取群列表为空，请先调用 get_group_list 查询可用群号"
        names = [str(g.get("group_name", "") or "") for g in groups]

        def _pick(pool):
            pool = list(pool)
            if len(pool) == 1:
                return pool[0]["group_id"], ""
            if len(pool) > 1:
                hint = "；".join(f"{g['group_name']}={g['group_id']}" for g in pool[:5])
                return None, f"群名「{raw}」匹配到多个群，请用群号精确指定：{hint}"
            return None, None

        gid, err = _pick(g for g in groups if g["group_name"] == raw)
        if gid or err:
            return gid, err
        gid, err = _pick(g for g in groups if g["group_name"].startswith(raw))
        if gid or err:
            return gid, err
        gid, err = _pick(g for g in groups if raw in g["group_name"])
        if gid or err:
            return gid, err
        return None, (f"未找到群「{raw}」。可用的群：{'、'.join(n for n in names[:12]) or '(空)'}"
                      "（也可先调用 get_group_list 查看完整列表）")

    @staticmethod
    def _extract(ret):
        if isinstance(ret, list):
            return ret
        if isinstance(ret, dict):
            return ret.get("data") or ret.get("groups") or []
        return []
