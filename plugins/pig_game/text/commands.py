# -*- coding: utf-8 -*-
"""养猪游戏：本地关键词指令解析（**零 LLM**）。

把「猪猪游戏 偷其乐容容30只超级肥猪」这类口令消息，用纯本地规则解析成
(工具名, 参数)，全程不经过任何 LLM / 工具调用。
"""

import re

from . import parse

# 猪种词表（长的放前面，避免「飞猪」抢了「神奇飞猪」）
SPECIES_WORDS = (
    "咕嘟魔法猪",
    "超级肥猪",
    "神奇飞猪",
    "肥宅猪",
    "超级猪",
    "鱼猪猪",
    "咕嘟猪",
    "神奇猪",
    "咕嘟",
    "鱼猪",
    "肥猪",
    "飞猪",
    "鱼",
)

_NUM = r"(\d{1,4}|[零〇一壹二两贰三叁四肆五伍六陆七柒八捌九玖十拾百佰]{1,4})"

# 目标名字里要剥掉的噪音词
_NOISE = (
    "出价", "单价", "价格", "每个", "金币", "币", "买", "卖", "收", "收购", "交易",
    "设置", "猪猪军队", "猪猪", "守军", "军队", "布防", "阵容", "猪圈", "地盘",
    "那里", "那边", "去", "把", "从", "给我", "帮我", "帮忙", "麻烦", "一下",
    "的", "了", "吧", "呢", "啊", "哦", "呀", "嘛", "我", "想要", "要",
)


# ============================================================================
# 小工具
# ============================================================================
def strip_prefix(text, prefixes):
    """去掉口令前缀（只去第一次出现的那一个）"""
    t = str(text or "")
    for p in (prefixes or []):
        p = str(p or "")
        if p and p in t:
            return t.replace(p, " ", 1)
    return t


