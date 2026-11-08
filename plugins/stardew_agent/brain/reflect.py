# -*- coding: utf-8 -*-
"""角色的「反思」层：日记、记忆 tips、习惯、长线规划、当日计划、请求判断。

所有函数都遵循同一个原则：
    - 能接模型就接，模型失败 / 超时就退回规则，绝不阻塞游戏；
    - 模型只输出结构化 JSON，落盘前统一校验、截断、去重。
"""

import json
import re
import threading

from ..records import diary as diary_mod
from ..records import habits as habits_mod
from ..records import journal as journal_mod
from ..records import memtips as memtips_mod
from ..records import plans as plans_mod
from ..records import store as store_mod
from ..voice import textgen
from . import needs

WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

RECORD_ROLES = (
    "四类记录的分工（写之前先分清）：\n"
    "- 日志：当天按时间记的原始事实，只用来回顾和挑细节，不是要输出的东西；\n"
    "- 记忆：极简、长期有效、以后还能直接拿来用的 tips，不写日期和当天流水账；\n"
    "- 日记：当天的一篇第一人称总结，有自己的评价、情绪和明天的打算；\n"
    "- 习惯：至少 7 天窗口里反复出现的行为规律，必须能说出证据。"
)


def _chat(ctx, messages, seconds=45, max_chars=4000):
    """模型调用；失败/超时/空回复直接抛错，不再退规则。"""
    result = {"text": "", "error": None}

    def worker():
        try:
            result["text"] = textgen.chat(ctx, messages, max_chars=max_chars)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(max(5, int(seconds)))
    if thread.is_alive():
        raise TimeoutError("星露谷反思模型超过 %ss" % seconds)
    if result["error"] is not None:
        raise RuntimeError("星露谷反思模型失败：%s" % result["error"])
    if not str(result["text"] or "").strip():
        raise RuntimeError("星露谷反思模型返回空结果")
    return result["text"]


def _json(text):
    if not text:
        return None
    try:
        return textgen.extract_json(text)
    except Exception:
        return None


def speak(ctx, state, event, persona="", traits=None):
    """把“刚发生了什么”变成角色自己的一句反应；禁止固定台词。"""
    prompt = (
        "%s\n现在的状态：%s\n\n刚发生的事：%s\n\n"
        "用第一人称说一句 15~40 字的反应，像角色自己随口说的；"
        "可以有情绪和评价，不要解释，不要复述全部事实，不要用引号。"
    ) % (_persona_block(persona, traits), _day_facts(state), str(event or "")[:600])
    text = _chat(ctx, [
        {"role": "system", "content": "你只输出这一句话，不要 JSON，不要解释。"},
        {"role": "user", "content": prompt},
    ], seconds=20, max_chars=120)
    text = re.sub(r"\s+", " ", str(text or "")).strip().strip("“”\"'")
    if not text:
        raise RuntimeError("星露谷模型没有生成台词")
    return text[:80]


def _persona_block(persona, traits):
    traits = traits or {}
    return ("你是%s，星露谷的农夫。性格：勤劳 %.1f、爱交际 %.1f、好奇 %.1f、在乎钱 %.1f（0~1）。"
            % (persona or "农夫", float(traits.get("diligence", 0.6)),
               float(traits.get("sociability", 0.5)), float(traits.get("curiosity", 0.5)),
               float(traits.get("thrift", 0.5))))


def _day_facts(state):
    gm = (state or {}).get("game") or {}
    me = (state or {}).get("player") or {}
    return ("第 %s 年 %s %s 日 %s，%s；我在 %s，体力 %s/%s，金币 %s。" % (
        gm.get("year"), gm.get("season"), gm.get("day"), needs.clock_text(state),
        "下雨" if gm.get("raining") else "晴天", me.get("location"),
        me.get("energy"), me.get("max_energy"), me.get("money")))


# ===================== 日记 =====================

