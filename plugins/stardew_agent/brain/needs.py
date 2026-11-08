# -*- coding: utf-8 -*-
"""需求评估 + 背包/技能/农场感知。

输入是 mod 的 /state 返回（meta + text），这里把 meta 修成稳定的结构，
给规划层提供可直接说人话的摘要。只算分和拼文本，不做决策。
"""

SEASON_CN = {"spring": "春", "summer": "夏", "fall": "秋", "winter": "冬"}

SKILL_CN = {"farming": "耕种", "mining": "采矿", "combat": "战斗",
            "foraging": "采集", "fishing": "钓鱼", "luck": "幸运"}

CATEGORY_CN = {
    -74: "种子", -79: "肥料", -80: "鱼饵", -81: "钓具",
    -75: "蔬菜", -76: "水果", -77: "采集品", -78: "花",
    -4: "鱼", -5: "蛋奶", -6: "饲料", -7: "矿石",
    -8: "古物", -2: "矿物", -12: "家具",
}


def game(state):
    return (state or {}).get("game") or {}


def player(state):
    return (state or {}).get("player") or {}


def hour_of(state):
    try:
        return int(game(state).get("time") or 0) // 100
    except (TypeError, ValueError):
        return 6


def clock_text(state):
    try:
        value = int(game(state).get("time") or 0)
    except (TypeError, ValueError):
        value = 0
    return "%02d:%02d" % (value // 100, value % 100)


def fatigue_text(state):
    """把体力翻译成角色能理解的体感，避免只看“体力 0/270”这种数字。"""
    me = player(state)
    try:
        energy = float(me.get("energy") or 0)
        maximum = max(1.0, float(me.get("max_energy") or 270))
    except (TypeError, ValueError):
        return "有点累"
    ratio = max(0.0, min(1.0, energy / maximum))
    if energy <= 0 or ratio <= 0.03:
        return "精疲力尽，再干就要晕倒了，必须马上吃东西或回家睡觉"
    if ratio <= 0.12:
        return "快没力气了，动作开始发虚"
    if ratio <= 0.28:
        return "很累，适合做轻活或回家"
    if ratio <= 0.5:
        return "有点累，还能撑一阵"
    return "体力充足"


def energy_ratio(state):
    me = player(state)
    try:
        return max(0.0, min(1.0, float(me.get("energy") or 0) / (float(me.get("max_energy") or 1) or 1.0)))
    except (TypeError, ValueError):
        return 0.0


def health_ratio(state):
    me = player(state)
    try:
        return max(0.0, min(1.0, float(me.get("health") or 0) / (float(me.get("max_health") or 100) or 100.0)))
    except (TypeError, ValueError):
        return 1.0


def money(state):
    try:
        return int(player(state).get("money") or 0)
    except (TypeError, ValueError):
        return 0


def inventory(state):
    return list((state or {}).get("inventory") or [])


def pets(state):
    return list((state or {}).get("pets") or [])


def has_pet(state):
    return bool(pets(state))


def free_slots(state):
    me = player(state)
    try:
        used = int(me.get("used_slots") or 0)
        total = int(me.get("inventory_slots") or 36)
    except (TypeError, ValueError):
        return 0
    return max(0, total - used)


def inventory_full(state):
    return free_slots(state) <= 0


def item_count(item):
    try:
        return max(1, int(item.get("count") or 1))
    except (TypeError, ValueError):
        return 1


def category_of(item):
    try:
        return int(item.get("category") or 0)
    except (TypeError, ValueError):
        return 0


def is_seed(item):
    name = str(item.get("name") or "")
    return category_of(item) == -74 or "Seeds" in name or "种子" in name


def is_food(item):
    return int(item.get("edible") or 0) > 0


def is_tool(item):
    return bool(item.get("is_tool"))


def is_quest_item(item):
    name = str(item.get("name") or "")
    return category_of(item) == -102 or "Quest" in name or "任务" in name


def seed_count(state):
    return sum(item_count(item) for item in inventory(state)
               if not is_tool(item) and is_seed(item))


def food_count(state):
    return sum(item_count(item) for item in inventory(state) if is_food(item))


def shippable_count(state):
    total = 0
    for item in inventory(state):
        if is_tool(item) or is_seed(item) or is_food(item) or is_quest_item(item):
            continue
        if int(item.get("count") or 0) <= 0:
            continue
        total += item_count(item)
    return total


def shippable_items(state):
    result = []
    for item in inventory(state):
        if is_tool(item) or is_seed(item) or is_food(item) or is_quest_item(item):
            continue
        if int(item.get("count") or 0) <= 0:
            continue
        result.append(item)
    return result


def sellable_items(state):
    """能卖给商店的东西：工具和任务物品除外，食物也可以卖（腾背包用）。"""
    result = []
    for item in inventory(state):
        if is_tool(item) or is_quest_item(item):
            continue
        if int(item.get("count") or 0) <= 0:
            continue
        result.append(item)
    return result


def _tool_kind(item):
    return str(item.get("kind") or "")


def page_tool(state, *names):
    wanted = set(str(name) for name in names)
    for item in inventory(state):
        if item.get("is_tool") and _tool_kind(item) in wanted:
            return item
    return None


def has_rod(state):
    me = player(state)
    if me.get("has_rod"):
        return True
    return page_tool(state, "FishingRod") is not None


def has_watering_can(state):
    return page_tool(state, "WateringCan") is not None


def has_pickaxe(state):
    return page_tool(state, "Pickaxe") is not None


def has_hoe(state):
    return page_tool(state, "Hoe") is not None


def has_water(state):
    """水壶里还有水吗（meta 里没有水壶余量时按有处理，让 mod 自己补水）。"""
    for item in inventory(state):
        if _tool_kind(item) == "WateringCan":
            return True
    return False


def crop_summary(state):
    farm = (state or {}).get("farm") or {}
    return {
        "crops": int(farm.get("crops") or 0),
        "ready": int(farm.get("ready") or 0),
        "thirsty": int(farm.get("thirsty") or 0),
        "watered": int(farm.get("watered") or 0),
        "empty_dirt": int(farm.get("empty_dirt") or 0),
        "debris": int(farm.get("debris") or 0),
        "trees": int(farm.get("trees") or 0),
        "grass": int(farm.get("grass") or 0),
        "animals": int(farm.get("animals") or 0),
        "buildings": int(farm.get("buildings") or 0),
        "hay": int(farm.get("hay") or 0),
        "empty_rect": list(farm.get("empty_rect") or []),
        "location": str(farm.get("location") or ""),
    }


def skills(state):
    raw = player(state).get("skills") or {}
    clean = {}
    for key, value in raw.items():
        try:
            clean[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return clean


def skills_text(state):
    data = skills(state)
    if not data:
        return ""
    return " · ".join("%s %s" % (SKILL_CN.get(key, key), value)
                      for key, value in data.items() if key != "luck")


def inventory_summary(state, limit=10):
    groups = {}
    for item in inventory(state):
        if is_tool(item):
            groups.setdefault("工具", []).append(str(item.get("name") or "?"))
            continue
        if int(item.get("count") or 0) <= 0:
            continue
        category = CATEGORY_CN.get(category_of(item)) or ("食物" if is_food(item) else "其它")
        groups.setdefault(category, []).append("%s×%s" % (item.get("name") or "?", item_count(item)))
    parts = []
    for category, entries in list(groups.items())[:limit]:
        parts.append("%s：%s" % (category, "、".join(entries[:5])))
    return "；".join(parts)


def inventory_text(state, limit=16, max_chars=900):
    me = player(state)
    slots = int(me.get("inventory_slots") or 36)
    used = int(me.get("used_slots") or 0)
    lines = ["背包 %d/%d%s" % (used, slots, "（满了）" if inventory_full(state) else "")]
    for item in inventory(state)[:limit]:
        if is_tool(item):
            lines.append("· [%s] %s（%s）" % (item.get("slot"), item.get("name"), _tool_kind(item)))
        else:
            lines.append("· [%s] %s ×%s" % (item.get("slot"), item.get("name") or "?", item_count(item)))
    return "\n".join(lines)[:max_chars]


def assess(state, traits=None):
    """计算各项需求分。traits 是 0~1 的性格参数。"""
    if not (state or {}).get("ok"):
        return {}
    traits = traits or {}
    hour = hour_of(state)
    energy = energy_ratio(state)
    farm = crop_summary(state)
    gm = game(state)
    needs = {}

    rest = 0.0
    if hour >= 24 or hour < 6:
        rest = 1.0
    elif hour >= 21:
        rest = min(1.0, 0.5 + (hour - 21) * 0.25)
    if energy < 0.1:
        rest = max(rest, 0.9)
    needs["rest"] = {"value": round(rest, 2),
                     "why": "%s，体力 %d%%" % (clock_text(state), int(energy * 100))}

    farm_need = 0.05
    farm_why = "农场没什么急事"
    if farm["ready"] > 0:
        farm_need = 0.95
        farm_why = "%d 株作物熟了" % farm["ready"]
    elif farm["thirsty"] > 0:
        farm_need = 0.8
        farm_why = "%d 块地还没浇水" % farm["thirsty"]
    elif farm["debris"] >= 8:
        farm_need = 0.7
        farm_why = "农场有 %d 处杂物" % farm["debris"]
    elif farm["trees"] + farm["grass"] >= 20:
        farm_need = 0.62
        farm_why = "农场有 %d 棵树、%d 丛草要清" % (farm["trees"], farm["grass"])
    elif farm["crops"] == 0 and seed_count(state) > 0 and has_hoe(state):
        farm_need = 0.6
        farm_why = "手上有种子，地还空着"
    farm_need *= 0.55 + 0.9 * float(traits.get("diligence", 0.6))
    needs["farm"] = {"value": round(min(1.0, farm_need), 2), "why": farm_why}

    eat = 0.0
    eat_why = "还不饿"
    if energy < 0.45 and food_count(state) > 0:
        eat = round(min(0.85, (0.45 - energy) * 2.0), 2)
        eat_why = "体力 %d%%，背包里有吃的" % int(energy * 100)
    needs["eat"] = {"value": eat, "why": eat_why}

    money_now = money(state)
    money_need = max(0.0, min(1.0, 1.0 - money_now / 2500.0))
    money_need *= 0.4 + 0.7 * float(traits.get("thrift", 0.5))
    if shippable_count(state) >= 8:
        money_need = min(1.0, money_need + 0.2)
    needs["money"] = {"value": round(money_need, 2),
                      "why": "身上 %d 金币，背包可出货 %d 件" % (money_now, shippable_count(state))}

    bag = 0.0
    bag_why = "背包还有空间"
    if inventory_full(state):
        bag = 1.0
        bag_why = "背包满了，得先整理/出货/存箱子"
    elif free_slots(state) <= 3:
        bag = 0.75
        bag_why = "背包快满了（剩 %d 格）" % free_slots(state)
    elif shippable_count(state) >= 12:
        bag = 0.45
        bag_why = "背包里堆了 %d 件可出货的东西" % shippable_count(state)
    needs["bag"] = {"value": bag, "why": bag_why}

    supplies = 0.0
    supplies_why = "该有的都有了"
    if seed_count(state) <= 0 and money_now >= 60 and has_hoe(state):
        supplies = 0.75
        supplies_why = "没种子了，先去买"
    elif not has_rod(state) and money_now >= 500 and hour < 16:
        supplies = 0.55
        supplies_why = "还没有钓竿，买一根就能钓鱼"
    needs["supplies"] = {"value": round(supplies, 2), "why": supplies_why}

    forage = 0.0
    forage_why = "不急着捡东西"
    if food_count(state) <= 0 and energy < 0.75:
        forage = 0.45 + (0.75 - energy) * 0.5
        forage_why = "背包里没吃的，捡点野生作物"
    needs["forage"] = {"value": round(min(0.9, forage), 2), "why": forage_why}

    adventure = 0.0
    adventure_why = "今天不想折腾"
    if hour < 20 and energy > 0.4:
        curiosity = float(traits.get("curiosity", 0.5))
        adventure = 0.2 + 0.55 * curiosity
        if hour < 12:
            adventure += 0.1
        if farm["ready"] > 0 or farm["thirsty"] > 0:
            adventure -= 0.25
        if health_ratio(state) < 0.6:
            adventure -= 0.3
        adventure_why = "想去钓鱼/下矿/探索试试运气"
    needs["adventure"] = {"value": round(max(0.0, min(0.95, adventure)), 2), "why": adventure_why}

    social = 0.3 + 0.35 * float(traits.get("sociability", 0.5))
    needs["social"] = {"value": round(min(1.0, social), 2), "why": "想找人聊聊天"}

    curiosity = 0.55 * (0.5 + 0.9 * float(traits.get("curiosity", 0.5)))
    needs["curiosity"] = {"value": round(min(1.0, curiosity), 2), "why": "想出去看看"}

    if gm.get("raining") and "farm" in needs:
        needs["farm"]["value"] = round(needs["farm"]["value"] * 0.5, 2)
        needs["farm"]["why"] += "（今天下雨）"

    return needs


def spending_advice(state):
    money_now = money(state)
    if money_now < 2000:
        return ""
    slots = int(player(state).get("inventory_slots") or 36)
    counts = {}
    for item in inventory(state):
        key = str(item.get("id") or "")
        counts[key] = counts.get(key, 0) + item_count(item)
    tips = []
    if slots < 24 and money_now >= 2000:
        tips.append("背包扩到 24 格：2000g，皮埃尔杂货店柜台上的背包")
    elif slots < 36 and money_now >= 10000:
        tips.append("背包扩到 36 格：10000g，皮埃尔杂货店柜台上的背包")
    if money_now >= 10000 and counts.get("388", 0) < 450:
        tips.append("升级房子要 10000g + 450 木材（现在木材 %s）" % counts.get("388", 0))
    if seed_count(state) < 5:
        tips.append("种子不多了，去 SeedShop 买当季种子")
    if not tips:
        return ""
    return "【花钱建议】" + "；".join(tips[:4])


def state_brief(state):
    gm = game(state)
    me = player(state)
    farm = crop_summary(state)
    return ("第 %s 年 %s %s 日 %s %s；我在 %s (%s,%s)，体力 %s/%s，金币 %s；"
            "农场作物 %s 株（熟 %s、待浇 %s、杂物 %s）。" % (
                gm.get("year"), SEASON_CN.get(gm.get("season"), gm.get("season")), gm.get("day"),
                clock_text(state), "雨" if gm.get("raining") else "晴",
                me.get("location"), me.get("tile_x"), me.get("tile_y"),
                me.get("energy"), me.get("max_energy"), me.get("money"),
                farm["crops"], farm["ready"], farm["thirsty"], farm["debris"]))
