# -*- coding: utf-8 -*-
"""卡片 demo：每一个指令一张图。

数据全部对齐后端（engine.py / config.py / llm.py），不编造字段：
  · 体力上限 100（config.stamina_max）
  · 好感度 0~20（config.affinity_max）
  · 体力消耗：假扮5 偷猪10 抢猪15 强制30 骑猪8 打扫5 晚餐3 巡视2（config.stamina_cost）
  · 偷猪「不暴露成功率」、抢猪「不暴露点数」
  · 无等级（Lv）字段
  · LLM 点评来自 llm.py：偷猪/假扮/打卡/交易=1句，抢猪=3~5句

运行：
    cd plugins/pig_game/poster
    python demo.py          # 全部
    python demo.py 1 6      # 只跑第 1~6 张
"""

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from poster import make_card                      # noqa: E402
from text.rules import TIPS as RULES_TIPS              # noqa: E402
from text.rules import command_card                    # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ---- 一套自洽的假存档（金币/好感/体力/猪种都算得通） ----
ME, TARGET = "渔家傲", "其乐容容"
P = {"coins": 240, "aff": 8, "stamina": 100}          # 我的状态
T = {"coins": 250, "aff": 16}                          # 对方状态
MY_PIGS = "超级肥猪×5、神奇飞猪×1、鱼猪×2"
INCOME = 5 * 1 + 1 * 2 + 2 * 3                          # = 13（打卡后繁殖+1 → 14）

# LLM 点评（llm.py 的 _FALLBACK 原文）
C_CHECKIN = "打卡打完了，猪猪们都挺安分的，别偷懒啊。"
C_FAKE = "偷偷摸摸的，也不看看人家猪圈里养的是什么货色。"
C_STEAL_OK = "偷来的猪也是要养的，你可得上点心。"
C_STEAL_NG = "手脚挺快嘛，就是别被人逮住了。"
C_TRADE = "买卖谈成了，钱货两清，别赖账。"
C_BATTLE = ("两只猪猪冲上去，尘土飞扬！\n"
            "渔家傲的神奇飞猪一个俯冲，把对面守军拱得七零八落。\n"
            "其乐容容的咕嘟猪咕嘟一声，气势倒是没输。\n"
            "最后渔家傲抢走了一只超级肥猪，扬长而去。")