def write_diary(ctx, state, store, day_stamp, rows, persona="", traits=None,
                mood_text="", recent_diary="", memory_text=""):
    facts = journal_mod.render(rows, max_rows=120, max_chars=8000)
    prompt = (
        "%s\n%s\n"
        "今天的事实（按时间记录的日志，不是日记；只用来挑细节，不要照抄）：\n%s\n\n"
        "最近的日记（只用来保持语气和连续性）：%s\n"
        "长期记忆 tips（只用来提醒你在意的人和事，不要写成罗列）：%s\n\n"
        "现在写今天的日记。规则：\n"
        "1. 第一人称，写你在星露谷这一天的感受；正文 100 字左右，硬上限 200 字，"
        "超出会被截断。\n"
        "2. 从今天的日志里挑 2~3 个具体细节（人、地点、作物、发现），写自己的评价和小情绪；"
        "不要按时间顺序罗列做了什么，不要写成任务清单或流水账。\n"
        "3. 结尾留一句对明天的打算或牵挂，让以后的日子接得上。\n"
        "4. 只能写今天日志里真实发生的事；不要编造，不要写空泛的总结句。\n"
        "5. 不要标题、不要日期、不要 markdown。\n"
        "只输出 JSON：{\"content\":\"日记正文\",\"mood\":\"两个字到八个字的心情\","
        "\"summary\":\"一句话摘要\",\"tags\":[\"npc:名字\",\"work:类别\",\"event:事件\"]}"
    ) % (_persona_block(persona, traits), RECORD_ROLES, facts or "（今天很安静）",
         recent_diary[:600] or "（还没有）", memory_text[:800] or "（还没什么）")

    text = _chat(ctx, [
        {"role": "system", "content": "你在写自己的日记，只输出 JSON，不要解释，不要代码块。"},
        {"role": "user", "content": prompt},
    ], seconds=50, max_chars=2000)
    data = _json(text)
    content = ""
    mood = mood_text
    summary = ""
    tags = []
    if isinstance(data, dict):
        content = str(data.get("content") or "").strip()
        mood = str(data.get("mood") or mood_text or "").strip()
        summary = str(data.get("summary") or "").strip()
        tags = diary_mod.parse_tags(" ".join(str(tag) for tag in (data.get("tags") or [])))
    if not content:
        raise RuntimeError("星露谷模型没有返回可用的日记正文")
    return diary_mod.write(store, day_stamp, content, state=state, mood=mood,
                           summary=summary, tags=tags)


# ===================== 记忆 tips =====================

def _rule_memories(rows, state, profile=None, limit=5):
    """没有模型时，从日志里挑真正长期有效的小事。"""
    tips = []
    seen = set()

    def add(content, tags, attrs):
        content = re.sub(r"\s+", " ", content).strip()
        if not content or content in seen or memtips_mod.is_transient(content):
            return
        seen.add(content)
        tips.append({"content": content, "tag": tags, "attributes": attrs})

    for row in rows or []:
        kind = row.get("kind")
        content = row.get("content") or ""
        if kind == "dialogue":
            match = re.search(r"(?:遇到|和|跟)\s*([\u4e00-\u9fa5A-Za-z]{2,12})", content)
            if match:
                npc = match.group(1)
                add("%s 和我聊过，关系更近了一点。" % npc, ["npc"],
                    {"accuracy": 2, "value": 5, "npc": npc,
                     "friendship": 1, "relationship": "聊过天"})
        elif kind == "event":
            if any(word in content for word in ("第一次", "解锁", "学会", "发现", "任务", "剧情")):
                add(content[:110], ["event"], {"accuracy": 3, "value": 7})
        elif kind == "action":
            if any(word in content for word in ("学会", "发现", "解锁", "记住")):
                add(content[:100], ["work"], {"accuracy": 2, "value": 5})
    return tips[:limit]


