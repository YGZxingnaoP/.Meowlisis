# -*- coding: utf-8 -*-
"""自主循环：模型自己看状态、自己选工具和参数、自己承担结果。

和旧 planner 的区别只有一句话：**没有任何固定动作序列**。
这里只做六件事：

    1. 读 /state，把游戏画面文字化；
    2. 把「人设 / 笔记 / 长期方向 / 今日打算 / 待办 / 记忆 / 最近发生的事」拼成提示词；
    3. 把模组的全部 MCP 工具原样交给模型（function calling）；
    4. 执行模型选的工具，把结果写进日志，下一轮再把新状态给它；
    5. 睡前写日记 / 记忆 / 长期规划，按天归档；
    6. 记录（日志 / 记忆 / 日记 / 习惯 / 计划 / 待办），不参与决策。

失败不做规则补救：工具返回什么就原样告诉模型，让它自己换方法；
模型连续三步只说话不动作，直接报错停下。
"""

import json
import re
import threading
import time

from ..brain import needs, reflect
from ..core import ops
from ..core.mcp import Mcp
from ..records import (diary, farmmap, habits, journal, memtips, plans, profile,
                       store as store_mod, todos)
from ..voice import social, textgen

STORY_WORDS = ("任务", "委托", "社区中心", "献祭", "博物馆", "捐献", "节日", "比赛",
               "求婚", "花束", "秘密", "冒险家公会", "马龙", "齐先生", "钥匙", "雕像",
               "爷爷", "矿洞", "矿山", "纸条", "信", "剧情", "升级", "解锁")

# 单机不需要的工具：露在 schema 里只会让模型分心。
MULTIPLAYER_ONLY = {"say", "set_mode", "wait_chat", "follow", "propose"}

PLAY_RULES = """# 你怎么操作这个角色

你不是在写计划，也不是在回答我。你就像真人坐在这台电脑前玩游戏：
用眼睛看状态，用工具动手，做完一步再看下一步。

- 每一步只做一件明确的事，直接调用一个工具；参数自己按状态里的坐标、物品名、地点填。
- 上一次工具的结果会原样给你。失败就换方法或换目标，不要原样重试同一个动作。
- 状态里出现「当前界面」时，先处理界面：dialogue（对话/选项）、close_menu、
  choose_profession（选职业）、set_name（起名）、buy/sell（商店）。
- 体力低于 20%：先 eat 吃东西；没有吃的就回家或去捡/买食物。
- 背包满了：先 craft Chest（50 木材）→ place_item 放到农场 → store_items / tidy_backpack。
- 树种（橡子、松果、枫树种子）要用 place_item 种在农场的空地上；plant_seeds 只认作物种子。
- 摸宠物只用 interact 传 x,y，**不要传 npc 名字**（宠物不是村民，按名字找不到）。
- 农活一次做一大片（整块田），不要种两颗就跑去干别的。
- 出门前想清楚：下矿要镐和武器和回血食物，钓鱼要鱼竿，送礼先 gift_info。
- 商店时间：杂货店 9:00-17:00，铁匠 9:00-16:00，木匠 9:00-17:00，博物馆 8:00-18:00。
- 22:00 以后收工回家，24:00 前用 sleep 睡觉。sleep 会结束这一天；
  不睡就会被抬回家，还会掉钱。决定熬夜也必须自己承担。
- 每天至少和村民说话、摸一次宠物/动物、吃点东西、看点风景，别做工作机器。
- 想记住自己的计划，调用 update_notes 覆盖写进笔记（每一步都会看到）。
- 不确定地图/规则时用 get_guide 查攻略，不要凭空猜。
- 遇到真正值得让主人知道的事（升级、解锁、节日、剧情、第一次到新地方、下矿到新层、
  做成一件大事），可以调用 share_moment 自己分享一句；收菜、浇水、出货、闲逛、
  每天写日记/睡觉都不算。
- 不要问我问题，不要只输出文字不调用工具。"""


