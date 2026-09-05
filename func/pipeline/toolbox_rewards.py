# -*- coding: utf-8 -*-
# func/pipeline/toolbox_rewards.py
# 奖励桥：从弹幕模块接收礼物事件 → 入账（func/rewards）→ 收纳篮广播；并向角色提示词提供余额行
from func.log.default_log import DefaultLog
from func.rewards.fishcake_store import FishCakeStore


class ToolboxRewardsBridge:
    """奖励对外桥（pipeline 层）：礼物入账入口 + 奖励余额行读取"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.store = FishCakeStore()

    # ==================== 礼物事件入口（弹幕模块调用） ====================
    @staticmethod
    def _is_paid(coin_type, paid):
        """只认真实金钱：开放平台 paid=True；web 端仅金瓜子(gold)（银瓜子免费忽略）"""
        if paid is True:
            return True
        if paid is None and coin_type in ('gold', ''):
            return True
        return False

    def on_gift(self, username="", gift_name="", gift_num=1, price=0,
                coin_type='gold', paid=None):
        """礼物入账：付费礼物按 1000瓜子=1元=10电池 折算电池，随机选一种奖励整笔计入。
        返回入账事件 dict；未入账（免费/过小/无奖励项）返回 None。"""
        try:
            price = int(price or 0)
            gift_num = int(gift_num or 1)
        except Exception:
            return None
        if not self._is_paid(coin_type, paid):
            return None
        battery = round(price * gift_num / 100.0, 1)
        if battery < 0.1:
            return None
        try:
            event = self.store.add_gift(battery, user=username or "",
                                        gift=gift_name or "", num=gift_num)
        except Exception as e:
            self.log.exception(f"礼物入账失败: {e}")
            return None
        if event:
            try:
                from func.subtitle.subtitle_server import get_subtitle_server
                get_subtitle_server().send_basket({
                    "kind": event.get("kind"), "qty": event.get("qty"),
                    "unit": event.get("unit") or "", "user": event.get("user") or "",
                    "gift": event.get("gift") or "", "battery": event.get("battery"),
                })
            except Exception:
                self.log.exception("收纳篮广播失败")
        return event

    # ==================== 提示词余额行（角色卡注入用） ====================
    def get_reward_line(self) -> str:
        """生成奖励余额行（置于角色卡「个人信息喵」区人际关系下一行）。

        无任何奖励项时返回空串（不注入）。格式：
        - 奖励余额：小鱼干×12.5条；星星×3个
        """
        try:
            items = []
            for kind in self.store.summary(history_limit=0).get("kinds", []):
                name = kind.get("name", "")
                balance = kind.get("balance", 0.0)
                unit = kind.get("unit") or ""
                if balance > 0:
                    items.append(f"{name}×{balance}{unit}")
            if not items:
                return ""
            return "- 奖励余额：" + "；".join(items)
        except Exception:
            return ""