def write_memories(ctx, state, store, day_stamp, rows, diary_data, persona="",
                   traits=None, profile=None, existing_text=""):
    prompt = (
        "%s\n%s\n"
        "今天的事实（日志，只用来判断哪些信息值得长期记住）：\n%s\n"
        "今天的日记：%s\n"
        "已经记住的 tips（不要重复，可以补充或纠正）：%s\n\n"
        "从今天里提炼 0~5 条**长期有价值**的记忆 tips。硬性要求：\n"
        "1. 记忆不是日志、也不是日记：只写以后还能用得上的信息——NPC 的喜好/关系/性格/身份、"
        "长期剧情线索、农场布局和做事方法的稳定经验、工具/商店/路线的稳定知识。\n"
        "2. 绝对禁止一次性流水账：今天种了几颗、浇了水、体力多少、天气、赚了多少、"
        "第几天、睡了多久，这类全部不写。\n"
        "3. 禁止出现任何日期和相对时间：不写今天/昨天/第X天/X月X日/早上/晚上；"
        "要写成不依赖当天、长期成立的陈述句。\n"
        "4. 极其精简，每条不超过 80 字；重复的、只对今天有用的、没把握的宁可不写。\n"
        "5. tag 只能是 npc / work / event；npc 类必须在 attributes 里写 "
        "npc、friendship(0~14)、relationship，并且 content 里要出现 NPC 名字。\n"
        "6. 只输出 JSON，不要解释，不要代码块。\n"
        "好的例子：content=“Pierre 是镇上杂货店老板，喜欢防风草。”；"
        "坏的例子：content=“今天种了 10 颗防风草，赚了 350 金币。”（流水账，禁止）\n"
        "只输出 JSON：{\"tips\":[{\"content\":\"...\",\"tag\":[\"npc\"],"
        "\"attributes\":{\"accuracy\":1-3,\"value\":1-10,\"npc\":\"名字\","
        "\"friendship\":数字,\"relationship\":\"关系\"}}]}"
    ) % (_persona_block(persona, traits), RECORD_ROLES,
         journal_mod.render(rows, max_rows=120, max_chars=9000) or "（没有特别的事）",
         (diary_data or {}).get("content") or "（没写日记）",
         existing_text[:1200] or "（还没有）")

    text = _chat(ctx, [
        {"role": "system", "content": "你只输出 JSON，不要解释，不要代码块。"},
        {"role": "user", "content": prompt},
    ], seconds=45, max_chars=3000)
    tips = memtips_mod.parse_json_tips(text)
    clean = []
    for tip in tips:
        item = memtips_mod.normalize_tip(tip, day_stamp)
        if item:
            clean.append(item)
    return clean[:6]


# ===================== 习惯 =====================

def _habit_facts(store, start_stamp, end_stamp):
    """把窗口内的日志压成「星期 + 钟点 + 做了什么」。"""
    lines = []
    for day in store.existing_days("journal"):
        if store_mod.stamp_order(day) < store_mod.stamp_order(start_stamp):
            continue
        if store_mod.stamp_order(day) > store_mod.stamp_order(end_stamp):
            continue
        weekday = store_mod.weekday_of(day)
        for row in journal_mod.read_day(store, day):
            if row.get("kind") != "action":
                continue
            label = str(row.get("content") or row.get("goal") or "")[:60]
            lines.append("%s %s %s" % (weekday, row.get("time") or "??:??", label))
    return "\n".join(lines[-500:])


