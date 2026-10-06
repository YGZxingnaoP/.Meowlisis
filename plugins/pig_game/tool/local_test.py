# -*- coding: utf-8 -*-
"""养猪游戏 · 本地离线模拟测试（完全不需要开 QQ / NapCat）。

================================ 用法 ================================
    cd D:\\.Meowlisis\\plugins\\pig_game
    python local_test.py          # 交互式：你扮演玩家，打中文口令，看机器人会发什么
    python local_test.py --demo   # 脚本化演示：自动跑一遍打卡/偷猪/抢猪/交易/跨天

说明：
  · 走的是【插件真实链路】：口令前缀 → 本地关键词解析 → 玩法执行 → 消息段发送，
    和线上 QQ 完全一致（唯一区别是把 NapCat 发送换成打印到控制台）。
  · 所有"发送"按 QQ 消息段顺序显示：[@某人] → [图片] → 正文。
  · 存档写在 pig_game/_testdata/，不污染正式 data/；`--demo` 每次用全新临时存档。
  · 图片用 assets/<猪种id>/image.png（缺失自动回退插件卡面 card.png）。

交互式额外命令（以 : 开头）：
    :help                 帮助
    :as 小B               切换当前玩家
    :new 小D              新建玩家
    :who                  列出玩家与猪圈
    :give 小B 超级肥猪 20  给某个玩家加猪
    :coins 10000          给当前玩家加金币
    :day 1                模拟时间前进 1 天（测每日刷新 / 池塘衰减）
    :private / :group      切换模拟私聊 / 群聊
    :at                   切换"群里有没有 @ 我"（演示不 @ 时不接管）
    :quit                 退出

指令直接打中文即可，例如：猪猪游戏 打卡 / 猪猪游戏 偷小B30只超级肥猪
===============================================================
"""