def _clean(s):
    """去掉标点与噪音词，留下干净的名字"""
    t = str(s or "")
    t = re.sub(r"[@#：:，,。.！!？?、；;~～\-—_\[\]()【】「」'\"|/\\]", " ", t)
    for _ in range(3):
        before = t
        for w in _NOISE:
            t = t.replace(w, " ")
        if t == before:
            break
    # 结尾单独的「猪」也算噪音（"偷小B的猪" → 小B），但保留「超级肥猪 / 鱼猪」这类猪种词
    t = re.sub(r"(?<=[的了\s])猪(?![^\s])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _after(text, words):
    """从 text 里去掉 words 后剩下的部分（再清洗）"""
    t = str(text or "")
    for w in sorted(set(words), key=len, reverse=True):
        t = t.replace(w, " ")
    return _clean(t)


def _pick_species(text):
    """取最先出现的猪种词（返回用户原词，交给引擎做别名解析）"""
    t = str(text or "")
    best = None
    for w in SPECIES_WORDS:
        i = t.find(w)
        if i >= 0 and (best is None or i < best[0] or (i == best[0] and len(w) > len(best[1]))):
            best = (i, w)
    return best[1] if best else None


def _pick_count(text, strict=False):
    """取数量：优先「N只」，strict=True 时不退化为裸数字"""
    t = str(text or "")
    m = re.search(_NUM + r"\s*只", t) or re.search(r"只\s*" + _NUM, t)
    if m:
        return parse.to_int(m.group(1))
    if strict:
        return None
    m = re.search(_NUM, t)
    return parse.to_int(m.group(1)) if m else None


# ============================================================================
# 各指令
# ============================================================================
def _parse_steal(body):
    sp = _pick_species(body)
    cnt = _pick_count(body)
    t = str(body or "")
    for w in ("偷", "顺走", "薅", "悄悄", "下手", "去", "的", "猪圈", "地盘", "那里", "那边"):
        t = t.replace(w, " ")
    if sp:
        t = t.replace(sp, " ")
    t = re.sub(_NUM + r"\s*只?", " ", t)
    t = t.replace("只", " ")
    return "pig_steal", {"target": _clean(t), "species": sp, "count": cnt}, body


def _parse_raid(body):
    t = str(body or "")
    target = ""
    for pat in (r"去\s*(.+?)\s*的?\s*(?:地盘|猪圈|那里|那边)",
                r"(?:抢|打劫|劫|攻打|进攻|偷袭)\s*([^\d\s，,。.]+?)\s*的?\s*(?:猪圈|猪|地盘)?\s*$"):
        m = re.search(pat, t)
        if m:
            target = _clean(m.group(1))
            break
    return "pig_raid", {"action": "start", "target": target, "squad": t}, body


def _parse_trade(body):
    t = str(body or "")
    m = re.search(r"(?:出价|单价|价格|每个|币)\s*" + _NUM, t) or re.search(_NUM + r"\s*(?:金币|币)", t)
    price = parse.to_int(m.group(1)) if m else None
    cnt = _pick_count(t, strict=True)
    sp = _pick_species(t)
    # 目标名 = 原文 - 动词/单位/数字/猪种 之后剩下的部分
    name = t
    for w in ("出价", "买", "卖", "收", "收购", "交易", "单价", "价格", "每个",
              "金币", "币", "只", "的", "块", "想"):
        name = name.replace(w, " ")
    if sp:
        name = name.replace(sp, " ")
    name = re.sub(_NUM, " ", name)
    return "pig_trade", {"action": "offer", "target": _clean(name),
                         "species": sp, "count": cnt, "price": price}, body


# 商店叫法（只放不会跟普通聊天撞的词）
SHOP_WORDS = ("天降猪猪", "猪猪商店", "小猪商店", "猪猪杂货铺", "猪猪超市")


def _parse_shop(body):
    """「天降猪猪 买 2只飞猪 1只鱼猪」→ {"飞猪": 2, "鱼猪": 1}（值是用户原词）"""
    t = str(body or "")
    for w in SHOP_WORDS:
        t = t.replace(w, " ")
    t = re.sub(r"[，,。.、；;！!？?~～\-—_]", " ", t)
    items = {}
    for sp in sorted(SPECIES_WORDS, key=len, reverse=True):
        m = re.search(_NUM + r"\s*只?\s*" + re.escape(sp), t)      # 2只飞猪 / 2飞猪
        if not m:
            m = re.search(re.escape(sp) + r"\s*(" + _NUM + r")?\s*只", t)   # 飞猪3只
            num = m.group(1) if m else None
        else:
            num = m.group(1)
        if m:
            n = parse.to_int(num) if num else 1
            t = t[:m.start()] + " " * (m.end() - m.start()) + t[m.end():]
        else:
            i = t.find(sp)                       # 只写了猪种，没写数量 → 1 只
            if i < 0:
                continue
            n = 1
            t = t[:i] + " " * len(sp) + t[i + len(sp):]
        if n and n > 0:
            items[sp] = items.get(sp, 0) + n
    return "pig_shop", {"items": items, "raw": body}, body


# ============================================================================
# 主入口
# ============================================================================
def parse_command(text, prefixes):
    """解析一条口令消息。

    返回 (工具名, 参数字典, 去掉前缀后的正文)；未命中返回 (None, None, 正文)。
    """
    body = strip_prefix(text, prefixes).strip()
    if not body:
        return None, None, ""

    # 1) 规则 / 帮助（优先级最高）
    if any(k in body for k in ("游戏规则", "养猪规则", "怎么玩", "玩法", "帮助", "菜单", "能干嘛")):
        return "pig_rules", {}, body

    # 2) 天降猪猪商店（要在「交易报价」之前，否则"买2只飞猪"会被当成玩家间交易）
    if any(k in body for k in SHOP_WORDS):
        return _parse_shop(body)

    # 3) 抢猪响应
    if any(k in body for k in ("接受抢猪", "迎战", "应战", "接战")):
        return "pig_raid", {"action": "accept"}, body
    if any(k in body for k in ("拒绝抢猪", "拒战", "不接受", "不接")):
        return "pig_raid", {"action": "reject"}, body
    if any(k in body for k in ("强制进攻", "强攻", "强行", "强制")):
        return "pig_raid", {"action": "force", "target": _after(body, ("强制进攻", "强攻", "强行", "强制", "进攻"))}, body

    # 4) 交易响应（放在报价之前）
    if "接受交易" in body or body in ("接受", "我接受"):
        return "pig_trade", {"action": "accept"}, body
    if "拒绝交易" in body or body in ("拒绝", "我拒绝"):
        return "pig_trade", {"action": "reject"}, body

    # 5) 池塘（必须在「打扫猪圈」之前，靠"池塘"区分）
    if "池塘" in body and any(k in body for k in ("维护", "清理", "换水", "打扫", "修理")):
        return "pig_pond", {}, body

    # 6) 猪猪军队
    if "军队" in body or "守军" in body or "布防" in body:
        squad = _after(body, ("设置", "猪猪军队", "猪猪", "守军", "军队", "布防", "阵容", "改为", "换成"))
        return "pig_army", {"squad": squad or body}, body

    # 7) 合成魔法猪
    if "合成" in body or "炼成" in body:
        sp = _pick_species(body)
        return "pig_craft", {"magic": sp or _after(body, ("合成", "炼成", "魔法猪", "一只", "1只"))}, body

    # 8) 养互动（在「查看猪圈」之前，否则"打扫猪圈/巡视猪圈"会被吃掉）
    for kws, act in (((("骑猪", "骑车", "骑一下", "骑着")), "ride"),
                     ((("打扫", "清理猪圈", "擦", "扫")), "clean"),
                     ((("晚餐", "共进晚餐", "吃饭", "喂食")), "dinner"),
                     ((("巡视", "巡逻", "巡查")), "patrol")):
        if any(k in body for k in kws):
            return "pig_care", {"action": act}, body

    # 9) 猪圈场景
    if "场景" in body or "布置" in body:
        return "pig_pen", {"action": "scene",
                           "scene": _after(body, ("设置猪圈场景", "设置场景", "猪圈场景", "场景",
                                                  "换成", "改成", "设置为", "设置", "布置"))}, body

    # 10) 查看猪圈
    if "猪圈" in body or "我的猪" in body or "查看猪" in body or "看猪" in body:
        return "pig_pen", {"action": "view"}, body

    # 11) 假扮打卡（必须在"打卡"之前）
    if "假扮" in body or "冒充" in body or "装扮" in body:
        return "pig_fake", {"target": _after(body, ("假扮打卡", "假扮", "冒充", "装扮", "打卡", "混进", "去"))}, body

    # 12) 打卡 / 签到
    if "打卡" in body or "签到" in body:
        return "pig_checkin", {}, body

    # 13) 偷猪
    if any(k in body for k in ("偷", "顺走", "薅", "下手")):
        return _parse_steal(body)

    # 14) 抢猪 / 攻打
    if any(k in body for k in ("抢", "打劫", "劫", "攻打", "进攻", "偷袭")):
        return _parse_raid(body)

    # 15) 交易报价
    if any(k in body for k in ("买", "卖", "出价", "收购", "单价")):
        return _parse_trade(body)

    # 16) 排行榜
    if "排行" in body or "榜" in body:
        return "pig_rank", {"scope": "全服" if "全服" in body else "全村",
                            "type": "金币" if "金币" in body else "数量"}, body

    return None, None, body