def write_habits(ctx, store, start_stamp, end_stamp, persona="", traits=None):
    facts = _habit_facts(store, start_stamp, end_stamp)
    prompt = (
        "%s\n%s\n"
        "下面只统计 %s 到 %s 这 %s 天窗口内的行为（窗口外的一律不算）：\n%s\n\n"
        "请总结 2~5 条**生活习惯**。规则：\n"
        "1. 习惯不是日志、不是日记、也不是记忆：它是这 %s 天里反复出现的行为规律，"
        "只根据上面窗口内的记录总结，不要引入窗口外或想象的行为。\n"
        "2. 至少出现 2~3 次才算习惯；只出现一次的是偶然，不要写。\n"
        "3. content 用第一人称、20 字左右的一句短话，"
        "例如「早上会先看电视再下地」「下午更愿意去镇上转转」。\n"
        "4. 每条都必须带 reason，写清证据：这几天里有几天、在哪个时段、重复做了什么；"
        "没有证据就不要写这一条。\n"
        "5. week_day 用 Mon/Tue/.../Sun，或写「每天」；time 用 HH:MM；"
        "priority 1~6（证据次数越多、越稳定越高）；goal 可选，填最接近的可执行目标 id。\n"
        "6. 这只是给角色的轻量提示，不是死规定；不要用「必须/一定/每天只能」这种强限制。\n"
        "7. 只输出 JSON，不要解释，不要代码块。\n"
        "只输出 JSON：{\"habits\":[{\"content\":\"...\",\"week_day\":[\"Mon\"],"
        "\"time\":[\"06:00\"],\"priority\":4,\"goal\":\"watch_tv\",\"reason\":\"...\"}]}"
    ) % (_persona_block(persona, traits), RECORD_ROLES, start_stamp, end_stamp,
         max(1, store_mod.stamp_order(end_stamp) - store_mod.stamp_order(start_stamp) + 1),
         facts or "（这几天几乎没有行动记录）", habits_mod.EVIDENCE_DAYS)
    text = _chat(ctx, [
        {"role": "system", "content": "你只输出 JSON，不要解释，不要代码块。"},
        {"role": "user", "content": prompt},
    ], seconds=40, max_chars=2500)
    habits = habits_mod.parse_json_habits(text)
    return habits


def rule_memories(rows, state, profile=None, limit=5):
    return _rule_memories(rows, state, profile, limit)


def rule_habits(store, start_stamp, end_stamp):
    return _rule_habits(store, start_stamp, end_stamp)


def _rule_habits(store, start_stamp, end_stamp):
    buckets = {}
    for day in store.existing_days("journal"):
        if store_mod.stamp_order(day) < store_mod.stamp_order(start_stamp):
            continue
        if store_mod.stamp_order(day) > store_mod.stamp_order(end_stamp):
            continue
        weekday = store_mod.weekday_of(day)
        for row in journal_mod.read_day(store, day):
            if row.get("kind") != "action" or not row.get("goal"):
                continue
            try:
                hour = int(str(row.get("time") or "06:00").split(":")[0])
            except (TypeError, ValueError):
                hour = 6
            key = (weekday, hour, row.get("goal"))
            buckets[key] = buckets.get(key, 0) + 1
    habits = []
    for (weekday, hour, goal), count in sorted(buckets.items(), key=lambda pair: -pair[1])[:5]:
        if count < 2:
            continue
        label = str(row.get("content") or row.get("goal") or "")[:40]
        habits.append({
            "content": "%s 前后常做：%s" % ("%02d:00" % hour, label),
            "week_day": [weekday],
            "time": ["%02d:00" % hour],
            "priority": min(6, 2 + count),
            "goal": goal,
            "reason": "这几天里有 %d 天在这个时段做这件事" % count,
        })
    return habits


# ===================== 长线规划 =====================