CARDS = [
    # ==================== 1. 打卡 ====================
    ("01_打卡", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 打卡成功", "badge": "第 12 天",
        "subtitle": "繁殖：超级肥猪 +1（现有 6）",
        "stats": [{"k": "今日收益", "v": "+14"}, {"k": "累计金币", "v": "240"},
                  {"k": "好感度", "v": "8"}, {"k": "体力", "v": "100"}],
        "comment": C_CHECKIN,
        "tip": None,     # 由 main 填充小知识
    }),

    # ==================== 2. 假扮打卡 ====================
    ("02_假扮打卡", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 假扮打卡 · 成功", "badge": "+10 金币",
        "subtitle": "%s 今天被锁了猪圈，无法打卡" % TARGET,
        "stats": [{"k": "窃取金币", "v": "+10"}, {"k": "累计金币", "v": "250"},
                  {"k": "体力", "v": "95"}, {"k": "消耗体力", "v": "5"}],
        "comment": C_FAKE,
    }),

    # ==================== 3/4. 偷猪 ====================
    ("03_偷猪_成功", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 偷猪 · 成功", "badge": "偷走 3 只",
        "subtitle": "从 %s 的猪圈偷走了 3 只超级肥猪" % TARGET,
        "stats": [{"k": "你的超级肥猪", "v": "6 → 9"}, {"k": "体力", "v": "90"},
                  {"k": "消耗体力", "v": "10"}],
        "comment": C_STEAL_OK,
        "tip": None,
    }),
    ("04_偷猪_失败", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 偷猪 · 失败", "badge": "空手而归",
        "subtitle": "摸到 %s 的猪圈，一只超级肥猪都没牵走" % TARGET,
        "stats": [{"k": "偷到", "v": "0 只"}, {"k": "体力", "v": "90"},
                  {"k": "消耗体力", "v": "10"}],
        "comment": C_STEAL_NG,
        "tip": None,
    }),

    # ==================== 5~8. 抢猪 ====================
    ("05_抢猪_发起", {
        "img": "assets/scene/grass.png",
        "title": "⚔️ 抢猪 · 已发起", "badge": "待应战",
        "subtitle": "你带 2只神奇飞猪、1只鱼猪 前往 %s 的地盘" % TARGET,
        "stats": [{"k": "出征", "v": "3 只"}, {"k": "状态", "v": "等对方回应"}],
    }),
    ("06_抢猪_战报", {
        "img": "assets/super_fat/image.png",
        "title": "⚔️ 猪猪大战 · 战报", "badge": "%s 获胜" % ME,
        "subtitle": "攻方 %s（2只神奇飞猪、1只鱼猪）" % ME,
        "stats": [{"k": "夺得", "v": "超级肥猪×1"}, {"k": "攻方体力", "v": "-15"},
                  {"k": "剩余体力", "v": "85"}],
        "comment": C_BATTLE,
        "tip": None,
        # 注意：不显示点数
    }),
    ("07_抢猪_拒绝", {
        "img": "assets/scene/night.png",
        "title": "⚔️ 抢猪 · 已拒绝", "badge": "无损失",
        "subtitle": "你回绝了这次抢猪。对方仍可能强制进攻。",
        "stats": [{"k": "体力", "v": "100"}, {"k": "状态", "v": "已回绝"}],
    }),
    ("08_强制进攻", {
        "img": "assets/gudu/image.png",
        "title": "⚔️ 猪猪大战 · 战报", "badge": "%s 获胜" % TARGET,
        "subtitle": "强制进攻 · 攻方 %s（2只神奇飞猪、1只鱼猪）" % ME,
        "stats": [{"k": "损失", "v": "超级肥猪×1"}, {"k": "攻方体力", "v": "-30"},
                  {"k": "剩余体力", "v": "70"}],
        "comment": C_BATTLE,
        "tip": None,
    }),

    # ==================== 9. 猪猪军队 ====================
    ("09_猪猪军队", {
        "img": "assets/flying/image.png",
        "title": "🐷 猪猪军队已就位", "badge": "守军 3 只",
        "subtitle": "守军：2 只神奇飞猪、1 只咕嘟猪",
        "stats": [{"k": "守军", "v": "3 只"}, {"k": "免战", "v": "已生效"}],
    }),

    # ==================== 10~13. 养互动 ====================
    ("10_骑猪", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 骑猪", "badge": "好感 -2",
        "subtitle": "骑猪很爽，但猪猪有点不高兴",
        "stats": [{"k": "好感度", "v": "8 → 6"}, {"k": "体力", "v": "92"},
                  {"k": "消耗体力", "v": "8"}],
    }),
    ("11_打扫猪圈", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 打扫猪圈", "badge": "好感 +1",
        "subtitle": MY_PIGS,
        "stats": [{"k": "好感度", "v": "8 → 9"}, {"k": "体力", "v": "95"},
                  {"k": "消耗体力", "v": "5"}],
    }),
    ("12_共进晚餐", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 和猪共进晚餐", "badge": "好感 +2",
        "subtitle": MY_PIGS,
        "stats": [{"k": "好感度", "v": "8 → 10"}, {"k": "体力", "v": "97"},
                  {"k": "消耗体力", "v": "3"}],
    }),
    ("13_巡视猪圈", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 巡视猪圈", "badge": "好感 ±0",
        "subtitle": "巡视一圈，一切正常",
        "stats": [{"k": "好感度", "v": "8 → 8"}, {"k": "体力", "v": "98"},
                  {"k": "消耗体力", "v": "2"}],
    }),

    # ==================== 14~15. 池塘 / 合成 ====================
    ("14_维护池塘", {
        "img": "assets/fish/image.png",
        "title": "🐷 池塘已维护", "badge": "-20 金币",
        "subtitle": "鱼猪 ×2 暂时安全了",
        "stats": [{"k": "花费", "v": "20"}, {"k": "剩余金币", "v": "220"},
                  {"k": "鱼猪", "v": "2 只"}],
    }),
    ("15_合成成功", {
        "img": "assets/gudu/image.png",
        "title": "🐷 合成成功", "badge": "咕嘟猪 +1",
        "subtitle": "消耗 2只鱼猪、1只神奇飞猪",
        "stats": [{"k": "咕嘟猪", "v": "1 只"}, {"k": "消耗", "v": "鱼猪×2 飞猪×1"}],
    }),

    # ==================== 16~17. 猪圈 ====================
    ("16_查看猪圈", {
        "img": "assets/scene/farm.png",
        "title": "🐷 %s 的猪圈" % ME, "badge": "今天已打卡",
        "subtitle": "已养 3 种猪",
        # 一只猪一张卡：总览 + 猪总数 → 逐个猪种 → 军队单独一行
        "stats": [{"k": "猪猪金币", "v": "240"}, {"k": "好感度", "v": "8"},
                  {"k": "体力", "v": "100"}, {"k": "猪总数", "v": "8 只"},
                  {"br": True},
                  {"k": "超级肥猪", "v": "5 只"}, {"k": "神奇飞猪", "v": "1 只"},
                  {"k": "鱼猪", "v": "2 只"}, {"k": "咕嘟猪", "v": "0 只"},
                  {"br": True},
                  {"k": "军队", "v": "1只神奇飞猪、2只鱼猪"}],
        "lines": ["· 场景：农场"],
    }),
    ("17_设置猪圈场景", {
        "img": "assets/scene/grass.png",
        "title": "🐷 猪圈场景已更换", "badge": "草地",
        "subtitle": "当前场景：草地",
        "stats": [{"k": "可选", "v": "草地 / 农场 / 夜晚"}],
    }),

    # ==================== 18~20. 交易 ====================
    ("18_已询价", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 已询价", "badge": "5 金币/只",
        "subtitle": "目标：%s 的 2 只超级肥猪" % TARGET,
        "stats": [{"k": "单价", "v": "5"}, {"k": "估价约", "v": "5.0"},
                  {"k": "状态", "v": "等对方回应"}],
    }),
    ("19_交易成功", {
        "img": "assets/super_fat/image.png",
        "title": "🐷 猪猪交易 · 成功", "badge": "-10 金币",
        "subtitle": "%s → %s，2 只超级肥猪，单价 5" % (ME, TARGET),
        "stats": [{"k": "共", "v": "10 金币"}, {"k": "买家金币", "v": "230"},
                  {"k": "卖家金币", "v": "260"}],
        "comment": C_TRADE,
    }),
    ("20_交易被拒", {
        "img": "assets/scene/night.png",
        "title": "🐷 交易已拒绝", "badge": "无损失",
        "subtitle": "%s 拒绝了你的询价（2 只超级肥猪，单价 5）" % TARGET,
        "stats": [{"k": "花费", "v": "0"}, {"k": "金币", "v": "240"}],
    }),

    # ==================== 21. 排行榜 ====================
    ("21_排行榜", {
        "img": "assets/scene/grass.png",
        "title": "🏆 猪猪数量榜 · 全村", "badge": "第 2 名",
        "subtitle": "最多显示前 10 名",
        "rows": [{"name": "1. %s" % TARGET, "v": "13 只"}, {"name": "2. %s" % ME, "v": "8 只"},
                 {"name": "3. 咕咕咕", "v": "6 只"}, {"name": "4. 小B", "v": "4 只"},
                 {"name": "5. 阿飘", "v": "2 只"}, {"name": "6. 路人甲", "v": "1 只"}],
        "tip": "试试：排行榜 全服 金币",
    }),

    # 22~23：规则 / 菜单已合并成一张「00_指令字典」（内容见 text/rules.py::command_card）

    # ==================== 22. 天降猪猪 ====================
    ("22_天降猪猪_货架", {
        "img": "assets/gudu/image.png",
        "title": "🐷 天降猪猪", "badge": "金币 240",
        "subtitle": "每种每天最多买 100 头",
        # 纵向一行一只（rows_cols=1）
        "rows": [{"name": "超级肥猪", "v": "12 币/只（还能买 100 头）"},
                 {"name": "神奇飞猪", "v": "24 币/只（还能买 100 头）"},
                 {"name": "鱼猪", "v": "36 币/只（还能买 100 头）"},
                 {"name": "咕嘟猪", "v": "60 币/只（还能买 100 头）"}],
        "rows_cols": 1,
        "lines": ["· 你的金币 240，最多能买 20 只超级肥猪",
                  "· 买法：猪猪游戏 天降猪猪 买 2只飞猪"],
    }),
    ("23_天降猪猪_成交", {
        "img": "assets/scene/farm.png",
        "title": "🐷 天降猪猪 · 成交", "badge": "-84 金币",
        "subtitle": "2只神奇飞猪、1只鱼猪 到手",
        "rows": [{"name": "神奇飞猪 ×2", "v": "48 金币"},
                 {"name": "鱼猪 ×1", "v": "36 金币"}],
        "rows_cols": 1,
        "stats": [{"k": "花费", "v": "84 金币"},
                  {"k": "剩余金币", "v": "156"},
                  {"k": "猪总数", "v": "11 只"}],
        "lines": ["· 今日还剩：超级肥猪 100 头、神奇飞猪 98 头、鱼猪 99 头、咕嘟猪 100 头"],
    }),
]

