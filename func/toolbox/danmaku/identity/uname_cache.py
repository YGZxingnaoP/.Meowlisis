# -*- coding: utf-8 -*-
# func/toolbox/danmaku/identity/uname_cache.py
# 一场直播内的「B站昵称 → uid」缓存：纯内存、不落盘、不开线程

from func.tools.singleton_mode import singleton


@singleton
class TBDanmakuUnameCache:
    """弹幕昵称反查结果的会话内缓存（只服务弹幕模块）。

    - 为什么需要：昵称反查要打 B站 搜索接口，一场直播里同一个观众会发很多条弹幕，
      不缓存就是每条弹幕一次外部请求。
    - 生命周期 = 一场直播：由弹幕模块在开播（模块 start）时显式 clear()。
    - 也缓存"查不到"（uid 为空串）——否则新路人每条弹幕都会重打一次接口。
    - 纯内存：不落盘、重启即空（会话态数据不写盘）。
    """

    # 单场上限，防止超长直播把内存撑大（超出就淘汰最早写入的那个）
    MAX_ENTRIES = 2000

    def __init__(self):
        self._data = {}

    def get(self, uname):
        """命中返回 uid（空串 = 这场直播内查过、没查到）；没缓存过返回 None。"""
        return self._data.get(str(uname or "").strip())

    def put(self, uname, uid):
        """写入缓存；空昵称不缓存。"""
        key = str(uname or "").strip()
        if not key:
            return
        if key not in self._data and len(self._data) >= self.MAX_ENTRIES:
            self._data.pop(next(iter(self._data)), None)
        self._data[key] = str(uid or "")

    def clear(self):
        """清空（会话边界：一场直播开始时调用）。"""
        self._data.clear()

    def size(self):
        return len(self._data)