def update_long_term(ctx, state, store, current_tree, day_stamp, diary_data, rows,
                     persona="", traits=None, max_roots=3, memory_text=""):
    current_text = plans_mod.long_term_text(current_tree, max_nodes=70, max_chars=6000)
    prompt = (
        "%s\n当前的长线规划树：\n%s\n\n今天的日记：%s\n今天的事实：%s\n值得记住的事：%s\n\n"
        "请更新这棵长线规划树。要求：\n"
        "1. 最多保留 %s 个根目标，层级最多 4 层；越往下越具体，第 4 层就是能直接做的动作。\n"
        "2. 每个节点都有 necessity(1~10)、priority(1~10)、frequency"
        "(once/daily/weekly/seasonal)；必要时可以调整，但不要为了改而改。\n"
        "3. 已经做完的叶子标 status=done；如果子层全部完成，父层也标 done，"
        "并往上推；做完的根可以保持 done，不要删掉历史。\n"
        "4. 根据今天的经历和记忆，补充/细化下一步能做的事；不要写空话，"
        "也不要给角色过强的限制。\n"
        "5. 尽量保留原来的 id；新增节点自己起 id。\n"
        "只输出 JSON：{\"reason\":\"一句话\",\"roots\":[{\"id\":\"lt1\",\"title\":\"...\","
        "\"necessity\":9,\"priority\":8,\"frequency\":\"daily\",\"status\":\"active\","
        "\"children\":[...]}]}"
    ) % (_persona_block(persona, traits), current_text or "（还没有）",
         (diary_data or {}).get("content") or "（没写日记）",
         journal_mod.render(rows, max_rows=80, max_chars=6000) or "（没有特别的事）",
         memory_text[:1200] or "（还没什么）", max_roots)
    text = _chat(ctx, [
        {"role": "system", "content": "你只输出 JSON，不要解释，不要代码块。"},
        {"role": "user", "content": prompt},
    ], seconds=60, max_chars=8000)
    data = _json(text)
    if not isinstance(data, dict) or not isinstance(data.get("roots"), list):
        raise RuntimeError("星露谷模型没有返回可解析的长线规划")
    roots = []
    used = set()
    for index, root in enumerate(data.get("roots") or []):
        node = plans_mod.normalize_node(root, 1, "lt%d" % (index + 1), used)
        if node:
            roots.append(node)
    roots = plans_mod.merge_status((current_tree or {}).get("roots") or [], roots)
    for root in roots:
        plans_mod.rollup(root)
    return plans_mod.save_long_term(store, roots, max_roots=max_roots,
                                    reason=str(data.get("reason") or ""))


# ===================== 当日打算 =====================