class Agent:
    def __init__(self, ctx, bridge, config, on_say=None, on_share=None):
        self.ctx = ctx
        self.bridge = bridge
        self.config = dict(config or {})
        self.on_say = on_say
        self.on_share = on_share
        self.stop_event = threading.Event()
        self.cancel_event = threading.Event()
        self.thread = None
        self.lock = threading.RLock()

        try:
            default_name = ctx.ai_name() or ""
        except Exception:
            default_name = ""
        self.persona = str(self._get("persona") or default_name or "农夫")
        self.autonomy = _bool(self._get("autonomy.enabled", self._flat("auto_play", True)), True)
        self.playing = False
        self.llm_enabled = _bool(self._get("autonomy.llm", self._flat("use_llm", True)), True)
        if not self.llm_enabled:
            raise RuntimeError("星露谷插件要求文本模型可用：autonomy.llm 不能关闭")
        self.feedback = _bool(self._get("feedback.enabled", True), True)
        self.share_images = _bool(self._get("feedback.share_images", True), True)
        self.share_minutes = max(10, _int(self._get("feedback.share_minutes", 60), 60))
        self.share_max_per_day = max(0, min(20, _int(
            self._get("feedback.share_max_per_day", 1), 1)))
        self.long_term_config = str(self._get("autonomy.long_term",
                                             "把农场经营好、多赚点钱、和镇上的人熟起来") or "")
        self.max_roots = max(1, min(5, _int(self._get("plans.max_roots", 3), 3)))
        self.max_leaves = max(3, min(12, _int(self._get("plans.max_leaves", 6), 6)))
        self.habits_enabled = _bool(self._get("habits.enabled", True), True)
        self.tips_enabled = _bool(self._get("tips.enabled", True), True)
        self.memory_recall = max(2, min(30, _int(self._get("memory.recall", 8), 8)))
        self.narrate_minutes = _int(self._get("autonomy.narrate_minutes", 2), 2)
        self.llm_timeout = max(30, min(300, _int(self._get("autonomy.llm_timeout", 150), 150)))
        self.max_idle_steps = max(1, min(5, _int(self._get("autonomy.max_idle_steps", 3), 3)))
        self.farm_vision_enabled = _bool(self._get("autonomy.farm_vision", True), True)

        traits = self._get("traits") or {}
        self.label = str(self._get("instance_label") or "").strip()
        self.traits_config = {
            "diligence": _float(traits.get("diligence", 0.6)),
            "sociability": _float(traits.get("sociability", 0.5)),
            "curiosity": _float(traits.get("curiosity", 0.5)),
            "thrift": _float(traits.get("thrift", 0.5)),
        }

        self.state = {}
        self.state_text = ""
        self.current = None
        self.last_action = None
        self.failures = []
        self.force_request = None
        self._day_state = {}
        self.last_error = ""
        self.last_say = 0.0
        self.last_share = 0.0
        self.notes = ""
        self.inbox = []
        self.paused = False
        self.sleeping = False
        self.jobs_today = 0
        self.steps_today = 0
        self._step_count = 0
        self._idle_steps = 0
        self._last_think = 0.0
        self._last_visit = ""
        self._dialog_since = 0
        self._last_dialogue_page = ""
        self.last_skills = None
        self._prompt_cache = ""
        self._last_prompt_state = 0
        self._schemas = None
        self._tool_names = set()
        self._schemas_at = 0.0
        self._rules_text = ""
        self._rules_at = 0.0

        self.pending_name = ""
        self.naming_ask = _bool(self._get("naming.ask_user", True), True)
        self.user_input_enabled = _bool(self._get("user_input.enabled", True), True)
        self.user_input_timeout = max(15, _int(self._get("user_input.timeout_seconds", 60), 60))
        self.pending_question = None

        self.world_key = ""
        self.store = None
        self.profile = None
        self.day_stamp = ""
        self.mcp = Mcp(self._get("mcp_url") or "http://127.0.0.1:18080/mcp")
        self._bind_world(self.state)

    # ---------- 配置 ----------
    def _get(self, path, default=None):
        node = self.config
        for part in str(path).split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def _flat(self, key, default=None):
        return self.config.get(key, default)

    @property
    def traits(self):
        return self.profile.traits if self.profile is not None else dict(self.traits_config)

    # ---------- 世界 / 存档 ----------
    def _bind_world(self, state):
        key = store_mod.world_key(state) or self.world_key
        if not key:
            return False
        if self.store is not None and key == self.world_key:
            return False
        self.world_key = key
        self.store = store_mod.Store(self.ctx, key, self.label)
        self.profile = profile.Profile(self.store)
        self.pending_name = str(self.profile.data.get("pending_name") or "")
        self.notes = str(self.profile.data.get("agent_notes") or "")
        self.pending_question = self.profile.data.get("pending_question") or None
        if not self.profile.data.get("_traits_seeded"):
            self.profile.set_traits(self.traits_config)
            self.profile.data["_traits_seeded"] = True
            self.profile.save()
        self.last_skills = None
        return True

    def _ensure_world(self, state):
        changed = self._bind_world(state)
        if changed:
            self.day_stamp = ""
            self.current = None
            self.inbox = []
        return changed

    # ---------- 生命周期 ----------
    def start(self):
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="stardew_agent", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        try:
            if self.store is not None and self.profile is not None:
                self.profile.save()
        except Exception:
            pass
        if self.thread is not None:
            self.thread.join(timeout=8)
        self.thread = None

    # ---------- 主循环 ----------
    def _loop(self):
        while not self.stop_event.is_set():
            try:
                state = self._read_state()
                if not state.get("ok"):
                    self.last_error = str(state.get("reason") or "连接不上游戏")
                    self.stop_event.wait(8)
                    continue
                self.state = state
                self.state_text = str(state.get("text") or "")
                self._ensure_world(state)
                if self.profile is not None:
                    self.profile.set_skills(needs.skills(state),
                                            needs.player(state).get("professions") or [],
                                            None)
                self._absorb_observation(state)
                self._track_visit(state)
                self._check_skills(state)
                self._check_day(state)
                if store_mod.stamp(state) == self.day_stamp:
                    self._day_state = state
                if not self.playing:
                    self.stop_event.wait(3)
                    continue
                if self.paused:
                    self.stop_event.wait(2)
                    continue
                self._step(state)
            except Exception as exc:
                self.ctx.log.exception("星露谷后台异常，停止游玩：%s" % exc)
                self.last_error = str(exc)
                self.playing = False
                break

    # ---------- 世界状态 ----------
    @staticmethod
    def _normalize_state(state):
        """把 mod 的 {meta:{game,player,...}} 摊平成 agent 内部用的结构。"""
        if not isinstance(state, dict):
            return {"ok": False, "reason": "bad state"}
        meta = state.get("meta") or {}
        if not isinstance(meta, dict) or not meta:
            return state
        merged = dict(state)
        for key in ("game", "player", "inventory", "farm", "menu", "npcs", "pets",
                    "forageables"):
            if key in meta and meta.get(key) is not None:
                merged[key] = meta[key]
        return merged

    def _read_state(self):
        return self._normalize_state(self.bridge.state())

    def _refresh_state(self, state):
        fresh = self._read_state()
        if fresh.get("ok"):
            self.state = fresh
            self.state_text = str(fresh.get("text") or "")
            return fresh
        return state

    def _absorb_observation(self, state):
        """从状态文字里抓 NPC 对话/事件线索，写进日志（只记录，不归纳）。"""
        text = self.state_text or ""
        if not text:
            return
        me = needs.player(state)
        place = str(me.get("location") or "")
        match = re.search(r"## 当前界面\n(.*?)(?:\n## |\Z)", text, re.S)
        if not match:
            return
        block = match.group(1).strip()
        if not block or block.startswith("无"):
            return
        if "对话" not in block and "Dialogue" not in block:
            return
        signature = "%s|%s" % (place, block[:80])
        if signature == self.profile.data.get("_last_menu_digest"):
            return
        self.profile.data["_last_menu_digest"] = signature
        self.profile.save()
        self._journal("dialogue", "[%s] %s" % (place, block[:300]), state=state)
        if any(word in block for word in STORY_WORDS):
            self._journal("event", "线索：" + block[:200], state=state)

    def _track_visit(self, state):
        me = needs.player(state)
        place = str(me.get("location") or "").strip()
        if not place or place == self._last_visit:
            return
        self._last_visit = place
        if self.profile is not None:
            first = self.profile.first_visit(place)
            self.profile.visit(place, store_mod.stamp(state))
            if first:
                self._journal("event", "第一次到 %s。" % place, state=state)

    def _check_skills(self, state):
        current = needs.skills(state)
        if not current:
            return
        if self.last_skills is None:
            self.last_skills = current
            return
        leveled = [(key, value) for key, value in current.items()
                   if value > int(self.last_skills.get(key, 0))]
        self.last_skills = current
        for key, value in leveled:
            label = needs.SKILL_CN.get(key, key)
            self._journal("event", "%s 升到 %s 级。" % (label, value), state=state)
            self.profile.bump("skill_levels")

    # ---------- 换天 ----------
    def _check_day(self, state):
        key = store_mod.stamp(state)
        if not key or self.store is None:
            return
        if key == self.day_stamp:
            return
        previous = self.day_stamp
        self.day_stamp = key
        self.steps_today = 0
        self.jobs_today = 0
        self.failures = []
        self.force_request = None
        previous_state = self._day_state or state
        if previous:
            try:
                if self.profile.data.get("last_diary_day") != previous:
                    self._close_day(previous_state, previous)
                plans.archive_day(self.store, previous)
            except Exception as exc:
                self.ctx.log.warning("星露谷收尾昨天失败：%s" % exc)
        self._start_day(state, previous)
        self._capture_farm_map(state)
        self._maybe_summarize_habits(state)
        gm = (state or {}).get("game") or {}
        self._journal("event", "新的一天：第 %s 年 %s %s 日，%s，%s。" % (
            gm.get("year"), needs.SEASON_CN.get(gm.get("season"), gm.get("season")),
            gm.get("day"), "雨天" if gm.get("raining") else "晴天",
            needs.clock_text(state)), state=state)

    def _close_day(self, state, day):
        """一天结束（睡觉或被抬回家）：写日记 → 记忆 → 长线。"""
        if self.store is None or self.profile is None or not day:
            return
        if self.profile.data.get("last_diary_day") == day:
            return
        data = self._write_diary(state, day)
        if not data:
            return
        self.profile.mark_diary(day)
        kept = []
        try:
            kept = self._memory_flow(state, day, data) or []
        except Exception as exc:
            self.ctx.log.warning("星露谷写记忆失败：%s" % exc)
        try:
            self._long_term_flow(state, day, data)
        except Exception as exc:
            self.ctx.log.warning("星露谷更新长线失败：%s" % exc)
        try:
            self._digest_flow(state, day, data, kept)
        except Exception as exc:
            self.ctx.log.warning("星露谷写记忆摘要失败：%s" % exc)
        self.profile.save()

    def _start_day(self, state, previous_day=""):
        if self.profile is None:
            return
        self.profile.mark_day(self.day_stamp)
        self.profile.set_traits(self.traits_config)
        self.inbox = [item for item in self.inbox
                      if str(item.get("day") or "") in ("", self.day_stamp)]
        for item in self.inbox:
            item["day"] = self.day_stamp
        if previous_day:
            moved = todos.carry_over(self.store, previous_day, self.day_stamp)
            if moved:
                self._journal("plan", "把昨天没做完的 %d 条待办带到今天。" % len(moved),
                              state=state)
        long_term = plans.load_long_term(self.store, self.long_term_config, self.max_roots)
        day_plan = plans.load_day(self.store, self.day_stamp)
        if self.playing and (day_plan is None or not day_plan.get("nodes")):
            try:
                day_plan = self._generate_day_plan(state, long_term, previous_day)
            except Exception as exc:
                self.ctx.log.warning("星露谷排今日打算失败（不阻塞游玩）：%s" % exc)
                self._journal("system", "今天没排成打算，直接看状态决定。", state=state)
        if day_plan is not None and self.profile.data.get("last_plan_day") != self.day_stamp:
            self.profile.mark_plan(self.day_stamp)
            self._journal("plan", plans.day_summary(day_plan), state=state)

    def _capture_farm_map(self, state):
        if self.store is None or self.profile is None or not self.day_stamp:
            return
        if not self.farm_vision_enabled:
            return
        if self.profile.data.get("last_farm_map") == self.day_stamp:
            return
        try:
            data = self.bridge.farmmap()
        except Exception as exc:
            self.ctx.log.info("星露谷取农场图失败：%s" % exc)
            return
        if not data.get("ok"):
            return
        old = farmmap.previous(self.store, self.day_stamp)
        delta = farmmap.diff(old, data)
        farmmap.save(self.store, self.day_stamp, data)
        text = farmmap.text(data, delta)
        self.profile.data["last_farm_map"] = self.day_stamp
        self.profile.data["farm_map_text"] = text[:1200]
        self.profile.save()
        try:
            self.store.save_json(farmmap.diff_path(self.store, self.day_stamp), delta)
        except Exception:
            pass
        self._journal("event", "农场图：" + text.replace("\n", "；")[:300], state=state)

    def _maybe_summarize_habits(self, state):
        if not self.habits_enabled or self.store is None or self.profile is None:
            return
        key = store_mod.stamp(state)
        if not key:
            return
        current_index = habits.window_index(key)
        last_key = str(self.profile.data.get("last_habit_window") or "")
        if not last_key:
            self.profile.mark_habits(habits.window_key(key))
            return
        try:
            last_index = int(str(last_key).lstrip("w"))
        except (TypeError, ValueError):
            last_index = current_index
        if current_index <= last_index:
            return
        for index in range(last_index, current_index):
            start_stamp, end_stamp = habits.window_stamps(index)
            if not start_stamp:
                continue
            evidence_start, _ = habits.evidence_stamps(index)
            data = reflect.write_habits(self.ctx, self.store, evidence_start, end_stamp,
                                        self.persona, self.traits)
            habits.save_summary(self.store, start_stamp, data,
                                evidence={"start": evidence_start, "end": end_stamp})
            self._journal("system", "总结了 %s ~ %s 的生活习惯。" % (start_stamp, end_stamp),
                          state=state)
        self.profile.mark_habits(habits.window_key(key))

    # ---------- 今日打算（文字指导，不是动作白名单） ----------
    def _tips_text(self, query=""):
        if not self.tips_enabled or self.store is None:
            return ""
        tips = memtips.recall(self.store, limit=self.memory_recall, query=query,
                              current_stamp=self.day_stamp)
        return memtips.render(tips, max_items=self.memory_recall)

    def _long_term_text(self):
        if self.store is None:
            return ""
        return plans.long_term_text(plans.load_long_term(
            self.store, self.long_term_config, self.max_roots))

    def _recent_journal(self, limit=14):
        if self.store is None or not self.day_stamp:
            return []
        return journal.read_day(self.store, self.day_stamp)[-max(1, int(limit)):]

    def _relevant_journal(self, long_term, todos_today, limit=40):
        if self.store is None:
            return []
        query = self._diary_search_query(long_term, todos_today)
        tokens = [token for token in re.split(r"[\s，。、,;；]+", query) if len(token) >= 2]
        if not tokens:
            return []
        picked = []
        for _day, day_rows in journal.recent_days(self.store, limit_days=10):
            for row in day_rows:
                content = str((row or {}).get("content") or "")
                if any(token in content for token in tokens):
                    picked.append(row)
                    if len(picked) >= limit:
                        return picked
        return picked

    def _diary_search_query(self, long_term, todos_today):
        parts = []
        try:
            for item in plans.next_long_term_focus(long_term, limit=4):
                parts.append(str(item.get("root") or ""))
                parts.append(str(item.get("leaf") or ""))
        except Exception:
            pass
        if self.tips_enabled:
            try:
                tips = memtips.recall(self.store, limit=min(6, self.memory_recall),
                                      current_stamp=self.day_stamp)
            except Exception:
                tips = []
            for tip in tips:
                parts.append(str((tip or {}).get("content") or ""))
        for item in (todos_today or [])[:6]:
            parts.append(str((item or {}).get("content") or ""))
        return " ".join(part for part in parts if part.strip())

    def _related_diaries(self, long_term, todos_today):
        if self.store is None:
            return []
        query = self._diary_search_query(long_term, todos_today)
        if not query:
            return []
        try:
            return diary.search(self.store, query=query, limit=3, before=self.day_stamp)
        except Exception as exc:
            self.ctx.log.warning("星露谷检索旧日记失败：%s" % exc)
            return []

    def _generate_day_plan(self, state, long_term, previous_day=""):
        if self.store is None:
            return None
        todos_today = todos.open_items(self.store, self.day_stamp)
        if not todos_today and previous_day:
            todos_today = todos.open_items(self.store, previous_day)
        last_diary = diary.latest(self.store, before=self.day_stamp)[1]
        habits_hint = habits.today_hint(self.store, state) if self.habits_enabled else ""
        search_query = self._diary_search_query(long_term, todos_today)
        farm_text = str((self.profile.data.get("farm_map_text") if self.profile else "") or "")
        nodes, reason = reflect.make_day_plan(
            self.ctx, state, self.store, long_term,
            self._tips_text(query=search_query), habits_hint, todos_today,
            (last_diary or {}).get("content") or "", self._relevant_journal(long_term, todos_today),
            self.persona, self.traits, self.max_leaves,
            self._tips_text(query=search_query),
            related_diaries=self._related_diaries(long_term, todos_today),
            observation=self.state_text + ("\n\n" + farm_text if farm_text else ""))
        return plans.save_day(self.store, self.day_stamp, nodes, state=state, reason=reason)

    # ---------- 一天一步 ----------
    def _step(self, state):
        if self.force_request:
            left = int(self.force_request.get("left") or 0) - 1
            if left <= 0:
                self.force_request = None
            else:
                self.force_request["left"] = left
        content, calls = self._ask_model(state)
        if content:
            self._journal("thought", content[:400], state=state)
        calls = [call for call in (calls or []) if str(call.get("name") or "").strip()]
        if not calls:
            self._idle_steps += 1
            self._journal("system", "（模型这一步没有调用任何工具）", state=state)
            if self._idle_steps >= self.max_idle_steps:
                raise RuntimeError("模型连续 %d 步只说话不动手，停下等人工检查"
                                   % self._idle_steps)
            self.stop_event.wait(1.0)
            return
        self._idle_steps = 0
        call = calls[0]
        self._execute(state, call)
        if len(calls) > 1:
            self._journal("system", "模型一次给了 %d 个动作，只执行第一个；看完新状态再继续。"
                          % len(calls), state=state)

    def _ask_model(self, state):
        messages = [
            {"role": "system", "content": self._system_prompt(state)},
            {"role": "user", "content": self._user_prompt(state)},
        ]
        choice = "required" if self._idle_steps > 0 else "auto"
        tries = 2
        last_error = None
        for attempt in range(tries):
            box = {}

            def work():
                try:
                    box["value"] = textgen.call_tools(self.ctx, messages,
                                                      self._tools(), tool_choice=choice)
                except Exception as exc:  # noqa: BLE001
                    box["error"] = exc

            thread = threading.Thread(target=work, name="stardew_decision", daemon=True)
            thread.start()
            thread.join(self.llm_timeout if attempt == 0 else self.llm_timeout * 2)
            if thread.is_alive():
                last_error = TimeoutError("模型思考超过 %ss" % self.llm_timeout)
                self._journal("system", "模型思考超时，重试一次。", state=state)
                continue
            if "error" in box:
                last_error = box["error"]
                break
            value = box.get("value") or ("", [])
            return value
        raise RuntimeError("星露谷决策模型失败：%s" % last_error)

    def _execute(self, state, call):
        name = str(call.get("name") or "").strip()
        args = self._parse_args(call.get("arguments"))
        label = name
        compact = self._compact_args(args)
        self.current = {
            "goal": name,
            "label": label,
            "title": label,
            "step": 1,
            "total": 1,
            "op": name,
            "args": args,
            "progress": compact,
            "started": int(time.time()),
        }
        day_before = self.day_stamp
        if self.profile is not None:
            self.profile.set_activity("正在 %s %s" % (name, compact))
        self._journal("action", "调用 %s %s" % (name, compact), goal=name, state=state)
        started = time.time()
        try:
            result = self._call_tool(name, args)
        except Exception as exc:  # noqa: BLE001
            self.current = None
            raise RuntimeError("执行 %s 失败：%s" % (name, exc))
        elapsed = round(time.time() - started, 1)
        ok = bool(result.get("ok"))
        detail = str(result.get("result") or result.get("reason") or "")
        self.steps_today += 1
        self._step_count += 1
        self.last_action = {
            "name": name, "args": args, "ok": ok,
            "result": detail[:800], "elapsed": elapsed, "at": store_mod.now(),
        }
        self.current = None
        self._journal("action", "%s %s（%.1fs）：%s" % (
            "完成" if ok else "失败", name, elapsed, detail[:500]), goal=name, state=state)
        if ok:
            self.failures = [item for item in self.failures if item.get("name") != name]
            self._after_success(name, args, detail, state)
        else:
            self.failures.append({"name": name, "args": compact, "result": detail[:240]})
            self.failures = self.failures[-5:]
        if name == "sleep":
            if ok:
                self._after_sleep(day_before, self._day_state or state)
            else:
                self._journal("action", "没睡成：%s" % detail[:300], state=state)
        if not ok:
            self.ctx.log.info("星露谷：%s 失败：%s" % (name, detail[:200]))

    @staticmethod
    def _parse_args(raw):
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _compact_args(args, limit=160):
        if not args:
            return ""
        try:
            text = json.dumps(args, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(args)
        return text[:limit]

    def _call_tool(self, name, args):
        if name == "update_notes":
            notes = str(args.get("notes") or "").strip()
            self.notes = notes[:1000]
            if self.profile is not None:
                self.profile.data["agent_notes"] = self.notes
                self.profile.save()
            self._journal("plan", "写下自己的笔记：" + self.notes.replace("\n", "；")[:300])
            return {"ok": True, "result": "笔记已更新"}
        if name == "screenshot":
            shot = self.bridge.screenshot()
            path = str(shot.get("path") or "")
            if shot.get("ok") and path:
                return {"ok": True, "result": "截图：" + path}
            return {"ok": False, "result": str(shot.get("reason") or "没截到画面")}
        if name == "get_state":
            fresh = self._refresh_state(self.state)
            return {"ok": True, "result": str(fresh.get("text") or "")[:6000]}
        if name == "share_moment":
            text = str(args.get("text") or "").strip()
            if not text:
                return {"ok": False, "result": "要分享的话是空的"}
            image = bool(args.get("image"))
            sent = self._share(text, image=image, level="model")
            return {"ok": True,
                    "result": "已经让主人知道了" if sent else "现在先不打扰主人（刚发过或今天够了）"}
        if name == "get_guide":
            text = self.mcp.call("get_guide", args, timeout=30)
            return {"ok": True, "result": str(text)[:4000]}
        self._ensure_tools()
        if name not in self._tool_names:
            return {"ok": False, "result": "失败：没有叫 %s 的工具" % name}
        result = self.bridge.call_with(name, args, timeout=ops.timeout(name))
        if not isinstance(result, dict):
            return {"ok": False, "result": "工具返回了奇怪的东西"}
        return result

    def _after_success(self, name, args, detail, state):
        if name == "sleep":
            return
        self.jobs_today += 1
        if name == "open_shop":
            self._journal("event", "商店开门了：" + detail[:120], state=state)
        elif name == "buy":
            self._journal("event", "买了东西：" + detail[:120], state=state)
        elif name == "ship_items":
            self._journal("event", "把东西送进出货箱：" + detail[:120], state=state)

    def _after_sleep(self, day_before, ended_state):
        self.sleeping = True
        try:
            self._journal("sleep", "睡着了。", state=ended_state or self.state)
            self._close_day(ended_state or self.state, day_before)
            if self.store is not None:
                plans.archive_day(self.store, day_before)
        finally:
            self.sleeping = False

    # ---------- 工具与提示词 ----------
    def _ensure_tools(self):
        if self._schemas is not None and time.time() - self._schemas_at < 600:
            return
        tools = self.mcp.tools(refresh=True)
        schemas = []
        names = set()
        for item in tools or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in MULTIPLAYER_ONLY or name == "get_state":
                continue
            schema = item.get("inputSchema")
            if not isinstance(schema, dict) or not schema:
                schema = {"type": "object", "properties": {}}
            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(item.get("description") or name)[:1500],
                    "parameters": schema,
                },
            })
            names.add(name)
        if not schemas:
            raise RuntimeError("游戏模组没有提供任何可用工具（MCP tools/list 为空）")
        schemas.append({
            "type": "function",
            "function": {
                "name": "share_moment",
                "description": (
                    "当你觉得刚才发生的事值得让主人知道时，主动分享一句。"
                    "值得：升级、解锁、节日、剧情、第一次到新地方、下矿到新层、"
                    "做成一件真正的大事。不值得：收菜、浇水、出货、闲逛、每天写日记/睡觉。"
                    "宁可少发，不要刷屏。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "你想对主人说的那句话"},
                        "image": {"type": "boolean", "description": "是否附一张当前游戏截图"},
                    },
                    "required": ["text"],
                },
            },
        })
        names.add("share_moment")
        self._schemas = schemas
        self._tool_names = names
        self._schemas_at = time.time()

    def _tools(self):
        self._ensure_tools()
        return self._schemas

    def _rules(self):
        if self._rules_text and time.time() - self._rules_at < 900:
            return self._rules_text
        init = self.mcp.initialize()
        rules = str(init.get("instructions") or "")
        guide_start = rules.find("## 游戏常识")
        mcp_notes = rules.find("## 通过 MCP 玩的额外说明")
        if guide_start >= 0 and mcp_notes > guide_start:
            rules = rules[:guide_start] + rules[mcp_notes:]
        self._rules_text = rules.strip()[:7000]
        self._rules_at = time.time()
        return self._rules_text

    def _persona_line(self):
        traits = self.traits or {}
        return ("你是%s，星露谷的农夫。性格：勤劳 %.1f、爱交际 %.1f、好奇 %.1f、在乎钱 %.1f（0~1）。"
                % (self.persona, float(traits.get("diligence", 0.6)),
                   float(traits.get("sociability", 0.5)),
                   float(traits.get("curiosity", 0.5)),
                   float(traits.get("thrift", 0.5))))

    def _inbox_text(self):
        if not self.inbox:
            return ""
        lines = ["# 别人刚对你说的话（你可以在合适的时候去做，不必立刻放下手里的活）"]
        for item in self.inbox[-5:]:
            who = item.get("by") or "有人"
            lines.append("- %s：%s" % (who, item.get("text")))
        return "\n".join(lines)

    def _system_prompt(self, state):
        tips = self._tips_text()
        sections = [
            self._persona_line(),
            PLAY_RULES,
        ]
        if self.force_request:
            sections.append(
                "# 主人现在就要你做（最高优先，先放下手头的计划）\n" +
                str(self.force_request.get("text") or "") +
                "\n先处理这件事，做完再回去做原来的事。")
        sections.extend([
            "# 你自己的笔记（上一步写下的，随时可以 update_notes 改）\n" +
            (self.notes or "（还没写）"),
            "# 长线方向（只是方向，不是任务清单）\n" + (self._long_term_text() or "（还没定）"),
            "# 今天的打算（自己排的，允许随时改）\n" +
            (plans.day_text(plans.load_day(self.store, self.day_stamp)) if self.store else "（还没定）"),
        ])
        if self.store is not None:
            todo_text = todos.summary(self.store, self.day_stamp, 10)
            if todo_text and todo_text != "今天没有待办。":
                sections.append("# 今天记下的待办\n" + todo_text)
        inbox = self._inbox_text()
        if inbox:
            sections.append(inbox)
        if tips:
            sections.append("# 你记得的事\n" + tips)
        if self.habits_enabled and self.store is not None:
            hint = habits.today_hint(self.store, state)
            if hint:
                sections.append("# 你的习惯\n" + hint)
        recent = journal.render(self._recent_journal(18), max_rows=18, max_chars=2600)
        if recent:
            sections.append("# 最近发生的事（从旧到新）\n" + recent)
        farm_text = str((self.profile.data.get("farm_map_text") if self.profile else "") or "")
        if farm_text:
            sections.append("# 农场宏观图\n" + farm_text)
        rules = self._rules()
        if rules:
            sections.append("# 游戏里的规矩和常识\n" + rules)
        return "\n\n".join(section for section in sections if str(section).strip())

    def _user_prompt(self, state):
        text = self.state_text or needs.state_brief(state)
        text = text[:12000]
        last = self.last_action
        last_text = "（还没有动作）"
        if last:
            last_text = "%s %s → %s" % (
                "成功" if last.get("ok") else "失败", last.get("name"),
                str(last.get("result") or "")[:700])
        now = needs.clock_text(state)
        fail_text = ""
        if self.failures:
            fail_text = "\n\n# 最近失败的动作（不要原样重试，换方法或换目标）\n" + "\n".join(
                "- %s %s → %s" % (item.get("name"), item.get("args"),
                                  str(item.get("result") or "")[:160])
                for item in self.failures[-4:])
        force_text = ""
        if self.force_request:
            force_text = ("# 主人现在就要你做（最高优先）\n%s\n先处理这个，别继续原来的计划。\n\n"
                          % str(self.force_request.get("text") or ""))
        return (
            "%s# 你现在看到的游戏画面\n%s\n\n"
            "# 上一步的结果\n%s\n%s\n"
            "# 现在\n当前时间 %s。直接调用一个工具做下一件事；"
            "如果该结束这一天了就用 sleep。不要只是说话。"
        ) % (force_text, text, last_text, fail_text, now)

    def _narrate_once(self, text):
        if time.time() - self.last_say > 90:
            self._narrate(text)

    # ---------- 记录 ----------
    def _journal(self, kind, content, goal="", state=None):
        if self.store is None:
            return
        day = self.day_stamp or store_mod.stamp(state or self.state)
        if not day:
            return
        try:
            journal.append(self.store, day, kind, content, goal=goal,
                           state=state or self.state)
        except Exception as exc:
            self.ctx.log.warning("星露谷日志写入失败：%s" % exc)

    def _write_diary(self, state, day):
        rows = journal.read_day(self.store, day)
        if not rows:
            return None
        last = diary.latest(self.store, before=day)[1]
        data = reflect.write_diary(
            self.ctx, state, self.store, day, rows, self.persona, self.traits,
            (self.profile.mood_text() if self.profile else ""),
            (last or {}).get("content") or "", self._tips_text())
        if data is not None:
            self._journal("system", "写完了今天的日记。", state=state)
        return data

    def _memory_flow(self, state, day, diary_data):
        if not self.tips_enabled:
            return
        rows = journal.read_day(self.store, day)
        existing = memtips.render(memtips.recall(self.store, limit=12, current_stamp=day))
        tips = reflect.write_memories(self.ctx, state, self.store, day, rows,
                                      diary_data, self.persona, self.traits,
                                      self.profile, existing)
        kept = memtips.replace_day(self.store, day, tips)
        self.profile.mark_memory(day)
        if kept:
            self._journal("system", "把 %d 条长期记忆写进了记忆册。" % len(kept), state=state)
        return kept

    def _digest_flow(self, state, day, diary_data, tips):
        """独立记忆摘要：一天一个 memory/digest/<日期>.json，只汇总插件自己的东西。"""
        if self.store is None:
            return None
        rows = journal.read_day(self.store, day)
        shares = []
        thoughts = []
        for row in rows:
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            if row.get("kind") in ("share", "say"):
                shares.append(content[:300])
            elif row.get("kind") == "thought":
                thoughts.append(content[:300])
        summary = str((diary_data or {}).get("summary") or "").strip()
        if not summary:
            summary = str((diary_data or {}).get("content") or "")[:60]
        gm = (state or {}).get("game") or {}
        data = {
            "version": 1,
            "date": day,
            "year": gm.get("year"),
            "season": gm.get("season"),
            "day": gm.get("day"),
            "weather": str((diary_data or {}).get("weather") or ""),
            "mood": str((diary_data or {}).get("mood") or ""),
            "summary": summary,
            "shares": shares[-20:],
            "thoughts": thoughts[-20:],
            "tips": [{
                "content": str((tip or {}).get("content") or ""),
                "summary": str((tip or {}).get("summary") or (tip or {}).get("content") or "")[:80],
                "tag": list((tip or {}).get("tag") or []),
            } for tip in (tips or [])][:8],
            "diary": {
                "summary": str((diary_data or {}).get("summary") or ""),
                "content": str((diary_data or {}).get("content") or "")[:200],
            },
            "created": store_mod.now(),
        }
        self.store.save_json(self.store.memory_digest_path(day), data)
        self._journal("system", "记忆摘要写好了（%d 条分享、%d 条心声、%d 条 tip）。" % (
            len(data["shares"]), len(data["thoughts"]), len(data["tips"])), state=state)
        return data

    def _long_term_flow(self, state, day, diary_data):
        current = plans.load_long_term(self.store, self.long_term_config, self.max_roots)
        rows = journal.read_day(self.store, day)
        updated = reflect.update_long_term(
            self.ctx, state, self.store, current, day, diary_data, rows,
            self.persona, self.traits, self.max_roots, self._tips_text())
        self._journal("system", "更新了长线规划树。", state=state)
        return updated

    # ---------- 待办 / 请求 ----------
    @staticmethod
    def _follow_up_target(text, context):
        """“立刻去做 / 就这个 / 刚才那个”指回上一句请求；返回上一句原文。"""
        text = str(text or "").strip()
        if not text or len(text) > 16:
            return ""
        words = ("立刻", "现在", "马上", "赶紧", "快点", "去做", "去办",
                 "就这个", "刚才", "那个", "这就去")
        if not any(word in text for word in words):
            return ""
        for item in reversed(list(context or [])):
            if not isinstance(item, dict) or item.get("role") != "user":
                continue
            content = str(item.get("content") or "").strip()
            if content and content != text:
                return content[:160]
        return ""

    def _promote_todo(self, target, decision):
        """把上一句对应的待办从 pending 改成 doing，不再新建一条“立刻去做”。"""
        if self.store is None:
            return None
        data = todos.load_day(self.store, self.day_stamp)
        found = None
        for item in reversed(data.get("items") or []):
            if str(item.get("content") or "").strip() != target:
                continue
            if item.get("status") not in ("open", "doing", "deferred"):
                continue
            found = item
            break
        if found is None:
            return None
        found["status"] = "doing"
        found["priority"] = max(int(found.get("priority") or 0),
                                int(decision.get("priority") or 0), 9)
        found["updated"] = store_mod.now()
        found["note"] = "被催了，立刻做"
        todos.save_day(self.store, self.day_stamp, data)
        return found

    def handle_request(self, text, by="", source="qq", context=None):
        text = str(text or "").strip()
        state = self._read_state()
        if not state.get("ok"):
            return {"mode": "todo", "reason": "", "reply": "游戏还没开，我先记着。"}
        self.state = state
        self.state_text = str(state.get("text") or "")
        self._ensure_world(state)
        if self.store is None:
            return {"mode": "todo", "reason": "", "reply": "还没读到存档，我先记着。"}
        if self.pending_question:
            answered = self.answer_pending(text)
            if answered is not None:
                return answered

        naming = re.match(r"^(?:改名|起名|名字|叫)\s*[:：]?\s*(.{1,12})$", text)
        if naming:
            ok, message = self.set_pending_name(naming.group(1))
            return {"mode": "now" if ok else "refuse", "reason": "命名", "reply": message}

        busy = self.current is not None
        decision = reflect.judge_request(
            self.ctx, state, text, self.persona, self.traits,
            self._day_plan_text(), (self.current or {}).get("title") or "闲着",
            self._long_term_text(), self._tips_text(), context=context)
        mode = str(decision.get("mode") or "todo")
        urgent = any(word in text for word in ("赶快", "赶紧", "立刻", "马上",
                                               "现在", "快点", "抓紧", "这就去"))
        if urgent and mode == "todo":
            mode = "now"
        reply = decision.get("reply") or {
            "now": "行，我这就去。",
            "todo": "记下了，我手头空了就做。",
            "refuse": "这个我就不干了。",
        }.get(mode, "我想想。")

        follow = self._follow_up_target(text, context)
        if follow:
            item = self._promote_todo(follow, decision)
            if item is not None:
                self.inbox.append({
                    "text": follow,
                    "by": by or "有人",
                    "mode": "now",
                    "day": self.day_stamp,
                    "at": store_mod.now(),
                })
                self.inbox = self.inbox[-8:]
                self.force_request = {"text": follow, "by": by or "有人",
                                      "at": store_mod.now(), "left": 8}
                self._journal("plan", "%s 催「%s」→ 立刻做" % (by or "有人", follow),
                              state=state)
                return {"mode": "now", "reason": decision.get("reason") or "",
                        "reply": reply, "item": item, "follow_up": follow}
            # 上一句没有对应待办：记上一句本身，不记“立刻去做”
            text = follow

        item = todos.add(self.store, self.day_stamp, {
            "content": text,
            "source": "%s:%s" % (source, by or ""),
            "by": by,
            "necessity": decision.get("necessity", 6),
            "priority": max(int(decision.get("priority") or 6), 9 if mode == "now" else 0),
            "frequency": decision.get("frequency", "once"),
            "status": "doing" if mode == "now" else "open",
        })
        if item is not None and mode == "now" and item.get("status") in ("open", "deferred"):
            data = todos.load_day(self.store, self.day_stamp)
            for entry in data.get("items") or []:
                if entry.get("id") == item.get("id"):
                    entry["status"] = "doing"
                    entry["note"] = "主人让现在做"
                    entry["updated"] = store_mod.now()
                    break
            todos.save_day(self.store, self.day_stamp, data)
        if mode == "now":
            self.force_request = {"text": text, "by": by or "有人",
                                  "at": store_mod.now(), "left": 8}
        if mode in ("now", "todo"):
            self.inbox.append({
                "text": text,
                "by": by or "有人",
                "mode": mode,
                "day": self.day_stamp,
                "at": store_mod.now(),
            })
            self.inbox = self.inbox[-8:]
        self._journal("plan", "%s 说「%s」→ %s" % (by or "有人", text,
                                                   "立刻做" if mode == "now" else
                                                   ("记着" if mode == "todo" else "拒绝")),
                      state=state)
        return {"mode": mode, "reason": decision.get("reason") or "",
                "reply": reply, "item": item}

    def request_goal(self, goal_id):
        result = self.handle_request(str(goal_id or ""), by="面板", source="grant")
        return result.get("mode") != "refuse", result.get("reply") or ""

    def request_sleep(self):
        if not self.playing:
            return False, "现在没在玩，先让我开始。"
        self.inbox.append({"text": "现在回家睡觉，今天就到这儿。", "by": "面板",
                           "mode": "now", "day": self.day_stamp,
                           "at": store_mod.now()})
        return True, "好，我收拾一下就回家睡。"

    def interrupt(self):
        self.cancel_event.set()
        try:
            self.bridge.cancel()
        except Exception:
            pass
        with self.lock:
            current = dict(self.current) if self.current else None
        if current:
            self._journal("system", "被叫停：%s" % current.get("title"))
        return current

    def pause(self):
        self.paused = True
        self.interrupt()
        return True

    def resume(self):
        self.paused = False
        self.cancel_event.clear()
        self._journal("system", "继续玩。")
        return True

    # ---------- 开始 / 停止 ----------
    def start_play(self):
        self.playing = True
        self.cancel_event.clear()
        state = self._read_state()
        if state.get("ok"):
            self.state = state
            self.state_text = str(state.get("text") or "")
            self._ensure_world(state)
            self._check_day(state)
        self._journal("system", "开始玩。")
        return self.status_text()

    def stop_play(self):
        self.interrupt()
        self.playing = False
        self._journal("system", "停止玩。")
        return True

    # ---------- 说话 / 分享 ----------
    def say(self, text, force=False):
        return self._narrate(str(text or ""), force=force)

    def _say_event(self, event, force=False):
        text = reflect.speak(self.ctx, self.state, event, self.persona, self.traits)
        return self._narrate(text, force=force)

    def _narrate(self, text, force=False):
        text = str(text or "").strip()
        if not text:
            return False
        now = time.time()
        if not force and self.narrate_minutes > 0 and now - self.last_say < self.narrate_minutes * 60:
            return False
        self.last_say = now
        self._journal("say", text, state=self.state)
        if self.on_say is not None:
            try:
                self.on_say(text)
            except Exception as exc:
                self.ctx.log.warning("星露谷发言失败：%s" % exc)
                return False
        return True

    def _share(self, text, image=False, level="normal", force=False):
        text = str(text or "").strip()
        if not text or not self.feedback:
            return False
        if not force:
            day = self.day_stamp or store_mod.stamp(self.state)
            if self.profile is not None:
                if self.profile.data.get("share_day") != day:
                    self.profile.data["share_day"] = day
                    self.profile.data["share_count"] = 0
                    self.profile.save()
                try:
                    count = int(self.profile.data.get("share_count") or 0)
                except (TypeError, ValueError):
                    count = 0
                if count >= self.share_max_per_day:
                    return False
            now = time.time()
            if now - self.last_share < self.share_minutes * 60:
                return False
        self.last_share = time.time()
        image_path = ""
        if image and self.share_images:
            try:
                shot = self.bridge.screenshot()
                if shot.get("ok"):
                    image_path = str(shot.get("path") or "")
            except Exception:
                image_path = ""
        if self.on_share is not None:
            try:
                try:
                    self.on_share(text, image_path)
                except TypeError:
                    self.on_share(text)
            except Exception as exc:
                self.ctx.log.warning("星露谷分享失败：%s" % exc)
                return False
        if self.profile is not None and not force:
            try:
                count = int(self.profile.data.get("share_count") or 0)
            except (TypeError, ValueError):
                count = 0
            self.profile.data["share_count"] = count + 1
            self.profile.save()
        self._journal("share", text, state=self.state)
        return True

    # ---------- 对外状态 ----------
    def _day_plan_text(self):
        if self.store is None:
            return ""
        return plans.day_text(plans.load_day(self.store, self.day_stamp))

    def brief_line(self):
        if not self.state.get("ok"):
            return ""
        return self.prompt_block().replace("\n", "；")[:400]

    def prompt_block(self):
        if not self.state.get("ok"):
            return ""
        now = time.time()
        if self._prompt_cache and now - self._last_prompt_state < 8:
            return self._prompt_cache
        state = self.state
        gm = state.get("game") or {}
        me = state.get("player") or {}
        current = self.current or {}
        activity = str(current.get("title") or current.get("label") or "闲着")
        if self.last_action:
            activity = "%s %s" % (self.last_action.get("name"),
                                  "成功" if self.last_action.get("ok") else "失败")
        thought = (self.profile.data.get("thought") if self.profile else "") or "没什么特别的"
        mood = (self.profile.mood_text() if self.profile else "还算平静")
        plan_text = plans.day_summary(plans.load_day(self.store, self.day_stamp)) if self.store else "还没定"
        farm = needs.crop_summary(state)
        lines = [
            "# Whoa~，你正在玩星露谷！",
            "当前正在做的事情：%s" % activity,
            "星露谷的时间季节和天气：第 %s 年 %s %s 日 %s %s" % (
                gm.get("year"), needs.SEASON_CN.get(gm.get("season"), gm.get("season")),
                gm.get("day"), needs.clock_text(state), "雨天" if gm.get("raining") else "晴天"),
            "心情：%s" % mood,
            "心理活动：%s" % thought,
            "位置：%s (%s,%s) · 体力 %s/%s · 金币 %s" % (
                me.get("location"), me.get("tile_x"), me.get("tile_y"),
                me.get("energy"), me.get("max_energy"), me.get("money")),
            "体力感受：%s" % needs.fatigue_text(state),
            "背包：%s" % (needs.inventory_summary(state, 8) or "空"),
            "农场：作物 %s（熟 %s、待浇 %s、杂物 %s、树 %s、草 %s）" % (
                farm["crops"], farm["ready"], farm["thirsty"], farm["debris"],
                farm["trees"], farm["grass"]),
            "今日打算：%s" % plan_text,
        ]
        if self.notes:
            lines.append("自己的笔记：%s" % self.notes.replace("\n", "；")[:300])
        tips = self._tips_text() if self.tips_enabled else ""
        if tips:
            lines.append(tips.replace("\n", "；")[:600])
        map_text = str((self.profile.data.get("farm_map_text") if self.profile else "") or "")
        if map_text:
            lines.append(map_text)
        if self.last_skills:
            lines.append("技能：%s" % needs.skills_text(state))
        if self.habits_enabled and self.store is not None:
            hint = habits.today_hint(self.store, state)
            if hint:
                lines.append("习惯提示：%s" % hint)
        advice = needs.spending_advice(state)
        if advice:
            lines.append(advice)
        self._prompt_cache = "\n".join(lines)
        self._last_prompt_state = now
        return self._prompt_cache

    def qq_block(self):
        if not self.state.get("ok"):
            return ""
        return self.prompt_block()[:1000]

    def status(self):
        with self.lock:
            current = dict(self.current) if self.current else None
        state = self.state or {}
        return {
            "persona": self.persona,
            "connected": bool(state.get("ok")),
            "playing": self.playing,
            "paused": self.paused,
            "world_key": self.world_key,
            "reason": self.last_error,
            "game": state.get("game") or {},
            "player": state.get("player") or {},
            "inventory": state.get("inventory") or [],
            "inventory_text": needs.inventory_text(state),
            "inventory_full": needs.inventory_full(state),
            "farm": needs.crop_summary(state),
            "observation": state.get("meta") or {},
            "skills": needs.skills(state),
            "skills_text": needs.skills_text(state),
            "professions": (state.get("player") or {}).get("professions") or [],
            "mood": self.profile.mood_text() if self.profile else "",
            "mood_value": self.profile.mood if self.profile else 0,
            "thought": (self.profile.data.get("thought") if self.profile else ""),
            "activity": (self.profile.data.get("activity") if self.profile else ""),
            "notes": self.notes,
            "last_action": self.last_action,
            "steps_today": self.steps_today,
            "tool_calls": self._step_count,
            "current": current,
            "day_plan": plans.load_day(self.store, self.day_stamp) if self.store else None,
            "long_term": plans.load_long_term(self.store, self.long_term_config,
                                              self.max_roots) if self.store else None,
            "todos": todos.load_day(self.store, self.day_stamp) if self.store else None,
            "tips": memtips.stats(self.store) if self.store else {},
            "habits": habits.latest(self.store) if self.store else {},
            "diary_latest": diary.latest(self.store)[1] if self.store else None,
            "traits": self.traits,
        }

    def status_text(self):
        data = self.status()
        if not data["connected"]:
            reason = data.get("reason") or ""
            return "【星露谷】连不上游戏：%s\n（mod 没加载，或还没读存档）" % (reason or "unknown")
        game = data["game"] or {}
        player = data["player"] or {}
        farm = data["farm"] or {}
        lines = []
        if not data.get("playing"):
            lines.append("【星露谷】现在没在玩（说「星露谷 开始玩」让我去干活）")
        lines.append("【星露谷】第 %s 年 %s %s 日 %s · %s" % (
            game.get("year"), needs.SEASON_CN.get(game.get("season"), game.get("season")),
            game.get("day"), needs.clock_text(self.state), "雨" if game.get("raining") else "晴"))
        lines.append("我：%s @ %s (%s,%s) 体力 %s/%s 金币 %s" % (
            player.get("name"), player.get("location"), player.get("tile_x"),
            player.get("tile_y"), player.get("energy"), player.get("max_energy"),
            player.get("money")))
        lines.append("心情：%s · 心理活动：%s" % (data.get("mood") or "-", data.get("thought") or "-"))
        lines.append(needs.inventory_text(self.state, limit=8))
        lines.append("农场：作物 %s · 可收 %s · 待浇 %s · 杂物 %s" % (
            farm.get("crops"), farm.get("ready"), farm.get("thirsty"), farm.get("debris")))
        if data.get("last_action"):
            last = data["last_action"]
            lines.append("上一步：%s %s → %s" % (
                "成功" if last.get("ok") else "失败", last.get("name"),
                str(last.get("result") or "")[:120]))
        if data.get("notes"):
            lines.append("自己的笔记：%s" % str(data["notes"]).replace("\n", "；")[:300])
        lines.append(self._day_plan_text() or "今日打算：还没定")
        lines.append(todos.summary(self.store, self.day_stamp, 6) if self.store else "")
        if self.last_skills:
            lines.append("技能：" + needs.skills_text(self.state))
        if self.habits_enabled and self.store is not None:
            hint = habits.today_hint(self.store, self.state)
            if hint:
                lines.append("习惯：" + hint)
        if self.store is not None:
            lines.append("记忆：%s 条（输入「记忆」查看）" % (data.get("tips") or {}).get("total", 0))
        lines.append("工具调用：%d 次（今天 %d 次）" % (data.get("tool_calls") or 0,
                                                     data.get("steps_today") or 0))
        return "\n".join([line for line in lines if line])

    def habits_text(self):
        if not self.habits_enabled or self.store is None:
            return "习惯记录没开。"
        return habits.render(self.store)

    def tips_text(self):
        if not self.tips_enabled or self.store is None:
            return "记忆 Tips 没开。"
        return self._tips_text()

    # ---------- 重要输入 ----------
    def _save_pending_question(self):
        if self.profile is None:
            return
        self.profile.data["pending_question"] = self.pending_question
        self.profile.save()

    def ask_user(self, question="", kind="text", fallback="", choices=None,
                 timeout=None, context=None):
        if not self.user_input_enabled:
            return False
        context = context or {}
        if not str(question or "").strip():
            generated = ""
            if self.llm_enabled:
                generated = reflect.natural_question(
                    self.ctx, self.state, kind, context, self.persona, self.traits)
            question = generated or context.get("fallback_text") or "这个你想让我怎么选？"
        now = time.time()
        self.pending_question = {
            "id": "%d" % int(now * 1000),
            "question": str(question)[:300],
            "kind": str(kind or "text"),
            "fallback": fallback,
            "choices": choices or [],
            "context": context or {},
            "asked_at": now,
            "deadline": now + max(15, int(timeout or self.user_input_timeout)),
        }
        self._save_pending_question()
        self._journal("system", "向用户提问：" + str(question)[:200])
        self._narrate(str(question)[:300], force=True)
        return True

    def _clear_pending_question(self):
        self.pending_question = None
        self._save_pending_question()

    def _resolve_pending_question(self, reason=""):
        question = self.pending_question
        if not question:
            return
        kind = str(question.get("kind") or "text")
        fallback = question.get("fallback")
        if kind == "name":
            name = self._decide_name() or "猫"
            self.pending_name = name
            self._clear_pending_question()
            self._narrate("没等到回复，我先给它起名「%s」。" % name, force=True)
            self._journal("system", "用户未回复，自动起名：%s" % name)
            return
        answer = fallback or ""
        question["answer"] = answer
        self._clear_pending_question()
        self._narrate("没等到回复，我先按「%s」处理。" % answer, force=True)

    def answer_pending(self, text):
        question = self.pending_question
        if not question:
            return None
        kind = str(question.get("kind") or "text")
        text = str(text or "").strip()
        if kind == "name":
            text = re.sub(r"^(?:改名|起名|名字|叫)\s*[:：]?\s*", "", text).strip()
            ok, message = self.set_pending_name(text)
            if not ok:
                return {"mode": "refuse", "reply": message}
            self._clear_pending_question()
            return {"mode": "now", "reason": "用户命名", "reply": message}
        question["answer"] = text
        self._clear_pending_question()
        return {"mode": "now", "reason": "用户输入", "reply": "记下了。"}

    def set_pending_name(self, name):
        name = str(name or "").strip().replace(" ", "")[:12]
        if not name:
            return False, "名字不能为空（1~12 个字）"
        self.pending_name = name
        if self.profile is not None:
            self.profile.data["pending_name"] = name
            self.profile.save()
        if self.playing:
            self.inbox.append({"text": "游戏让你起名时用这个名字：%s" % name, "by": "面板",
                               "mode": "todo", "day": self.day_stamp,
                               "at": store_mod.now()})
        return True, "记下了，起名时就用「%s」。" % name

    def remember_tip(self, dim, subject, text):
        if not self.tips_enabled or self.store is None:
            return None
        tips = [{
            "content": str(text or "")[:100],
            "tag": [dim if dim in ("npc", "work", "event") else "event"],
            "attributes": {"accuracy": 3, "value": 7,
                           "npc": subject if dim == "npc" else "",
                           "friendship": 0, "relationship": "记录"},
        }]
        added = memtips.add_day(self.store, self.day_stamp, tips)
        return added[0] if added else None

    def status_json(self):
        return self.status()


def _bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "是", "开")


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