if __name__ == "__main__":
    import random
    os.makedirs(OUT, exist_ok=True)

    # 指令字典（帮助 / 菜单 / 游戏规则 发的就是这张）
    dic = os.path.join(OUT, "00_指令字典.png")
    make_card(command_card(), dic, height=2600)
    try:
        from PIL import Image
        print("[ 0/%d] %-16s %s" % (len(CARDS) + 1, "00_指令字典", Image.open(dic).size), flush=True)
    except Exception:
        print("[ 0/%d] %-16s ok" % (len(CARDS) + 1, "00_指令字典"), flush=True)

    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else len(CARDS)
    for i, (name, data) in enumerate(CARDS, 1):
        if not (lo <= i <= hi):
            continue
        data = dict(data)
        if data.pop("tip", "") is None:          # 后端有「💡 小知识」的卡才带 tip
            data["tip"] = random.choice(RULES_TIPS)
        height = 1700 if (data.get("lines") or data.get("rows")) else 1500
        png = os.path.join(OUT, name + ".png")
        make_card(data, png, height=height)
        try:
            from PIL import Image
            size = Image.open(png).size
        except Exception:
            size = "?"
        print("[%2d/%d] %-16s %s" % (i, len(CARDS), name, size), flush=True)
    print("\n完成 →", OUT)