def make_day_plan(ctx, state, store, long_term, tips_text, habits_hint, todos,
                  last_diary, recent_journal, persona="", traits=None,
                  max_leaves=6, memory_text="", related_diaries=None,
                  observation=""):
    """让角色自己排今天的打算——只是文字方向，不生成任何动作序列。

    真正做什么由 tool_agent 每一步看状态决定，所以这里不写工具名、不写 goal。
    """
    focus = plans_mod.next_long_term_focus(long_term, limit=4)
    focus_text = "\n".join("- %s → %s" % (item["root"], item["leaf"]) for item in focus) or "（还没定）"
    todo_text = "\n".join("- %s（必要%s/优先%s）" % (item.get("content"),
                                                     item.get("necessity"), item.get("priority"))
                          for item in (todos or [])[:8]) or "（没有）"
    related_text = _related_diaries_text(related_diaries)
    game = (state or {}).get("game") or {}
    festival_now = bool(game.get("is_festival") or game.get("festival"))
    festival_line = ("今天有节日：%s。节日上的事优先。\n"
                     % (game.get("festival") or "节日")) if festival_now else ""
    prompt = (
        "%s\n现在的状态：%s\n%s\n"
        "长线方向（只是方向，不是任务清单）：\n%s\n\n"
        "这阵子想推进的分支：\n%s\n\n"
        "长期记忆 tips：\n%s\n\n生活习惯：%s\n\n"
        "今天记下的待办：\n%s\n\n最近一篇日记：%s\n"
        "相关旧日记：\n%s\n最近的事实：%s\n\n"
        "当前游戏状态（完整文字状态）：\n%s\n\n"
        "请用第一人称排今天大概想做的事，写成 3~%s 条「打算」：\n"
        "1. 每条一句标题 + 一两句细节；写人话，不要写工具名、不要写参数、不要写 goal。\n"
        "2. 想清楚轻重：农活、赚钱、社交、探索、休息都要有，别当工作机器；\n"
        "   体力低/背包满/天黑了就先把吃饭、整理、回家排前面。\n"
        "3. 长线方向只是 guidance，今天做不完也没关系，允许临时改主意。\n"
        "4. 每条的 start/end 用游戏时间 HH:MM，按星露谷作息（商店 9:00 开门，24:00 前睡）。\n"
        "只输出 JSON：{\"reason\":\"一句话说明为什么这样排\","
        "\"plan\":[{\"title\":\"上午先把田弄一遍\",\"detail\":\"看看熟了的先收，再浇水\","
        "\"start\":\"06:30\",\"end\":\"10:00\"}]}"
    ) % (_persona_block(persona, traits), _day_facts(state), festival_line,
         plans_mod.long_term_text(long_term, max_nodes=50, max_chars=4000) or "（还没有）",
         focus_text, tips_text[:1400] or "（还没什么）",
         habits_hint or "（还不到 7 天）", todo_text,
         (last_diary or "（还没有）")[:600], related_text,
         journal_mod.render(recent_journal, max_rows=50, max_chars=4000) or "（还没有）",
         (observation or "")[:7000], max_leaves)
    reply = _chat(ctx, [
        {"role": "system", "content": "你只输出 JSON，不要解释，不要代码块。"},
        {"role": "user", "content": prompt},
    ], seconds=55, max_chars=4000)
    data = _json(reply)
    if not isinstance(data, dict) or not isinstance(data.get("plan"), list):
        raise RuntimeError("星露谷模型没有返回可解析的今日打算")
    nodes = []
    for index, item in enumerate(data.get("plan") or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        nodes.append({
            "title": title[:80],
            "detail": str(item.get("detail") or "")[:240],
            "start": item.get("start") or "",
            "end": item.get("end") or "",
            "necessity": 6,
            "priority": max(1, 8 - index),
            "frequency": "once",
            "status": "pending",
            "source": "self",
        })
        if len(nodes) >= max_leaves:
            break
    if not nodes:
        raise RuntimeError("星露谷模型返回的今日打算为空")
    return nodes, str(data.get("reason") or "")


def _related_diaries_text(items, max_chars=1200):
    lines = []
    for data in (items or [])[:3]:
        text = diary_mod.render(data, with_meta=False)
        if text:
            lines.append(text)
    return ("\n\n".join(lines) or "（没有检索到相关的旧日记）")[:max_chars]


# ===================== 请求判断 =====================

def judge_request(ctx, state, text, persona="", traits=None, current_plan="", busy="",
                  long_term_text="", memory_text="", context=None):
    """别人提了一句要求：让她自己决定立刻做、记着、还是拒绝。

    context 是主链路这次调用带进来的最近对话（OpenAI messages），用来理解
    “立刻去做 / 刚才那个 / 就按这个来”这类指代。
    """
    recent = ""
    lines = []
    for item in (context or [])[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
        if role in ("user", "assistant") and content:
            lines.append("%s：%s" % ("用户" if role == "user" else "你", content[:220]))
    if lines:
        recent = "最近对话（用来理解“立刻去做 / 刚才那个”）：\n" + "\n".join(lines) + "\n\n"
    prompt = (
        "%s\n现在：%s\n手上正在做：%s\n今天打算：%s\n长线方向：%s\n记得的事：%s\n\n"
        "%s有人对你说：「%s」\n\n"
        "请像角色自己一样判断：\n"
        "- 明确要现在做、而且身体/时间允许 → mode=now；\n"
        "- 可以做但不必现在、或者手上正忙 → mode=todo；\n"
        "- 明显做不了/不合适 → mode=refuse。\n"
        "同时给 necessity(1~10)、priority(1~10)、frequency(once/daily/weekly/seasonal)，"
        "以及一句自然口语的回复（30 字内）。\n"
        "只输出 JSON：{\"mode\":\"now|todo|refuse\",\"necessity\":7,\"priority\":8,"
        "\"frequency\":\"once\",\"reason\":\"一句话\",\"reply\":\"对对方说的话\"}"
    ) % (_persona_block(persona, traits), _day_facts(state), busy or "闲着",
         (current_plan or "").replace("\n", "；")[:800] or "（还没定）",
         (long_term_text or "").replace("\n", "；")[:500] or "（还没定）",
         (memory_text or "").replace("\n", "；")[:400] or "（还没什么）",
         recent, str(text or "")[:300])
    reply = _chat(ctx, [
        {"role": "system", "content": "你只输出 JSON，不要解释，不要代码块。"},
        {"role": "user", "content": prompt},
    ], seconds=35, max_chars=1200)
    data = _json(reply)
    if not isinstance(data, dict):
        raise RuntimeError("星露谷模型没有返回可解析的请求判断")
    mode = str(data.get("mode") or "").lower()
    if mode not in ("now", "todo", "refuse"):
        raise RuntimeError("星露谷模型返回了无法识别的请求处理方式：%r" % mode)
    try:
        necessity = max(1, min(10, int(data.get("necessity") or 6)))
        priority = max(1, min(10, int(data.get("priority") or 6)))
    except (TypeError, ValueError):
        necessity, priority = 6, 6
    return {
        "mode": mode,
        "necessity": necessity,
        "priority": priority,
        "frequency": str(data.get("frequency") or "once"),
        "reason": str(data.get("reason") or "")[:120],
        "reply": str(data.get("reply") or "").strip()[:80],
    }


def natural_question(ctx, state, kind, context, persona, traits):
    """让角色用自然口语向用户提问，而不是套固定模板；模型不可用时返回空串。"""
    context = context or {}
    subject = str(context.get("subject") or "").strip()
    details = []
    if subject:
        details.append("对象：" + subject)
    if kind == "name":
        details.append("事情：要给这只宠物起名字")
        details.append("要点：先问用户想叫什么，不要自己先起；如果用户没回，你会稍后自己决定。")
    elif kind == "profession":
        details.append("事情：升级后要选职业")
        choices = context.get("choices") or []
        if choices:
            details.append("候选：" + "；".join(
                "%s（%s）" % (item.get("name"), item.get("desc") or item.get("id"))
                for item in choices[:6]))
        details.append("要点：问用户想让你选哪个，不要念菜单式播报。")
    else:
        details.append("事情：" + str(context.get("purpose") or "有一个需要用户决定的问题"))
    system = (
        "你是正在玩《星露谷物语》的角色，正在和主人/观众用 QQ 或语音说话。"
        "用第一人称、自然、简短的口语问一个问题，像真的在玩游戏时随口问。"
        "不要用固定模板，不要列 JSON，不要超过 60 个汉字，只输出你要说的那一句话。"
    )
    user = "角色：" + str(persona or "星露谷角色") + "\n" + "\n".join(details)
    text = _chat(ctx, [{"role": "system", "content": system},
                       {"role": "user", "content": user}], seconds=30, max_chars=200)
    text = re.sub(r"\s+", " ", str(text or "")).strip().strip('"“”')
    return text[:120]


def suggest_name(ctx, state, persona, memory_text, rows, diary_text):
    system = (
        "你是正在玩《星露谷物语》的角色。现在要给一只猫起名字。"
        "结合你记得的人、地方、经历和今天发生的事，用自然口语想一个 2~4 个汉字的名字。"
        "不要解释，不要列候选，不要用“小星/小白/咪咪”这种通用模板，只输出名字本身。"
    )
    facts = []
    if memory_text:
        facts.append("长期记忆：\n" + str(memory_text)[:1200])
    if diary_text:
        facts.append("最近日记：\n" + str(diary_text)[:800])
    if rows:
        facts.append("今天日志：\n" + "\n".join(
            str((row or {}).get("content") or "") for row in (rows or [])[-20:])[:1200])
    user = "角色：" + str(persona or "星露谷角色") + "\n" + "\n".join(facts)
    text = _chat(ctx, [{"role": "system", "content": system},
                       {"role": "user", "content": user}], seconds=30, max_chars=80)
    text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(text or ""))
    return text[:8]
