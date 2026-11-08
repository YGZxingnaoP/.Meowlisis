# -*- coding: utf-8 -*-
"""与游戏内 mod 的通信层（MCP 工具 + 只读 /state）。

mod 有两个面：
    GET  /state   只读状态：text（给模型看的文字状态）+ meta（结构化字段）
    POST /command {"tool": "...", "args": {...}}  执行一个 MCP 工具
    GET  /ping    存活检查
    GET  /saves   列出存档目录
    POST /load    从标题画面读档

动作本身和 MCP 的 tools/call 完全同一条路径，这里只是把 JSON-RPC 换成了
更省事的 REST 调用；长动作（下矿、钓鱼）可能跑几分钟，超时给足。
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8765"

# 长动作工具的超时（秒）；mod 侧还有自己的 tick 上限，这里只是兜底。
TOOL_TIMEOUT = {
    "sleep": 420, "fish": 900, "explore_mine": 900, "clear_area": 400,
    "till_area": 300, "plant_seeds": 300, "water_crops": 400,
    "harvest_crops": 300, "care_animals": 600, "festival": 620,
    "donate_bundles": 600, "ship_items": 180, "tidy_backpack": 300,
    "store_items": 120, "take_items": 120, "wait": 900, "travel_to": 180,
    "move_to": 60, "use_tool": 120, "interact": 120, "fight": 150,
    "cook": 120, "check_crab_pots": 240, "donate_museum": 240,
    "buy": 20, "sell": 20, "open_shop": 20, "craft": 20, "dialogue": 20,
    "menu_click": 20, "close_menu": 20, "choose_profession": 20,
    "skip_event": 20, "leave_festival": 320, "quest_board": 180,
    "upgrade_tool": 240, "crack_geodes": 240, "buy_animal": 240,
    "build": 300, "upgrade_house": 240, "give_gift": 240, "gift_info": 10,
    "bundle_info": 10, "eat": 30, "place_item": 60, "say": 10,
    "set_name": 20, "set_mode": 10, "wait_chat": 320, "follow": 620,
    "propose": 180, "watch_tv": 240,
}


class Bridge:
    def __init__(self, base_url=DEFAULT_URL, timeout=8.0):
        self.base_url = str(base_url or "").strip().rstrip("/") or DEFAULT_URL
        self.timeout = _number(timeout, 8.0)

    # ---------- 底层 ----------
    def _request(self, path, payload=None, timeout=None, method=None):
        url = self.base_url + path
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method=method or ("POST" if data is not None else "GET"))
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", "replace"))
                if isinstance(body, dict):
                    return body
            except Exception:
                pass
            return {"ok": False, "reason": "http %s" % exc.code}
        except urllib.error.URLError as exc:
            return {"ok": False, "reason": "mod 未加载或端口不通：%s" % (getattr(exc, "reason", exc),)}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    # ---------- 查询 ----------
    def ping(self):
        return self._request("/ping", timeout=4)

    def state(self):
        return self._request("/state", timeout=max(8, self.timeout))

    def screenshot(self):
        """截一张当前画面，返回 {ok, path}。"""
        return self._request("/screenshot", timeout=30)

    def farmmap(self):
        """农场宏观记忆图（4×4 格一块）。"""
        return self._request("/farmmap", timeout=20)

    # ---------- 动作 ----------
    def call(self, tool, timeout=None, **kwargs):
        return self.call_with(tool, kwargs, timeout=timeout)

    def call_with(self, tool, args=None, timeout=None):
        """args 用字典传：工具参数里本身就有叫 tool 的（use_tool），不能和形参撞。"""
        payload = {"tool": str(tool or ""), "args": dict(args or {})}
        limit = timeout or TOOL_TIMEOUT.get(str(tool or ""), 120)
        started = time.time()
        result = self._request("/command", payload, timeout=max(10, limit + 20))
        if not isinstance(result, dict):
            raise RuntimeError("bad response")
        result["elapsed"] = round(time.time() - started, 1)
        return result

    def cancel(self):
        """中止当前正在跑的长动作（钓鱼、下矿等）。"""
        return self._request("/cancel", {}, timeout=8)


def _number(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback



