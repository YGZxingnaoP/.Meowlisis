# -*- coding: utf-8 -*-
"""养猪游戏：核心引擎（玩法编排 + 惰性每日结算）。"""

import datetime
import random
import time

from . import battle as bt
from ..text import parse
from ..text import rules
from . import trade as td


def today():
    return time.strftime("%Y-%m-%d")


def _days_between(a, b):
    try:
        da = datetime.date.fromisoformat(str(a))
        db = datetime.date.fromisoformat(str(b))
        return (db - da).days
    except Exception:
        return 0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# 场景 id 与中文名
SCENE_LABELS = {"grass": "草地", "farm": "农场", "night": "夜晚"}
SCENE_ALIASES = {"草地": "grass", "草原": "grass", "农场": "farm", "牧场": "farm",
                 "夜晚": "night", "晚上": "night", "夜景": "night"}


def scene_id(text, scenes):
    t = str(text or "").strip()
    if not t:
        return None
    if t in scenes:
        return t
    alias = SCENE_ALIASES.get(t)
    if alias and alias in scenes:
        return alias
    for sid in scenes:
        if SCENE_LABELS.get(sid) == t:
            return sid
    return None


def scene_hint(scenes):
    return " / ".join("%s(%s)" % (SCENE_LABELS.get(s, s), s) for s in scenes)



class Engine:
    """所有玩法逻辑。返回统一结果 dict：{"text": str, "image": 文件名或 None}"""

    def __init__(self, app):
        self.app = app
        self._members_cache = {}

    # ==================== 依赖快捷方式 ====================
    @property
    def cfg(self):
        return self.app.cfg

    @property
    def book(self):
        return self.app.book

    @property
    def store(self):
        return self.app.store

    @property
    def ctx(self):
        return self.app.ctx

    # ==================== 玩家 ====================
    def new_player(self, qq, nick):
        cfg, t = self.cfg, today()
        init = {}
        for sid, cnt in (cfg.init_pigs or {}).items():
            if self.book.get(sid):
                init[str(sid)] = int(cnt or 0)
        return {
            "qq": str(qq), "nickname": str(nick),
            "coins": int(cfg.coins_init), "stamina": int(cfg.stamina_max),
            "stamina_date": t, "affinity": int(cfg.affinity_init),
            "last_checkin_date": "", "checkin_blocked_date": "",
            "pond_last_maintain_date": t, "pond_decay_applied": 0,
            "shop_date": t, "shop_bought": {},
            "pigs": init, "army": {},
            "scene": (cfg.scenes[0] if cfg.scenes else "grass"),
            "joined_date": t,
        }

    def ensure(self, scope, qq, nick=""):
        """取/建玩家档案（存储键 = scope + QQ号，身份标准是 QQ号，昵称只是展示字段）。

        昵称只接受「真昵称」：空值或纯数字（内部编号 / QQ号）一律拒收并记 ERROR，
        绝不把编号/QQ号写进昵称位（否则私聊一句就把昵称刷成 000001）。
        """
        nick = str(nick or "").strip()
        if nick and nick.isdigit():
            self.ctx.log.error(f"[猪猪游戏] 拒绝把纯数字当昵称写入档案: qq={qq} nick={nick}")
            nick = ""
        p = self.store.get_player(scope, qq)
        if p is None:
            if not nick:
                self.ctx.log.error(f"[猪猪游戏] 建档缺少昵称: qq={qq}")
            p = self.new_player(qq, nick)
            self.store.put_player(scope, qq, p)
        elif nick and p.get("nickname") != nick:
            p["nickname"] = nick
        self.tick(p)
        return p

    def tick(self, p):
        """惰性每日结算：体力刷新 + 池塘衰减。"""
        cfg, t = self.cfg, today()
        if p.get("stamina_date") != t:
            p["stamina"] = int(cfg.stamina_max)
            p["stamina_date"] = t
        pigs = p.setdefault("pigs", {})
        last = p.get("pond_last_maintain_date") or t
        days = _days_between(last, t)
        if days >= int(cfg.pond_clear_days):
            if int(pigs.get("fish", 0) or 0) > 0:
                pigs["fish"] = 0
            p["pond_decay_applied"] = 0
        elif days >= int(cfg.pond_decay_start_days):
            target = days - (int(cfg.pond_decay_start_days) - 1)
            applied = int(p.get("pond_decay_applied") or 0)
            for _ in range(max(0, target - applied)):
                n = int(pigs.get("fish", 0) or 0)
                if n <= 0:
                    break
                loss = max(1, int(n * float(cfg.pond_decay_ratio)))
                pigs["fish"] = max(0, n - loss)
            p["pond_decay_applied"] = max(applied, target)
        else:
            p["pond_decay_applied"] = 0

    # ==================== 工具 ====================
    def _res(self, text, image=None):
        """提示类：参数缺失 / 报错 / 无需展示 → 发文字。"""
        return {"text": str(text or ""), "image": image}

    def _card(self, card, image=None):
        """结算类：只发图片。text 由卡片拍平成一行，仅用于日志与渲染失败兜底。"""
        data = dict(card or {})
        return {"text": self._flatten(data), "image": image, "card": data}

    @staticmethod
    def _flatten(card):
        """卡片 → 纯文本（日志 / 渲染失败时发出去）。"""
        out = [str(card.get("title") or "")]
        if card.get("badge"):
            out[0] += "  " + str(card["badge"])
        if card.get("subtitle"):
            out.append(str(card["subtitle"]))
        for s in card.get("stats") or []:
            if not s:
                continue
            if s.get("br"):
                out.append("")
                continue
            out.append("· %s %s" % (s.get("k"), s.get("v")))
        for r in card.get("rows") or []:
            out.append("%s %s" % (r.get("name"), r.get("v")))
        for g in card.get("groups") or []:
            out.append("【%s】" % g.get("title"))
            for it in g.get("items") or []:
                out.append("· " + (it.get("cmd") if isinstance(it, dict) else str(it)))
        for t in card.get("lines") or []:
            out.append(t.get("h") if isinstance(t, dict) else str(t))
        if card.get("comment"):
            out.append(str(card["comment"]))
        if card.get("tip"):
            out.append("💡 " + str(card["tip"]))
        return "\n".join(out)

    def _spend(self, p, key):
        cost = self.cfg.stamina(key)
        if int(p.get("stamina") or 0) < cost:
            return False, cost
        p["stamina"] = int(p.get("stamina") or 0) - cost
        return True, cost

    def _aff(self, p, delta):
        amax = int(self.cfg.affinity_max)
        p["affinity"] = _clamp(int(p.get("affinity") or 0) + int(delta), 0, amax)
        return p["affinity"]

    def _own_pigs_text(self, p):
        return parse.pigs_text(self.book, p.get("pigs"))

    def resolve_target(self, scope, name, qq_context=None):
        """昵称 → QQ：本群玩家 → 群成员列表 → 昵称映射。查不到返回 None。"""
        name = parse.clean_name(name)
        if not name:
            return None
        for q, pl in self.store.scope_players(scope).items():
            if str(pl["nickname"]) == name:
                return str(q)
        gid = None
        if qq_context and str(qq_context.get("message_type")) == "group":
            gid = qq_context.get("group_id") or qq_context.get("target_id")
        if gid:
            members = self._members(gid)
            for m in members:
                if str(m.get("card") or "") == name or str(m.get("nickname") or "") == name:
                    return str(m.get("user_id") or "")
            for m in members:
                if name and (name in str(m.get("card") or "") or name in str(m.get("nickname") or "")):
                    return str(m.get("user_id") or "")
        try:
            from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
            q = TBUserNicknameMap().reverse(name)
            if q:
                return str(q)
        except Exception:
            pass
        return None

    def _members(self, gid):
        key = str(gid)
        cached = self._members_cache.get(key)
        now = time.time()
        if cached and now - cached[0] < 60:
            return cached[1]
        data = []
        try:
            ret = self.ctx.napcat().call_action_sync("get_group_member_list",
                                                     {"group_id": int(gid)})
            if isinstance(ret, dict):
                data = ret.get("data") or ret.get("members") or []
            elif isinstance(ret, list):
                data = ret
        except Exception:
            data = []
        data = [m for m in data if isinstance(m, dict)]
        self._members_cache[key] = (now, data)
        return data

    def _date_allowed(self, dates):
        """obtain_dates 命中判定：命中任意一条即放行；空值表示不限时。

        每条规则支持（可混写）：
            "2026-12-25"               只此一天
            "12-25"                    每年 12-25
            "2026-10-06~2026-12-01"    时间段（含首尾）  ← 本次新增
            "10-06~12-01"              每年这个时间段
            "12-25~01-05"              跨年时间段（冬天这段）
            "2026-10-06~"              从这天起，之后都行
            "~2026-12-01"              到这天为止
        """
        if isinstance(dates, str):       # 允许直接写一个字符串
            dates = [dates]
        if not dates:
            return True
        rules = [str(r).strip() for r in dates]
        rules = [r for r in rules if r]  # 空串忽略
        if not rules:                    # 只剩空串 → 当不限时
            return True
        t = today()                     # "YYYY-MM-DD"
        md = t[5:]                      # "MM-DD"
        year = t[:4]
        for rule in rules:
            if self._date_hit(rule, t, md, year):
                return True
        return False

    @staticmethod
    def _date_hit(rule, t, md, year):
        """单条日期规则命中判定。"""
        r = str(rule or "").strip()
        if not r:
            return False
        for sep in ("～", "—", "－", "..", "至", "到"):
            r = r.replace(sep, "~")
        if "~" not in r:
            return r == t or r == md

        a, _, b = r.partition("~")
        a, b = a.strip(), b.strip()

        # 有一边带年份 → 按绝对日期比较
        if len(a) == 10 or len(b) == 10:
            if a and len(a) == 5:                 # "10-06~2026-12-01"
                a = year + "-" + a
            if b and len(b) == 5:
                b = year + "-" + b
            if a and b and a > b:                 # 跨年：终点推到下一年
                try:
                    b = str(int(b[:4]) + 1) + b[4:]
                except Exception:
                    return False
            if a and t < a:
                return False
            if b and t > b:
                return False
            return True

        # 两边都是 MM-DD → 每年同一段
        if a and b and a > b:                     # 跨年段，如 12-25~01-05
            return md >= a or md <= b
        if a and md < a:
            return False
        if b and md > b:
            return False
        return True


    # ==================== 入口 ====================
    def identity(self, qq_context):
        """从上下文取身份：qq=QQ号（存储键），nick=昵称（仅展示），meowid=内部编号（标准）。

        禁止兜底：QQ 号只认 user_id 一个来源；昵称只认 nickname。
        """
        mt = str(qq_context.get("message_type") or "private")
        if mt == "group":
            scope = str(qq_context.get("group_id") or "")
        else:
            scope = "private"
        qq = str(qq_context.get("user_id") or "")
        nick = str(qq_context.get("nickname") or "")
        return mt, scope, qq, nick

    def handle(self, tool, arguments, qq_context):
        args = arguments or {}
        mt, scope, qq, nick = self.identity(qq_context)
        if not qq:
            return self._res(rules.invalid("没能识别出你的身份（缺少 QQ 号）"))
        if not nick:
            return self._res(rules.invalid("没能识别出你的昵称（身份不完整）"))
        p = self.ensure(scope, qq, nick)
        name = str(tool or "")
        if name.startswith("pig_"):
            name = name[4:]
        fn = getattr(self, "_cmd_" + name, None)
        try:
            res = fn(scope, qq, p, args, qq_context) if fn else self._res(rules.MENU)
        except Exception:
            try:
                self.ctx.log.exception("养猪游戏：执行指令失败 %s" % tool)
            except Exception:
                pass
            res = self._res(rules.missing(["刚才这条指令没能处理，请检查一下写法"], "游戏规则"))
        # 被动提醒（对方下次交互时给出）
        try:
            notes = self.store.take_notes(scope, qq)
            if notes:
                res["text"] = (res.get("text") or "") + "\n\n【📮 有人找你】\n" + "\n".join(notes)
        except Exception:
            pass
        self.store.save_all()
        return res

    # ==================== 打卡 ====================
    def _cmd_checkin(self, scope, qq, p, args, qq_context):
        cfg = self.cfg
        t = today()
        if p.get("last_checkin_date") == t:
            return self._res(rules.invalid("你今天已经打过卡啦，明天再来吧"))
        if p.get("checkin_blocked_date") == t:
            return self._res(rules.invalid("你今天被人假扮了，猪圈门被锁上，没法打卡"))

        amax = max(1, int(cfg.affinity_max))
        breed, dead = [], []
        for sp in self.book.all():
            b = sp.get("breed") or {}
            sid = str(sp["id"])
            n = int(p["pigs"].get(sid, 0) or 0)
            if not b.get("enabled") or n <= 0:
                continue
            cap = max(1, int(b.get("cap") or 1))
            if n >= cap:
                continue
            p_eff = (float(b.get("base_prob") or 0) * max(0.0, 1 - n / cap)
                     * (1 + float(b.get("aff_influence") or 0) * int(p.get("affinity") or 0) / amax))
            if random.random() < _clamp(p_eff, 0.0, 1.0):
                amt = min(int(b.get("amount") or 1), cap - n)
                if amt > 0:
                    p["pigs"][sid] = n + amt
                    breed.append((sp, amt, n + amt))

        income = 0
        for sp in self.book.all():
            income += int(p["pigs"].get(str(sp["id"]), 0) or 0) * int(sp.get("coin_per_day") or 0)
        p["coins"] = int(p.get("coins") or 0) + income

        for sp in self.book.all():
            dp = float(sp.get("death_prob") or 0)
            sid = str(sp["id"])
            n = int(p["pigs"].get(sid, 0) or 0)
            if dp <= 0 or n <= 0:
                continue
            lost = sum(1 for _ in range(n) if random.random() < dp)
            if lost:
                p["pigs"][sid] = n - lost
                dead.append((sp, lost))

        p["last_checkin_date"] = t
        day_no = _days_between(p.get("joined_date"), t) + 1

        comment = self.app.llm.comment(
            "checkin",
            "繁殖 %s；金币 +%d；好感度 %d；体力 %d" % (
                "、".join("%s+%d" % (sp["name"], amt) for sp, amt, _ in breed) or "无",
                income, int(p["affinity"]), int(p["stamina"])))

        image = None
        if breed:
            image = self.app.pig_image(str(random.choice(breed)[0]["id"]))
        else:
            owned = [str(sp["id"]) for sp in self.book.all() if int(p["pigs"].get(str(sp["id"]), 0) or 0) > 0]
            if owned:
                image = self.app.pig_image(random.choice(owned))

        if breed:
            sub = "繁殖：" + "、".join("%s +%d（现有 %d）" % (sp["name"], amt, total)
                                     for sp, amt, total in breed)
        else:
            sub = "今天猪猪们有点安静，没有新的小猪诞生"
        if dead:
            sub += "；意外：" + "、".join("%s 撞死 %d 只" % (sp["name"], lost) for sp, lost in dead)
        return self._card({
            "title": "🐷 打卡成功", "badge": "第 %d 天" % max(1, day_no),
            "subtitle": sub,
            "stats": [{"k": "今日收益", "v": "+%d" % income},
                      {"k": "累计金币", "v": "%d" % int(p["coins"])},
                      {"k": "好感度", "v": "%d" % int(p["affinity"])},
                      {"k": "体力", "v": "%d" % int(p["stamina"])}],
            "comment": comment, "tip": random.choice(rules.TIPS),
        }, image=image)

    # ==================== 假扮打卡 ====================
    def _cmd_fake(self, scope, qq, p, args, qq_context):
        name = parse.clean_name(args.get("target"))
        if not name:
            return self._res(rules.missing(["缺少：目标玩家"], "假扮打卡@其乐容容"))
        tqq = self.resolve_target(scope, name, qq_context)
        if tqq == qq:
            return self._res(rules.invalid("不能假扮自己的猪圈"))
        if not tqq:
            return self._res(rules.missing(["目标玩家「%s」没找到（要写对方昵称）" % name],
                                           "假扮打卡@其乐容容"))
        tp = self.store.get_player(scope, tqq)
        if tp is None or parse.total_pigs(tp.get("pigs")) <= 0:
            return self._res(rules.invalid("对方还没有开始养猪，没得假扮"))
        self.tick(tp)
        t = today()
        if tp.get("checkin_blocked_date") == t:
            return self._res(rules.invalid("对方今天已经被假扮过了，猪圈门锁着呢"))
        if tp.get("last_checkin_date") == t:
            return self._res(rules.invalid("对方今天已经打过卡了，假扮没有意义"))
        ok, cost = self._spend(p, "fake")
        if not ok:
            return self._res(rules.invalid("体力不足，假扮打卡需要 %d 点体力" % cost))

        amax = max(1, int(self.cfg.affinity_max))
        discover = _clamp(float(tp.get("affinity") or 0) / amax * float(self.cfg.fake_discover_ratio), 0.0, 1.0)
        name_t = str(tp["nickname"])
        if random.random() < discover:
            comment = self.app.llm.comment("fake", "假扮失败，被拱出对方猪圈")
            return self._card({
                "title": "🐷 假扮打卡 · 被识破", "badge": "被拱出去了",
                "subtitle": "你刚溜进 %s 的猪圈，就被里面的猪猪一眼看穿" % name_t,
                "stats": [{"k": "获得", "v": "0 金币"},
                          {"k": "体力", "v": "%d" % int(p["stamina"])},
                          {"k": "消耗体力", "v": "%d" % cost}],
                "comment": comment,
            }, image=self.app.pig_image("super_fat"))

        income = 0
        for sp in self.book.all():
            income += int(tp["pigs"].get(str(sp["id"]), 0) or 0) * int(sp.get("coin_per_day") or 0)
        stolen = int(income * float(self.cfg.fake_steal_ratio))
        p["coins"] = int(p.get("coins") or 0) + stolen
        tp["checkin_blocked_date"] = t
        self.store.add_note(scope, tqq,
                            "%s 假扮了你的猪圈，你今天无法打卡了！" % str(p["nickname"]))
        comment = self.app.llm.comment("fake", "假扮成功，偷了对方当日产出")
        top = None
        for sp in self.book.all():
            n = int(tp["pigs"].get(str(sp["id"]), 0) or 0)
            if n > 0 and (top is None or n > top[1]):
                top = (str(sp["id"]), n)
        return self._card({
            "title": "🐷 假扮打卡 · 成功", "badge": "+%d 金币" % stolen,
            "subtitle": "你混进了 %s 的猪圈，蹭到了一份产出；他今天被锁了猪圈" % name_t,
            "stats": [{"k": "窃取金币", "v": "+%d" % stolen},
                      {"k": "累计金币", "v": "%d" % int(p["coins"])},
                      {"k": "体力", "v": "%d" % int(p["stamina"])},
                      {"k": "消耗体力", "v": "%d" % cost}],
            "comment": comment,
        }, image=self.app.pig_image(top[0] if top else "super_fat"))

    # ==================== 偷猪 ====================
    def _cmd_steal(self, scope, qq, p, args, qq_context):
        cfg = self.cfg
        name = parse.clean_name(args.get("target"))
        if not name:
            return self._res(rules.missing(["缺少：目标玩家"], "偷其乐容容30只超级肥猪"))
        tqq = self.resolve_target(scope, name, qq_context)
        if tqq == qq:
            return self._res(rules.invalid("不能偷自己的猪"))
        if not tqq:
            return self._res(rules.missing(["目标玩家「%s」没找到（要写对方昵称）" % name],
                                           "偷其乐容容30只超级肥猪"))
        tp = self.store.get_player(scope, tqq)
        if tp is None:
            return self._res(rules.invalid("对方还没有开始养猪，偷不到东西"))
        self.tick(tp)

        raw_species = args.get("species")
        sid = self.book.resolve(raw_species) if raw_species else None
        if raw_species and not sid:
            return self._res(rules.invalid("没有「%s」这种猪" % str(raw_species).strip()))

        cnt = parse.extract_int(args.get("count"))
        if cnt is None:
            cnt = int(cfg.steal_default_count)
        if cnt <= 0:
            return self._res(rules.invalid("偷猪数量要大于 0", "偷其乐容容3只超级肥猪"))

        if not sid:
            pool = [str(sp["id"]) for sp in self.book.all()
                    if sp.get("stealable") and int(tp["pigs"].get(str(sp["id"]), 0) or 0) > 0]
            if not pool:
                return self._res(rules.invalid("对方猪圈里没有能被偷的猪"))
            sid = random.choice(pool)

        sp = self.book.get(sid)
        if not sp or not sp.get("stealable"):
            return self._res(rules.invalid("%s 是魔法猪，偷不走" % (sp["name"] if sp else "这种猪")))
        own = int(tp["pigs"].get(sid, 0) or 0)
        if own <= 0:
            return self._res(rules.invalid("对方没有 %s 可以偷" % sp["name"]))
        take = min(cnt, own, int(cfg.steal_max_per_time))

        ok, cost = self._spend(p, "steal")
        if not ok:
            return self._res(rules.invalid("体力不足，偷猪需要 %d 点体力" % cost))

        amax = max(1, int(cfg.affinity_max))
        prob = _clamp(float(sp.get("steal_rate") or 0)
                      * (1 - float(tp.get("affinity") or 0) / amax * float(cfg.steal_affinity_discount)),
                      float(cfg.steal_min_prob), 1.0)
        name_t = str(tp["nickname"])
        if random.random() >= prob:
            comment = self.app.llm.comment("steal", "偷猪失败，空手而归")
            return self._card({
                "title": "🐷 偷猪 · 失败", "badge": "空手而归",
                "subtitle": "摸到 %s 的猪圈，一只 %s 都没牵走" % (name_t, sp["name"]),
                "stats": [{"k": "偷到", "v": "0 只"},
                          {"k": "体力", "v": "%d" % int(p["stamina"])},
                          {"k": "消耗体力", "v": "%d" % cost}],
                "comment": comment, "tip": random.choice(rules.TIPS),
            }, image=self.app.pig_image(sid))

        before = int(p["pigs"].get(sid, 0) or 0)
        tp["pigs"][sid] = own - take
        p["pigs"][sid] = before + take
        self.store.add_note(scope, tqq,
                            "%s 从你的猪圈偷走了 %d 只%s！" % (str(p["nickname"]), take, sp["name"]))
        comment = self.app.llm.comment("steal", "偷猪成功，偷到 %d 只%s" % (take, sp["name"]))
        return self._card({
            "title": "🐷 偷猪 · 成功", "badge": "偷走 %d 只" % take,
            "subtitle": "从 %s 的猪圈偷走了 %d 只%s" % (name_t, take, sp["name"]),
            "stats": [{"k": "你的%s" % sp["name"], "v": "%d → %d" % (before, before + take)},
                      {"k": "体力", "v": "%d" % int(p["stamina"])},
                      {"k": "消耗体力", "v": "%d" % cost}],
            "comment": comment, "tip": random.choice(rules.TIPS),
        }, image=self.app.pig_image(sid))

    # ==================== 猪猪军队 ====================
    def _cmd_army(self, scope, qq, p, args, qq_context):
        squad = parse.parse_squad(self.book, args.get("squad") or args.get("request") or "")
        if not squad:
            return self._res(rules.missing(["缺少：守军编队"], "设置猪猪军队2只神奇飞猪1只鱼猪"))
        lack = []
        for sid, cnt in squad.items():
            have = int(p["pigs"].get(sid, 0) or 0)
            if int(cnt) > have:
                lack.append("%s 只有 %d 只，编不进 %d 只" % (self.book.name(sid), have, int(cnt)))
        if lack:
            return self._res(rules.invalid("；".join(lack), "设置猪猪军队2只神奇飞猪1只鱼猪"))
        p["army"] = {str(k): int(v) for k, v in squad.items()}
        squad_text = parse.squad_text(self.book, p["army"])
        return self._card({
            "title": "🐷 猪猪军队已就位", "badge": "守军 %d 只"
            % sum(int(v or 0) for v in p["army"].values()),
            "subtitle": "守军：%s" % squad_text,
            "stats": [{"k": "免战", "v": "已生效"}],
        }, image=self.app.pig_image("flying"))

    # ==================== 抢猪 ====================
    def _cmd_raid(self, scope, qq, p, args, qq_context):
        action = str(args.get("action") or "").strip().lower()
        if action in ("accept", "接受", "迎战"):
            return self._raid_accept(scope, qq, p)
        if action in ("reject", "拒绝", "拒战"):
            return self._raid_reject(scope, qq, p)
        if action in ("force", "强制", "强制进攻"):
            return self._raid_force(scope, qq, p, args, qq_context)
        return self._raid_start(scope, qq, p, args, qq_context)

    def _raid_start(self, scope, qq, p, args, qq_context):
        name = parse.clean_name(args.get("target"))
        if not name:
            return self._res(rules.missing(["缺少：目标玩家"], "带领2只神奇飞猪去其乐容容的地盘抢猪"))
        tqq = self.resolve_target(scope, name, qq_context)
        if tqq == qq:
            return self._res(rules.invalid("不能抢自己的猪圈"))
        if not tqq:
            return self._res(rules.missing(["目标玩家「%s」没找到（要写对方昵称）" % name],
                                           "带领2只神奇飞猪去其乐容容的地盘抢猪"))
        tp = self.store.get_player(scope, tqq)
        if tp is None or not any(int(v or 0) > 0 for v in (tp.get("army") or {}).values()):
            return self._res(rules.invalid("对方还没有设置猪猪军队，不能发起抢猪"))
        squad = parse.parse_squad(self.book, args.get("squad") or args.get("request") or "")
        if not squad:
            return self._res(rules.missing(["缺少：出征的猪猪编队"], "带领2只神奇飞猪去其乐容容的地盘抢猪"))
        for sid, cnt in squad.items():
            if int(cnt) > int(p["pigs"].get(sid, 0) or 0):
                return self._res(rules.invalid("你没有那么多%s" % self.book.name(sid)))
        bid = "%s-%d" % (qq, int(time.time() * 1000))
        self.store.battles.append({
            "id": bid, "scope": str(scope), "attacker": str(qq), "defender": str(tqq),
            "squad": {str(k): int(v) for k, v in squad.items()},
            "status": "pending", "date": today(),
        })
        self.store.add_note(scope, tqq,
                            "%s 带着 %s 来抢你的猪圈了！回复「接受抢猪」或「拒绝抢猪」"
                            % (str(p["nickname"]), parse.squad_text(self.book, squad)))
        return self._card({
            "title": "⚔️ 抢猪 · 已发起", "badge": "待应战",
            "subtitle": "你带 %s 前往 %s 的地盘" % (parse.squad_text(self.book, squad),
                                              str(tp["nickname"])),
            "stats": [{"k": "出征", "v": "%d 只" % sum(int(v or 0) for v in squad.values())},
                      {"k": "状态", "v": "等对方回应"}],
        }, image=self.app.pig_image("flying"))

    def _find_battle(self, scope, key_field, qq, status=None):
        for b in self.store.battles:
            if str(b.get("scope")) != str(scope):
                continue
            if str(b.get(key_field)) != str(qq):
                continue
            if status and b.get("status") != status:
                continue
            return b
        return None

    def _raid_accept(self, scope, qq, p):
        b = self._find_battle(scope, "defender", qq, status="pending")
        if not b:
            return self._res(rules.invalid("你当前没有待处理的抢猪邀请"))
        return self._resolve_battle(scope, b, forced=False)

    def _raid_reject(self, scope, qq, p):
        b = self._find_battle(scope, "defender", qq, status="pending")
        if not b:
            return self._res(rules.invalid("你当前没有待处理的抢猪邀请"))
        b["status"] = "rejected"
        self.store.add_note(scope, b["attacker"],
                            "%s 拒绝了你的抢猪，你可以「强制进攻 %s」（多花体力）"
                            % (str(p["nickname"]), str(p["nickname"])))
        return self._card({
            "title": "⚔️ 抢猪 · 已拒绝", "badge": "无损失",
            "subtitle": "你回绝了这次抢猪，对方仍可能强制进攻",
            "stats": [{"k": "体力", "v": "%d" % int(p.get("stamina") or 0)},
                      {"k": "状态", "v": "已回绝"}],
        }, image=self.app.scene_image(str(p.get("scene") or "")))

    def _raid_force(self, scope, qq, p, args, qq_context):
        name = parse.clean_name(args.get("target"))
        b = None
        if name:
            tqq = self.resolve_target(scope, name, qq_context)
            for item in self.store.battles:
                if (str(item.get("scope")) == str(scope) and str(item.get("attacker")) == str(qq)
                        and str(item.get("defender")) == str(tqq or "") and item.get("status") == "rejected"):
                    b = item
                    break
        if b is None:
            b = self._find_battle(scope, "attacker", qq, status="rejected")
        if not b:
            return self._res(rules.invalid("没有可以强制进攻的目标（要先被对方拒绝）",
                                           "强制进攻其乐容容"))
        return self._resolve_battle(scope, b, forced=True)

    def _trim_squad(self, book, player, squad):
        out = {}
        for sid, cnt in (squad or {}).items():
            have = int(player["pigs"].get(str(sid), 0) or 0)
            c = min(int(cnt or 0), have)
            if c > 0:
                out[str(sid)] = c
        return out

    def _take_pigs(self, loser, winner, take):
        pool = [sp for sp in self.book.all()
                if sp.get("type") != "magic" and int(loser["pigs"].get(str(sp["id"]), 0) or 0) > 0]
        random.shuffle(pool)
        got, remain = [], int(take)
        for sp in pool:
            if remain <= 0:
                break
            sid = str(sp["id"])
            n = int(loser["pigs"].get(sid, 0) or 0)
            c = min(n, remain)
            if c <= 0:
                continue
            loser["pigs"][sid] = n - c
            winner["pigs"][sid] = int(winner["pigs"].get(sid, 0) or 0) + c
            got.append((sp, c))
            remain -= c
        return got

    def _resolve_battle(self, scope, b, forced):
        cfg = self.cfg
        ap = self.store.get_player(scope, b["attacker"])
        dp = self.store.get_player(scope, b["defender"])
        if ap is None or dp is None:
            try:
                self.store.battles.remove(b)
            except Exception:
                pass
            return self._res(rules.invalid("这场抢猪的对手已经不存在了"))
        self.tick(ap)
        self.tick(dp)
        squad = self._trim_squad(self.book, ap, b.get("squad"))
        army = self._trim_squad(self.book, dp, dp.get("army"))
        if not squad:
            try:
                self.store.battles.remove(b)
            except Exception:
                pass
            return self._res(rules.invalid("你的出征猪猪已经不够了，抢猪取消"))
        if not army:
            try:
                self.store.battles.remove(b)
            except Exception:
                pass
            return self._res(rules.invalid("对方的猪猪军队已经散了，抢猪取消"))

        key = "raid_force" if forced else "raid"
        ok, cost = self._spend(ap, key)
        if not ok:
            return self._res(rules.invalid("体力不足，%s需要 %d 点体力"
                                           % ("强制进攻" if forced else "抢猪", cost)))

        pa, da = bt.team_points(cfg, self.book, squad)
        pb, db = bt.team_points(cfg, self.book, army)
        prob = bt.win_prob(cfg, pa, pb)
        attacker_win = random.random() < prob
        delta = abs(pa - pb)
        take = bt.take_count(cfg, delta)
        if attacker_win:
            got = self._take_pigs(dp, ap, take)
            winner, loser = ap, dp
        else:
            got = self._take_pigs(ap, dp, take)
            winner, loser = dp, ap

        got_text = "、".join("%s×%d" % (sp["name"], c) for sp, c in got) or "啥也没捞到"
        # 不向玩家暴露点数：只给说书人「双方编队 + 结果」，点数只用于内部结算
        facts = ("攻方 %s（%s）；守方 %s（%s）；胜者 %s；夺取 %s；双方鏖战一场，互有损伤"
                 % (str(ap["nickname"]), parse.squad_text(self.book, squad),
                    str(dp["nickname"]), parse.squad_text(self.book, army),
                    str(winner["nickname"]), got_text))
        report = self.app.llm.battle_report(facts)

        lines = []

        other = b["defender"] if str(winner.get("qq")) == str(b["attacker"]) else b["attacker"]
        self.store.add_note(scope, other,
                            "猪猪大战结束：%s 获胜，夺得 %s" % (str(winner["nickname"]), got_text))
        try:
            self.store.battles.remove(b)
        except Exception:
            pass
        img = self.app.pig_image(str(got[0][0]["id"])) if got else self.app.pig_image("flying")
        return self._card({
            "title": "⚔️ 猪猪大战 · 战报", "badge": "%s 获胜" % str(winner["nickname"]),
            "subtitle": "攻方 %s　vs　守方 %s" % (parse.squad_text(self.book, squad),
                                                parse.squad_text(self.book, army)),
            "stats": [{"k": "夺得", "v": got_text},
                      {"k": "攻方体力", "v": "-%d" % cost},
                      {"k": "剩余体力", "v": "%d" % int(ap.get("stamina") or 0)}],
            "comment": report, "tip": random.choice(rules.TIPS),
        }, image=img)

    # ==================== 养互动 ====================
    def _cmd_care(self, scope, qq, p, args, qq_context):
        raw = str(args.get("action") or "").strip().lower()
        table = {
            "ride": ("ride", "骑猪"), "骑猪": ("ride", "骑猪"),
            "clean": ("clean", "打扫猪圈"), "打扫": ("clean", "打扫猪圈"), "打扫猪圈": ("clean", "打扫猪圈"),
            "dinner": ("dinner", "和猪共进晚餐"), "晚餐": ("dinner", "和猪共进晚餐"),
            "共进晚餐": ("dinner", "和猪共进晚餐"), "和猪共进晚餐": ("dinner", "和猪共进晚餐"),
            "patrol": ("patrol", "巡视猪圈"), "巡视": ("patrol", "巡视猪圈"), "巡视猪圈": ("patrol", "巡视猪圈"),
        }
        item = table.get(raw)
        if not item:
            return self._res(rules.missing(
                ["缺少：互动动作（骑猪 / 打扫猪圈 / 和猪共进晚餐 / 巡视猪圈）"],
                "打扫猪圈"))
        key, label = item
        ok, cost = self._spend(p, key)
        if not ok:
            return self._res(rules.invalid("体力不足，%s 需要 %d 点体力" % (label, cost)))
        delta = self.cfg.aff_delta(key)
        aff = self._aff(p, delta)
        sub = {"ride": "骑猪很爽，但猪猪有点不高兴",
               "patrol": "巡视一圈，一切正常"}.get(key, self._own_pigs_text(p))
        return self._card({
            "title": "🐷 %s" % label,
            "badge": "好感 %s%d" % ("+" if delta >= 0 else "", delta),
            "subtitle": sub,
            "stats": [{"k": "好感度", "v": "%d → %d" % (aff - delta, aff)},
                      {"k": "体力", "v": "%d" % int(p["stamina"])},
                      {"k": "消耗体力", "v": "%d" % cost}],
        }, image=self.app.pig_image("super_fat"))

    # ==================== 池塘 ====================
    def _cmd_pond(self, scope, qq, p, args, qq_context):
        cfg = self.cfg
        cost = int(cfg.pond_cost)
        if int(p.get("coins") or 0) < cost:
            return self._res(rules.invalid("金币不足，维护池塘需要 %d 金币" % cost))
        p["coins"] = int(p["coins"]) - cost
        p["pond_last_maintain_date"] = today()
        p["pond_decay_applied"] = 0
        fish = int(p["pigs"].get("fish", 0) or 0)
        return self._card({
            "title": "🐷 池塘已维护", "badge": "-%d 金币" % cost,
            "subtitle": "鱼猪 ×%d 暂时安全了（%d 天不维护开始消失，%d 天全没）"
                        % (fish, int(cfg.pond_decay_start_days), int(cfg.pond_clear_days)),
            "stats": [{"k": "花费", "v": "%d" % cost},
                      {"k": "剩余金币", "v": "%d" % int(p["coins"])},
                      {"k": "鱼猪", "v": "%d 只" % fish}],
        }, image=self.app.pig_image("fish"))

    # ==================== 合成魔法猪 ====================
    def _cmd_craft(self, scope, qq, p, args, qq_context):
        raw = args.get("magic") or args.get("request")
        sid = self.book.resolve(raw)
        sp = self.book.get(sid) if sid else None
        if not sp or sp.get("type") != "magic":
            return self._res(rules.missing(["缺少：要合成的魔法猪名（例如咕嘟猪）"], "合成咕嘟猪"))
        recipe = sp.get("craft") or {}
        if not recipe:
            return self._res(rules.invalid("%s 还没有合成配方" % sp["name"]))
        if not self._date_allowed(sp.get("obtain_dates")):
            return self._res(rules.invalid("%s 是限定款，今天不是它的可获取日期" % sp["name"]))
        lack = []
        for mid, need in recipe.items():
            have = int(p["pigs"].get(str(mid), 0) or 0)
            if have < int(need):
                lack.append("%s 需要 %d 只，你有 %d 只" % (self.book.name(mid), int(need), have))
        if lack:
            return self._res(rules.invalid("材料不够：" + "；".join(lack), "合成咕嘟猪"))
        for mid, need in recipe.items():
            p["pigs"][str(mid)] = int(p["pigs"].get(str(mid), 0) or 0) - int(need)
        p["pigs"][str(sp["id"])] = int(p["pigs"].get(str(sp["id"]), 0) or 0) + 1
        used = "、".join("%d只%s" % (int(n), self.book.name(m)) for m, n in recipe.items())
        return self._card({
            "title": "🐷 合成成功", "badge": "%s +1" % sp["name"],
            "subtitle": "消耗 %s，炼出了 1 只 %s" % (used, sp["name"]),
            "stats": [{"k": sp["name"], "v": "%d 只" % int(p["pigs"].get(str(sp["id"]), 0))},
                      {"k": "消耗", "v": "、".join("%s×%d" % (self.book.name(m), int(n))
                                                  for m, n in recipe.items())}],
        }, image=self.app.pig_image(str(sp["id"])))

    # ==================== 天降猪猪（买猪商店） ====================
    def _shop_offers(self):
        """当前上架的猪种 [(sid, sp, price)]。

        不上架的直接不进列表（前端就不会显示）：
          · shop_price 没写或 <= 0
          · 魔法猪的 obtain_dates 今天不在可获取日期内
        """
        out = []
        for sp in self.book.all():
            try:
                price = int(sp.get("shop_price") or 0)
            except Exception:
                price = 0
            if price <= 0:
                continue
            if not self._date_allowed(sp.get("obtain_dates")):
                continue
            out.append((str(sp["id"]), sp, price))
        out.sort(key=lambda x: x[2])          # 便宜的排前面
        return out

    @staticmethod
    def _shop_reset(p, t):
        """跨天就把当天限购清零（跟体力一样惰性刷新）。"""
        if p.get("shop_date") != t or not isinstance(p.get("shop_bought"), dict):
            p["shop_date"] = t
            p["shop_bought"] = {}

    def _cmd_shop(self, scope, qq, p, args, qq_context):
        cfg = self.cfg
        if not bool(getattr(cfg, "shop_enabled", True)):
            return self._res(rules.invalid("天降猪猪今天没开张"))
        t = today()
        self._shop_reset(p, t)
        offers = self._shop_offers()
        if not offers:
            return self._res(rules.invalid("天降猪猪今天没货，明天再来看看"))

        limit = int(getattr(cfg, "shop_daily_limit", 100) or 0)      # 0 = 不限购
        bought = p["shop_bought"]

        def left_of(sid):
            if limit <= 0:
                return None                                          # None = 不限
            return max(0, limit - int(bought.get(sid, 0) or 0))

        want = args.get("items") or {}
        if not want:                                                 # 只喊了店名 → 看货
            return self._shop_shelf_card(p, offers, left_of, limit)

        price_of = {sid: pr for sid, _sp, pr in offers}
        ok, fail = [], []
        for word, n in want.items():
            sid = self.book.resolve(word)
            sp = self.book.get(sid) if sid else None
            if not sp:
                fail.append("认不出「%s」这个猪种" % word)
                continue
            if sid not in price_of:
                if not self._date_allowed(sp.get("obtain_dates")):
                    fail.append("%s 今天不在可获取日期内" % sp["name"])
                else:
                    fail.append("%s 天降猪猪不卖" % sp["name"])
                continue
            price = price_of[sid]
            n = max(1, int(n or 1))
            left = left_of(sid)
            if left is not None:
                if left <= 0:
                    fail.append("%s 今天已经买满 %d 头了，明天再来" % (sp["name"], limit))
                    continue
                if n > left:
                    fail.append("%s 今天只剩 %d 头额度（每样每天 %d 头），这次按 %d 头算"
                                % (sp["name"], left, limit, left))
                    n = left
            cost = price * n
            coins = int(p.get("coins") or 0)
            if coins < cost:
                fail.append("%s %d 头要 %d 金币，你只有 %d（还差 %d）"
                            % (sp["name"], n, cost, coins, cost - coins))
                continue
            stamina = int(getattr(cfg, "shop_stamina_cost", 0) or 0)
            if stamina > 0:
                if int(p.get("stamina") or 0) < stamina:
                    fail.append("体力不足，买猪要 %d 点体力" % stamina)
                    continue
                p["stamina"] = int(p.get("stamina") or 0) - stamina
            p["coins"] = coins - cost
            p["pigs"][sid] = int(p["pigs"].get(sid, 0) or 0) + n
            bought[sid] = int(bought.get(sid, 0) or 0) + n
            ok.append({"sid": sid, "name": sp["name"], "n": n, "cost": cost})

        if not ok:
            return self._res(rules.invalid("没买成——\n" + "\n".join("· " + x for x in fail),
                                           "天降猪猪 买 2只飞猪"))

        total = sum(x["cost"] for x in ok)
        lines = []
        lefts = ["%s %d 头" % (self.book.name(sid), left_of(sid))
                 for sid, _sp, _pr in offers if left_of(sid) is not None]
        if lefts:
            lines.append("· 今日还剩：" + "、".join(lefts))
        if fail:
            lines.append("· 没买成：" + "；".join(fail))
        return self._card({
            "title": "🐷 天降猪猪 · 成交",
            "badge": "-%d 金币" % total,
            "subtitle": "%s 到手" % "、".join("%d只%s" % (x["n"], x["name"]) for x in ok),
            "rows": [{"name": "%s ×%d" % (x["name"], x["n"]), "v": "%d 金币" % x["cost"]}
                     for x in ok],
            "rows_cols": 1,
            "stats": [{"k": "花费", "v": "%d 金币" % total},
                      {"k": "剩余金币", "v": "%d" % int(p.get("coins") or 0)},
                      {"k": "猪总数", "v": "%d 只" % parse.total_pigs(p.get("pigs"))}],
            "lines": lines,
        }, image=self.app.pig_image(ok[0]["sid"]))

    def _shop_shelf_card(self, p, offers, left_of, limit):
        """只喊「天降猪猪」→ 货架：一行一只，纵向排。"""
        coins = int(p.get("coins") or 0)
        rows = []
        for sid, sp, price in offers:
            left = left_of(sid)
            v = "%d 币/只" % price
            if left is not None:
                v += "（还能买 %d 头）" % left
            rows.append({"name": sp["name"], "v": v})
        lines = []
        cheapest = min(pr for _s, _p, pr in offers)
        lines.append("· 你的金币 %d，最多能买 %d 只%s" % (coins, coins // cheapest,
                                                        [sp["name"] for _s, sp, pr in offers
                                                         if pr == cheapest][0]))
        lines.append("· 买法：猪猪游戏 天降猪猪 买 2只飞猪")
        return self._card({
            "title": "🐷 天降猪猪",
            "badge": "金币 %d" % coins,
            "subtitle": ("每种每天最多买 %d 头" % limit) if limit > 0 else "不限购",
            "rows": rows,
            "rows_cols": 1,
            "lines": lines,
        }, image=self.app.pig_image(offers[0][0]))

    # ==================== 猪圈 / 场景 ====================
    def _cmd_pen(self, scope, qq, p, args, qq_context):
        action = str(args.get("action") or "view").strip().lower()
        raw_scene = str(args.get("scene") or "").strip()
        cfg = self.cfg
        if raw_scene or action in ("scene", "设置", "设置场景", "set"):
            sid = scene_id(raw_scene, cfg.scenes)
            if not sid:
                return self._res(rules.missing(
                    ["缺少或无效的场景名，可选：%s" % scene_hint(cfg.scenes)],
                    "设置猪圈场景草地"))
            p["scene"] = sid
            return self._card({
                "title": "🐷 猪圈场景已更换", "badge": SCENE_LABELS.get(sid, sid),
                "subtitle": "当前场景：%s" % SCENE_LABELS.get(sid, sid),
                "stats": [{"k": "可选场景", "v": " / ".join(SCENE_LABELS.get(s, s)
                                                          for s in cfg.scenes)}],
            }, image=self.app.scene_image(sid))

        army = p.get("army") or {}
        if any(int(v or 0) > 0 for v in army.values()):
            army_text = parse.squad_text(self.book, army)
        else:
            army_text = "未设置（免战）"
        if p.get("checkin_blocked_date") == today():
            day_text = "今天被假扮了，无法打卡"
        elif p.get("last_checkin_date") == today():
            day_text = "今天已打卡"
        else:
            day_text = "今天还没打卡"

        # 一只猪一张卡：先三个总览 + 猪总数，再逐个猪种，最后军队单独一行
        pigs = p.get("pigs") or {}
        total = sum(int(v or 0) for v in pigs.values())
        kinds = sum(1 for sp in self.book.all()
                    if int(pigs.get(str(sp["id"]), 0) or 0) > 0)
        stats = [
            {"k": "猪猪金币", "v": "%d" % int(p.get("coins") or 0)},
            {"k": "好感度", "v": "%d" % int(p.get("affinity") or 0)},
            {"k": "体力", "v": "%d" % int(p.get("stamina") or 0)},
            {"k": "猪总数", "v": "%d 只" % total},
            {"br": True},
        ]
        for i in sorted(range(len(self.book.all())),
                        key=lambda k: (-int(pigs.get(str(self.book.all()[k]["id"]), 0) or 0), k)):
            sp = self.book.all()[i]
            stats.append({"k": sp["name"],
                          "v": "%d 只" % int(pigs.get(str(sp["id"]), 0) or 0)})
        stats.append({"br": True})
        stats.append({"k": "军队", "v": army_text})

        return self._card({
            "title": "🐷 %s 的猪圈" % str(p["nickname"]),
            "badge": day_text,
            "subtitle": ("已养 %d 种猪" % kinds) if total else "猪圈还空着，先去打卡攒猪吧",
            "stats": stats,
            "lines": ["· 场景：%s" % SCENE_LABELS.get(str(p.get("scene") or ""),
                                                     str(p.get("scene") or ""))],
        }, image=self.app.scene_image(str(p.get("scene") or "")))

    # ==================== 交易 ====================
    def _cmd_trade(self, scope, qq, p, args, qq_context):
        action = str(args.get("action") or "").strip().lower()
        if action in ("accept", "接受"):
            return self._trade_accept(scope, qq, p)
        if action in ("reject", "拒绝"):
            return self._trade_reject(scope, qq, p)
        return self._trade_offer(scope, qq, p, args, qq_context)

    def _trade_offer(self, scope, qq, p, args, qq_context):
        cfg = self.cfg
        name = parse.clean_name(args.get("target"))
        sid = self.book.resolve(args.get("species"))
        if not name or not sid:
            return self._res(rules.missing(
                ["缺少：目标玩家" if not name else "", "缺少：猪种" if not sid else ""],
                "出价5金币买其乐容容1只超级肥猪"))
        tqq = self.resolve_target(scope, name, qq_context)
        if tqq == qq:
            return self._res(rules.invalid("不能买自己的猪"))
        if not tqq:
            return self._res(rules.missing(["目标玩家「%s」没找到（要写对方昵称）" % name],
                                           "出价5金币买其乐容容1只超级肥猪"))
        sp = self.book.get(sid)
        if not sp or not sp.get("tradable"):
            return self._res(rules.invalid("%s 不能交易" % (sp["name"] if sp else "这种猪")))
        seller = self.store.get_player(scope, tqq)
        if seller is None:
            return self._res(rules.invalid("对方还没有开始养猪"))
        self.tick(seller)

        cnt = parse.extract_int(args.get("count"))
        price = parse.extract_int(args.get("price"))
        if cnt is None or price is None:
            return self._res(rules.missing(
                ["缺少：数量" if cnt is None else "", "缺少：单价" if price is None else ""],
                "出价5金币买其乐容容1只超级肥猪"))
        maxc = td.max_count(cfg, self.book, sid, int(seller["pigs"].get(sid, 0) or 0))
        if cnt <= 0 or cnt > maxc:
            return self._res(rules.invalid("数量超出上限：%s 单笔最多 %d 只，对方有 %d 只"
                                           % (sp["name"], maxc, int(seller["pigs"].get(sid, 0) or 0))))
        cap, est = td.price_cap(cfg, self.book, sid, int(seller.get("affinity") or 0))
        if price <= 0:
            return self._res(rules.invalid("单价要大于 0"))
        if price > cap:
            return self._res(rules.invalid("出价超过上限：当前估价约 %.1f，单价最高 %.1f" % (est, cap)))

        fp = td.fail_prob(cfg, int(seller.get("affinity") or 0))
        if random.random() < fp:
            return self._res(rules.invalid("对方好感度太高，猪不肯离开主人，交易失败"))

        threshold = td.skip_threshold(cfg, self.book, sid, int(seller.get("affinity") or 0))
        if price >= threshold:
            return self._trade_execute(scope, p, seller, sid, cnt, price, skip=True)

        if int(p.get("coins") or 0) < price * cnt:
            return self._res(rules.invalid("你的金币不够，需要 %d 金币" % (price * cnt)))
        self.store.trades.append({
            "id": "%s-%d" % (qq, int(time.time() * 1000)), "scope": str(scope),
            "buyer": str(qq), "seller": str(tqq), "species": str(sid),
            "count": int(cnt), "price": int(price), "date": today(),
        })
        self.store.add_note(scope, tqq,
                            "%s 想出价 %d 金币/只 买你 %d 只%s（估价约 %.1f），回复「接受交易」或「拒绝交易」"
                            % (str(p["nickname"]), price, cnt, sp["name"], est))
        return self._card({
            "title": "🐷 已询价", "badge": "%d 金币/只" % price,
            "subtitle": "目标：%s 的 %d 只%s" % (str(seller["nickname"]), cnt, sp["name"]),
            "stats": [{"k": "单价", "v": "%d" % price},
                      {"k": "估价约", "v": "%.1f" % est},
                      {"k": "共", "v": "%d 金币" % (price * cnt)},
                      {"k": "状态", "v": "等对方回应"}],
        }, image=self.app.pig_image(str(sid)))

    def _trade_find(self, scope, field, qq):
        for t in self.store.trades:
            if str(t.get("scope")) == str(scope) and str(t.get(field)) == str(qq):
                return t
        return None

    def _trade_accept(self, scope, qq, p):
        t = self._trade_find(scope, "seller", qq)
        if not t:
            return self._res(rules.invalid("你当前没有待处理的交易请求"))
        buyer = self.store.get_player(scope, t["buyer"])
        if buyer is None:
            self._drop_trade(t)
            return self._res(rules.invalid("买家已经不在了，交易取消"))
        return self._trade_execute(scope, buyer, p, t["species"], int(t["count"]),
                                   int(t["price"]), skip=False, by_seller=True, trade=t)

    def _trade_reject(self, scope, qq, p):
        t = self._trade_find(scope, "seller", qq)
        if not t:
            return self._res(rules.invalid("你当前没有待处理的交易请求"))
        self._drop_trade(t)
        self.store.add_note(scope, t["buyer"],
                            "%s 拒绝了你的交易（%d 只%s，单价 %d）"
                            % (str(p["nickname"]), int(t["count"]),
                               self.book.name(t["species"]), int(t["price"])))
        return self._card({
            "title": "🐷 交易已拒绝", "badge": "无损失",
            "subtitle": "%s 的询价被回绝了" % str(p["nickname"]),
            "stats": [{"k": "花费", "v": "0"}],
        }, image=self.app.pig_image(str(t["species"])))

    def _drop_trade(self, t):
        try:
            self.store.trades.remove(t)
        except Exception:
            pass

    def _trade_execute(self, scope, buyer, seller, sid, cnt, price, skip=False,
                       by_seller=False, trade=None):
        sp = self.book.get(sid)
        have = int(seller["pigs"].get(sid, 0) or 0)
        total = int(price) * int(cnt)
        if have < int(cnt):
            if trade:
                self._drop_trade(trade)
            return self._res(rules.invalid("对方的%s已经不够了，交易失败" % (sp["name"] if sp else "猪")))
        if int(buyer.get("coins") or 0) < total:
            if trade:
                self._drop_trade(trade)
            return self._res(rules.invalid("买家金币不足，交易失败"))
        buyer["coins"] = int(buyer["coins"]) - total
        seller["coins"] = int(seller.get("coins") or 0) + total
        seller["pigs"][sid] = have - int(cnt)
        buyer["pigs"][sid] = int(buyer["pigs"].get(sid, 0) or 0) + int(cnt)
        if trade:
            self._drop_trade(trade)
        b_name = str(buyer["nickname"])
        s_name = str(seller["nickname"])
        if skip:
            self.store.add_note(scope, seller["qq"],
                                "%s 用超高价（单价 %d）直接买走了你 %d 只%s"
                                % (b_name, int(price), int(cnt), sp["name"]))
            head = "【🐷 猪猪交易 · 成功（超高价直接成交）】"
        elif by_seller:
            self.store.add_note(scope, buyer["qq"],
                                "交易成功：你以单价 %d 买入 %s 的 %d 只%s，共 %d 金币"
                                % (int(price), s_name, int(cnt), sp["name"], total))
            head = "【🐷 猪猪交易 · 成功】"
        else:
            head = "【🐷 猪猪交易 · 成功】"
        comment = self.app.llm.comment("trade", "买入 %d 只%s，单价 %d，共 %d 金币"
                                       % (int(cnt), sp["name"], int(price), total))
        return self._card({
            "title": "🐷 猪猪交易 · 成功",
            "badge": "%s 金币" % ("超高价直接成交" if skip else "-%d" % total),
            "subtitle": "%s → %s，%d 只%s，单价 %d" % (b_name, s_name, int(cnt), sp["name"], int(price)),
            "stats": [{"k": "共", "v": "%d 金币" % total},
                      {"k": "买家金币", "v": "%d" % int(buyer["coins"])},
                      {"k": "卖家金币", "v": "%d" % int(seller["coins"])}],
            "comment": comment,
        }, image=self.app.pig_image(str(sid)))

    # ==================== 排行榜 ====================
    def _cmd_rank(self, scope, qq, p, args, qq_context):
        scope_arg = str(args.get("scope") or args.get("request") or "").strip()
        type_arg = str(args.get("type") or "").strip()
        global_rank = ("全服" in scope_arg) or ("global" in scope_arg.lower())
        coin = ("金币" in type_arg) or ("coin" in type_arg.lower())
        title_type = "猪猪金币榜" if coin else "猪猪数量榜"
        title_scope = "全服" if global_rank else "全村"

        rows = {}
        if global_rank:
            for _sc, q, pl in self.store.all_players():
                item = rows.setdefault(str(q), {"qq": str(q),
                                                "name": str(pl["nickname"]),
                                                "coins": 0, "count": 0})
                item["coins"] += int(pl.get("coins") or 0)
                item["count"] += parse.total_pigs(pl.get("pigs"))
                if pl.get("nickname"):
                    item["name"] = str(pl["nickname"])
        else:
            for q, pl in self.store.scope_players(scope).items():
                rows[str(q)] = {"qq": str(q), "name": str(pl["nickname"]),
                                "coins": int(pl.get("coins") or 0),
                                "count": parse.total_pigs(pl.get("pigs"))}
        key = "coins" if coin else "count"
        unit = "金币" if coin else "只"
        ordered = [x for x in sorted(rows.values(), key=lambda x: -x[key]) if x[key] > 0]
        rank_rows, my_rank = [], ""
        me = str(qq)
        for i, item in enumerate(ordered[:10], 1):
            rank_rows.append({"name": "%d. %s" % (i, item["name"]),
                              "v": "%d %s" % (item[key], unit)})
        for i, item in enumerate(ordered, 1):
            if item.get("qq") and str(item["qq"]) == me:
                my_rank = "第 %d 名" % i
                break
        return self._card({
            "title": "🏆 %s · %s" % (title_type, title_scope),
            "badge": my_rank or "未上榜",
            "subtitle": "最多显示前 10 名",
            "rows": rank_rows or [{"name": "还没有人上榜", "v": ""}],
            "tip": "试试：排行榜 全服 金币",
        })

    # ==================== 规则 ====================
    def _cmd_rules(self, scope, qq, p, args, qq_context):
        return self._card(rules.command_card())
