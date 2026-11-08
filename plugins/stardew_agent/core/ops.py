# -*- coding: utf-8 -*-
"""动作超时：给 REST 调用兜底；动作清单本身来自模组 MCP。"""

TOOL_TIMEOUT = {
    "move_to": 60, "travel_to": 180,
    "use_tool": 120, "interact": 120, "place_item": 60, "till_area": 300,
    "plant_seeds": 300, "water_crops": 400, "harvest_crops": 300, "clear_area": 400,
    "ship_items": 180, "store_items": 120, "take_items": 120, "tidy_backpack": 300,
    "eat": 30, "open_shop": 20, "buy": 20, "sell": 20, "craft": 20,
    "dialogue": 20, "menu_click": 20, "close_menu": 20, "skip_event": 20,
    "choose_profession": 20, "leave_festival": 320,
    "sleep": 420, "fish": 900, "care_animals": 600,
    "gift_info": 10, "give_gift": 240, "donate_museum": 240, "bundle_info": 10,
    "donate_bundles": 600, "cook": 120, "check_crab_pots": 240, "fight": 150,
    "explore_mine": 900, "upgrade_tool": 240, "crack_geodes": 240,
    "quest_board": 180, "buy_animal": 240, "build": 300, "upgrade_house": 240,
    "wait": 900, "say": 10, "set_name": 20, "set_mode": 10,
    "wait_chat": 320, "follow": 620, "propose": 180,
    "festival": 620, "watch_tv": 240,
}


def timeout(tool, default=180):
    return TOOL_TIMEOUT.get(str(tool or ""), default)


# 兼容旧 runner/agent.py
OP_TIMEOUT = TOOL_TIMEOUT