import datetime
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # pig_game/tool
PLUGIN_ROOT = os.path.dirname(HERE)
PLUGINS_ROOT = os.path.dirname(PLUGIN_ROOT)
if PLUGINS_ROOT not in sys.path:
    sys.path.insert(0, PLUGINS_ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pig_game.text import parse as pig_parse
from pig_game.text import rules as pig_rules
from pig_game.core.runner import PigRunner
from pig_game.core import engine as engine_mod

CONFIG_PATH = os.path.join(PLUGIN_ROOT, "config.yml")
ASSETS_DIR = os.path.join(PLUGIN_ROOT, "assets")
TEST_DATA_DIR = os.path.join(PLUGIN_ROOT, "_testdata")

DAY_OFFSET = {"n": 0}
_real_today = engine_mod.today


def fake_today():
    """带"模拟时间前进"的今天"""
    return (datetime.date.today() + datetime.timedelta(days=DAY_OFFSET["n"])).isoformat()


engine_mod.today = fake_today


# ============================================================================
# 假 NapCat：把消息段打到控制台
# ============================================================================
class FakeNapcat:
    def call_action_sync(self, action, params, timeout=5.0):
        segs = params.get("message") or []
        who = ("群 " + str(params.get("group_id"))) if "group_id" in params \
            else ("私聊 " + str(params.get("user_id")))
        print("┌─ 机器人发送 → %s（%s）" % (who, action))
        for seg in segs:
            t = seg.get("type")
            d = seg.get("data") or {}
            if t == "at":
                print("│ [@%s]" % d.get("qq"))
            elif t == "image":
                print("│ [图片] %s" % os.path.basename(str(d.get("file") or "")))
            elif t == "text":
                for line in str(d.get("text") or "").split("\n"):
                    print("│ " + line)
            else:
                print("│ [%s] %s" % (t, d))
        print("└─")
        return {"status": "ok", "retcode": 0, "data": {}}


class FakeLog:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def exception(self, *a, **k):
        pass


class FakeCtx:
    """只提供 napcat / config / log；LLM 走插件自己的配置（没配就走模板兜底）。"""

    def __init__(self, config):
        self.id = "pig_game"
        self.config = config
        self.log = FakeLog()
        self._napcat = FakeNapcat()

    def napcat(self):
        return self._napcat

    def llm(self):
        return None


class LocalApp(PigRunner):
    """复刻插件的运行器，只把发送换成控制台；玩法/解析与线上完全相同。"""

    def __init__(self, config_data, data_dir=None):
        super().__init__(FakeCtx(config_data), PLUGIN_ROOT, data_dir or TEST_DATA_DIR)

    def say(self, text, name, qq, group=None, at_self=True):
        """模拟「某个玩家发了一条消息」"""
        ctx = {"message_type": "group" if group else "private",
               "target_id": group or qq, "user_id": qq, "username": name}
        if group:
            ctx["group_id"] = group
            ctx["self_id"] = "12345"
        where = ("群 %s%s" % (group, "（已@）" if at_self else "（没@）")) if group else "私聊"
        print("\n>>> %s[%s] %s" % (name, where, text))
        ok = self.route(text, ctx, at_self=at_self)
        if not ok:
            print("（未接管 → 消息放行给主链路，插件不插手）")
        return ok


HELP = """额外命令（: 开头）：
  :help                本帮助
  :as 名字             切换当前玩家
  :new 名字            新建玩家
  :who                 列出玩家
  :give 名字 猪种 数量  给某人加猪
  :coins N             给当前玩家加金币
  :day N               模拟时间前进 N 天
  :private / :group    切换私聊 / 群聊
  :at                  切换群里有没有 @ 我
  :quit                退出
其它输入按中文口令解析，例如：猪猪游戏 打卡"""


def load_config():
    if not os.path.isfile(CONFIG_PATH):
        return {}
    try:
        import yaml
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def resolve_qq(app, name):
    for _sc, q, pl in app.store.all_players():
        if str(pl.get("nickname")) == name:
            return q
    return None


def interactive(app):
    qq, name = "10001", "小A"
    app.engine.ensure("private", qq, name)
    mode = {"group": False, "at": True}
    print(__doc__)
    print("已默认登录：%s（:%s）｜ 当前模拟：私聊\n" % (name, qq))

    while True:
        tag = "群聊@我" if mode["group"] and mode["at"] else ("群聊未@" if mode["group"] else "私聊")
        try:
            raw = input("%s[%s]> " % (name, tag)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue

        if raw.startswith(":"):
            parts = raw[1:].split()
            cmd = (parts[0].lower() if parts else "")
            arg = parts[1] if len(parts) > 1 else ""
            if cmd in ("quit", "q", "exit"):
                break
            elif cmd == "help":
                print(HELP)
            elif cmd == "as" and arg:
                q = resolve_qq(app, arg)
                if q:
                    name, qq = arg, q
                else:
                    print("  没这个玩家，用 :new 建一个")
            elif cmd == "new" and arg:
                q = str(20000 + len(list(app.store.all_players())))
                app.engine.ensure("private", q, arg)
                print("  新建 %s（QQ %s）" % (arg, q))
            elif cmd == "who":
                for sc, q, pl in app.store.all_players():
                    print("  [%s] %s(%s) 金币 %s 好感 %s 体力 %s 猪 %s 军队 %s"
                          % (sc, pl.get("nickname"), q, pl.get("coins"), pl.get("affinity"),
                             pl.get("stamina"), pl.get("pigs"), pl.get("army")))
            elif cmd == "give" and len(parts) > 2:
                q = resolve_qq(app, arg)
                sid = app.book.resolve(parts[2]) or parts[2]
                p = app.store.get_player("private", q) or app.store.get_player("group", q)
                if p:
                    p["pigs"][sid] = int(p["pigs"].get(sid, 0)) + int(parts[3] if len(parts) > 3 else 1)
                    app.store.save("players")
                    print("  已给 %s 加 %s" % (arg, sid))
                else:
                    print("  没找到玩家")
            elif cmd == "coins" and arg:
                p = app.store.get_player("private" if not mode["group"] else "group", qq)
                if p:
                    p["coins"] = int(p.get("coins") or 0) + int(arg)
                    app.store.save("players")
                    print("  金币 = %s" % p["coins"])
            elif cmd == "day" and arg:
                DAY_OFFSET["n"] += int(arg)
                print("  当前模拟日期：%s" % engine_mod.today())
            elif cmd == "group":
                mode["group"] = True
            elif cmd == "private":
                mode["group"] = False
            elif cmd == "at":
                mode["at"] = not mode["at"]
                print("  群里 @ 我 = %s" % mode["at"])
            else:
                print(HELP)
            continue

        app.say(raw, name, qq,
                group="777777" if mode["group"] else None,
                at_self=mode["at"])


# ============================================================================
# 脚本化演示
# ============================================================================
def demo(app):
    A, B = "10001", "10002"
    app.engine.ensure("private", A, "小A")
    app.engine.ensure("private", B, "小B")
    pb = app.store.get_player("private", B)
    pb["pigs"] = {"super_fat": 20, "flying": 3, "fish": 4}
    pb["coins"] = 500
    pb["army"] = {"super_fat": 8, "flying": 2}

    print("\n========== 零 LLM 接管判定（口令前缀 + 群聊需 @）==========")
    checks = [
        ("打卡", "private", True), ("偷小B30只超级肥猪", "private", True),
        ("猪猪游戏 打卡", "private", True), ("养猪游戏 查看猪圈", "private", True),
        ("猪猪游戏 打卡", "group", False), ("猪猪游戏 打卡", "group", True),
        ("猪猪游戏", "private", True),
    ]
    for text, mt, at in checks:
        cc = {"message_type": mt}
        print("  %-26s %-8s @=%-5s → %s"
              % (text, mt, at, "接管" if app.accept(text, cc, at) else "放行"))
    print("\n" + pig_rules.prefix_hint(app.cfg.prefixes()) + "\n")

    print("\n========== 本地关键词解析（零 LLM）==========")
    from pig_game.text import commands
    for text in ("猪猪游戏 打卡", "猪猪游戏 偷其乐容容30只超级肥猪",
                 "猪猪游戏 带领2只神奇飞猪去小B的地盘抢猪",
                 "猪猪游戏 假扮打卡小B", "猪猪游戏 出价6金币买小B2只超级肥猪",
                 "猪猪游戏 设置猪猪军队2只神奇飞猪1只鱼猪",
                 "猪猪游戏 排行榜 全服 金币", "猪猪游戏 打酱油"):
        tool, args, _ = commands.parse_command(text, app.cfg.prefixes())
        print("  %-32s → %s %s" % (text, tool or "（认不出）", args or ""))

    print("\n\n========== 玩法流程 ==========")
    app.say("猪猪游戏 游戏规则", "小A", A)
    app.say("猪猪游戏 打卡", "小A", A)
    app.say("猪猪游戏 和猪共进晚餐", "小A", A)
    app.say("猪猪游戏 设置猪猪军队 3只超级肥猪", "小A", A)
    app.say("猪猪游戏 偷小B30只超级肥猪", "小A", A)
    app.say("猪猪游戏 假扮打卡小B", "小A", A)
    app.say("猪猪游戏 查看猪圈", "小A", A)
    app.say("猪猪游戏 打卡", "小B", B)
    app.say("猪猪游戏 出价6金币买小B2只超级肥猪", "小A", A)
    app.say("猪猪游戏 接受交易", "小B", B)
    app.say("猪猪游戏 带领2只超级肥猪去小B的地盘抢猪", "小A", A)
    app.say("猪猪游戏 接受抢猪", "小B", B)
    app.say("猪猪游戏 设置猪圈场景 农场", "小A", A)
    app.say("猪猪游戏 排行榜 全服 金币", "小A", A)

    print("\n========== 群聊：不带 @ 不接管 ==========")
    app.say("猪猪游戏 打卡", "小A", A, group="888888", at_self=False)
    print("\n========== 群聊：@ 了才接管 ==========")
    app.say("猪猪游戏 打卡", "小A", A, group="888888", at_self=True)

    print("\n========== 模拟时间前进 4 天（体力刷新 + 池塘衰减）==========")
    DAY_OFFSET["n"] += 4
    app.say("猪猪游戏 查看猪圈", "小A", A)
    app.say("猪猪游戏 维护池塘", "小A", A)
    print("\n模拟日期：%s" % engine_mod.today())


def main():
    random.seed(20261006)
    cfg = load_config()
    if "--demo" in sys.argv:
        demo(LocalApp(cfg, data_dir=tempfile.mkdtemp(prefix="pig_demo_")))
    else:
        interactive(LocalApp(cfg))


if __name__ == "__main__":
    main()
