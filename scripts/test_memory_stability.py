# -*- coding: utf-8 -*-
# scripts/test_memory_stability.py
# CatBrain 记忆模块稳定性/冷门用例测试（只读，不写任何记忆文件）
# 用法：runtime\311\python.exe scripts/test_memory_stability.py

import os
import sys
import json
import glob
import time
import types
import threading

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

import jieba
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.process.recall_index import MeowRecallIndex
from func.catbrain.AbstractMem.process.dedup import MeowDedup
from func.catbrain.AbstractMem.process.evidence import MeowEvidence
from func.catbrain.AbstractMem.record.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.record.promise_sweep import MeowPromiseSweep
from func.catbrain.AbstractMem.record import update_abmem as U

FAIL = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else " :: " + str(detail)))
    if not cond:
        FAIL.append(name)


class Seg:
    def segment(self, text):
        return [w for w in jieba.cut(str(text or "")) if len(w.strip()) > 1]


def load_real():
    rows = []
    for path in sorted(glob.glob("character/abstract_memory/meow-*.json")):
        rows.extend(json.load(open(path, encoding="utf-8")))
    return rows


# ---------- 1. 真实数据完整性 ----------
def test_data_integrity(data):
    print("\n== 数据完整性 ==")
    bad = {"not_dict": 0, "no_id": 0, "no_event": 0, "bad_time": 0,
           "tags_not_list": 0, "topics_not_list": 0, "joint_not_list": 0,
           "evidence_not_dict": 0, "accuracy_bad": 0}
    ids = set()
    dup = 0
    for it in data:
        if not isinstance(it, dict):
            bad["not_dict"] += 1
            continue
        if not it.get("id"):
            bad["no_id"] += 1
        elif it["id"] in ids:
            dup += 1
        else:
            ids.add(it["id"])
        if not str(it.get("event") or "").strip():
            bad["no_event"] += 1
        t = str(it.get("time") or "")
        try:
            time.strptime(t[:16], "%Y-%m-%d-%H-%M")
        except ValueError:
            bad["bad_time"] += 1
        for key in ("tags", "topics", "joint"):
            if not isinstance(it.get(key), list):
                bad["%s_not_list" % key] += 1
        if not isinstance(it.get("evidence"), dict):
            bad["evidence_not_dict"] += 1
        if it.get("accuracy") not in (1, 3, 4, 5):
            bad["accuracy_bad"] += 1
    print("entries=%d duplicate_ids=%d" % (len(data), dup))
    for k, v in bad.items():
        print("  %-18s %d" % (k, v))
    check("data-dup-ids", dup == 0, dup)


# ---------- 2. 检索边界 ----------
def test_edge_queries(index, cfg):
    print("\n== 检索边界 ==")
    cases = [
        ("empty", "", 0),
        ("spaces", "   ", 0),
        ("punct", "？？？！！", 0),
        ("single-char", "a", 0),
        ("unknown-latin", "hello world", 0),
        ("unknown-cn", "鲱鱼罐头", 0),
        ("common-entity", "异环", 1),
        ("rare-entity", "张阿姨", 1),
        ("exact-phrase", "愿弦月之眼保佑你", 1),
        ("stopwords-only", "主人 今天 现在 那个", 0),
        ("negation", "不是异环", 0),
        ("date", "2026-10-01", 0),
        ("repeat", "异环 异环 异环 异环", 1),
        ("long-natural", "异环 张阿姨 晚安 星降る海 " * 250, 1),
        ("newlines", "异环\n张阿姨\n异环", 1),
    ]
    for name, q, expect_min in cases:
        t0 = time.perf_counter()
        try:
            picked = index.recall(q, gate_ratio=cfg.recall_gate_ratio, topic="")
            ok = len(picked) >= expect_min
            err = ""
        except Exception as e:
            picked, ok, err = [], False, repr(e)
        dt = (time.perf_counter() - t0) * 1000
        check("edge-%-16s" % name, ok, "n=%d %.1fms %s" % (len(picked), dt, err))

    # 精确句必须命中原三条
    picked = index.recall("愿弦月之眼保佑你", gate_ratio=cfg.recall_gate_ratio, topic="")
    hits = [d for d in picked if "弦月" in str(index.docs[d].get("event", ""))]
    check("exact-phrase-3-hits", len(hits) == 3, hits)

    # 空查询 + 话题：应回退到话题文档而不是崩
    picked = index.recall("", gate_ratio=cfg.recall_gate_ratio, topic="情感")
    check("empty-with-topic", isinstance(picked, list) and len(picked) > 0, len(picked))

    # 非法 months
    try:
        picked = index.recall("异环", months=["xx", None], gate_ratio=cfg.recall_gate_ratio)
        check("bad-months", isinstance(picked, list))
    except Exception as e:
        check("bad-months", False, repr(e))


# ---------- 3. 脏数据合成 ----------
def test_dirty_docs():
    print("\n== 脏数据合成 ==")
    now = "2026-10-30T10:00:00"
    docs = [
        {},
        {"id": "x"},
        {"id": "y", "event": None, "tags": "bad", "topics": None, "joint": "n",
         "time": "bad", "accuracy": "x", "importance": "z", "evidence": "no"},
        {"id": "dup", "event": "重复内容", "tags": ["重复"], "time": "2026-10-01-10-00"},
        {"id": "dup", "event": "重复内容2", "tags": ["重复"], "time": "2026-10-01-10-00"},
        {"id": "big", "event": "长" * 5000, "tags": ["长"], "time": "2026-10-02-10-00"},
        {"id": "neg", "event": "负分条目", "tags": ["负分"], "time": "2026-10-03-10-00",
         "evidence": {"reinforcement": 0.0, "disputation": 3.0,
                      "rein_last_signal_at": None, "disp_last_signal_at": now}},
        {"id": "future", "event": "未来条目", "tags": ["未来"], "time": "2099-01-01-00-00"},
        {"id": "emoji", "event": "🐱 表情和 emoji 测试", "tags": ["emoji"], "time": "2026-10-04-10-00"},
    ]
    try:
        index = MeowRecallIndex(docs, Seg())
        check("dirty-build", True)
    except Exception as e:
        check("dirty-build", False, repr(e))
        return
    check("dirty-dup-id-dedup", len([d for d in index.docs if d == "dup"]) == 1)
    for q in ("重复内容", "长", "负分", "未来", "emoji", ""):
        try:
            index.recall(q, gate_ratio=0.1, topic="")
            ok = True
        except Exception as e:
            ok = False
        check("dirty-query-" + (q or "empty"), ok, "" if ok else "crash")
    check("dirty-blocked-negative", "neg" in index.blocked, index.blocked)


# ---------- 4. 写入规范化 ----------
def make_stub():
    s = object.__new__(U.MeowUpdateAbstractMemory)
    s.config = MeowCatBrainConfig()
    s.summary_tool = types.SimpleNamespace(
        TOPICS=["日常", "爱好", "哲思", "闲聊", "情感"],
        SYSTEM_TAGS={"temp_promise"}, TEMP_PROMISE_TAG="temp_promise")
    return s


def test_normalize():
    print("\n== 写入规范化 ==")
    s = make_stub()

    def norm(**kw):
        base = {"event": "事件", "tags": [], "topics": [], "joint": [], "importance": 5, "accuracy": 5}
        base.update(kw)
        return s._normalize_event(dict(base), "")

    check("norm-empty-event", norm(event=None)["event"] == "")
    check("norm-tags-string", norm(tags="abc")["tags"] == [])
    check("norm-tags-limit", len(norm(tags=["a", "b", "c", "d", "e"])["tags"]) == 3)
    check("norm-topics-string", norm(topics="爱好")["topics"] == ["爱好"])
    check("norm-topics-bad", norm(topics=["坏话题"])["topics"] == ["日常"])
    check("norm-joint-empty", norm(joint="")["joint"] == [])
    check("norm-importance-low", norm(importance=-5)["importance"] == 0)
    check("norm-importance-high", norm(importance=99)["importance"] == 10)
    check("norm-importance-bad", norm(importance="abc")["importance"] == 0)
    for raw, want in ((0, 1), (2, 3), (4, 5), (9, 5), (None, 5), ("x", 5)):
        check("norm-accuracy-%s" % raw, norm(accuracy=raw)["accuracy"] == want, norm(accuracy=raw)["accuracy"])
    for raw, want in (("TRUE", True), ("false", False), (1, True), (0, False), ("是", True)):
        got = "temp_promise" in norm(temp_promise=raw)["tags"]
        check("norm-temp-%s" % raw, got == want, got)


# ---------- 5. 去重与证据 ----------
def test_dedup_evidence():
    print("\n== 去重与证据 ==")
    dedup = MeowDedup()
    a = dedup.make_id({"event": "同一句话", "joint": [{"meowid": "000001", "nickname": "A"}]})
    b = dedup.make_id({"event": "同一句话", "joint": [{"meowid": "000001", "nickname": "A"}]})
    c = dedup.make_id({"event": "同一句话", "joint": [{"meowid": "000002", "nickname": "B"}]})
    check("id-stable", a == b)
    check("id-joint-diff", a != c)
    check("id-empty", dedup.make_id({"event": "", "joint": []}).startswith("mem_"))

    item = {"event": "x", "accuracy": 5}
    dedup._apply_same(item, {}, "2026-10-30T10:00:00", delta=99, accuracy_step=1)
    check("same-cap", item["evidence"]["reinforcement"] == 5.0, item["evidence"])
    check("same-accuracy-cap", item["accuracy"] == 5)

    item2 = {"event": "y", "accuracy": 2}
    dedup._apply_opposite(item2, "2026-10-30T10:00:00")
    check("opposite-accuracy-floor", item2["accuracy"] == 1, item2["accuracy"])

    ev = MeowEvidence()
    check("evidence-missing", ev.score({}, __import__("datetime").datetime.now()) == 0.0)
    bad_ts = {"reinforcement": 1.0, "rein_last_signal_at": "not-a-date"}
    check("evidence-bad-ts", abs(ev.effective_reinforcement(bad_ts, __import__("datetime").datetime.now()) - 1.0) < 1e-9)
    now = __import__("datetime").datetime.now()
    one = {"reinforcement": 0.0, "disputation": 0.0, "sub_zero_days": 0,
           "sub_zero_last_increment_date": None}
    check("subzero-not-counted-at-minus1", ev.mark_sub_zero(one, now) is False)
    one["disputation"] = 3.0
    check("subzero-counted-at-minus3", ev.mark_sub_zero(one, now) is True)
    check("subzero-once-per-day", ev.mark_sub_zero(one, now) is False)


# ---------- 6. 临时约定辅助 ----------
def test_promise_helpers():
    print("\n== 临时约定辅助 ==")
    s = object.__new__(MeowPromiseSweep)
    s.log = types.SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None,
                                  info=lambda *a, **k: None)
    s.config = MeowCatBrainConfig()
    s.dedup = MeowDedup()
    s.jieba = None
    it = {"event": "约定周末看电影", "time": "2026-10-29-20-21", "tags": ["temp_promise"]}

    check("clean-empty", s._clean("", "x") == "")
    check("clean-51", s._clean("长" * 51, "x") == "")
    check("clean-relative", s._clean("今晚看电影", "x") == "")
    check("clean-promise-word", s._clean("答应去看电影", "x") == "")
    check("clean-same", s._clean("约定周末看电影", "约定周末看电影") == "")
    check("clean-valid", s._clean("2026-11-01 和主人看了电影", "x") != "")
    check("window-bad", s._window("bad") == "")
    check("window-ok", s._window("2026-10-01") == "2026-10-31")
    check("grounded-self", s._grounded(it["event"], it, [], "") is False)
    check("grounded-content-plan", s._grounded("周末一起看电影吧", it, [], "周末一起看电影吧") is False)
    check("grounded-content-done", s._grounded("今天看了电影", it, [], "今天看了电影") is True)
    check("grounded-evidence", s._grounded("主人玩异环", it, ["主人玩异环游戏"], "") is True)
    check("grounded-fabricated", s._grounded("主人买了新衣服", it, ["主人说买衣服"], "") is False)


# ---------- 7. 参数解析 ----------
def test_parser():
    print("\n== 参数解析 ==")
    parse = MeowSummaryTool.parse_arguments
    check("parse-valid", parse('{"a": 1}') == {"a": 1})
    check("parse-wrapped", parse('这是结果：{"a": 2} 完毕') == {"a": 2})
    check("parse-python", parse("{'a': 3}") == {"a": 3})
    check("parse-broken", parse("not json") == {})
    check("parse-empty", parse("") == {})


# ---------- 8. 冷门/复杂记忆场景 ----------
def test_content_scenarios(index, cfg):
    print("\n== 冷门/复杂记忆场景（top5 命中） ==")
    scenarios = [
        ("新衣服是什么颜色", "蓝色亮片"),
        ("约好周末看什么电影", "就决定是你了"),
        ("我们的晚安语是什么", "弦月"),
        ("你还欠我什么", "欠"),
        ("猫耳帽到了吗", "猫耳帽"),
        ("塔吉多是谁", "塔吉多"),
        ("薄荷是谁", "薄荷"),
        ("阿德勒的剧情", "阿德勒"),
        ("Blockbench 做的奖杯", "奖杯"),
        ("声卡识别出错", "声卡"),
        ("开蓝色车兜风看樱花", "兜风"),
        ("中秋节怎么过的", "中秋"),
        ("MC 社团第一届活动", "MC社团"),
        ("主人答应圣诞节送的衣服", "圣诞节"),
    ]
    for q, kw in scenarios:
        picked = index.recall(q, gate_ratio=cfg.recall_gate_ratio, topic="")
        top = [str(index.docs[d].get("event", "")) for d in picked[:5]]
        ok = any(kw in e for e in top)
        check("scene-%-22s" % q[:20], ok, "top=%s" % [e[:24] for e in top[:3]])

    # 覆盖/措辞边界：只记录结果，不作为失败
    print("\n-- 覆盖/措辞边界（仅观察）--")
    for q, note in (("PBR 贴图", "PBR 只在用户档案里，摘要记忆没有"),
                    ("上次一起看的番", "措辞太泛，记忆里是具体片名")):
        picked = index.recall(q, gate_ratio=cfg.recall_gate_ratio, topic="")
        top = [str(index.docs[d].get("event", "")) for d in picked[:3]]
        print("  %-8s -> %d 条 %s（%s）" % (q, len(picked), [e[:24] for e in top], note))

    # 冷门 ASR/错别字：只记录结果，不作为失败
    print("\n-- 错别字/ASR 变体（仅观察）--")
    for q in ("乙环", "星降海", "弦月之演", "猪脚饭"):
        picked = index.recall(q, gate_ratio=cfg.recall_gate_ratio, topic="")
        top = [str(index.docs[d].get("event", "")) for d in picked[:3]]
        print("  %-6s -> %d 条 %s" % (q, len(picked), [e[:26] for e in top]))


# ---------- 9. 并发与性能 ----------
def test_perf_concurrency(index, cfg):
    print("\n== 并发与性能 ==")
    t0 = time.perf_counter()
    for _ in range(100):
        index.recall("异环 张阿姨", gate_ratio=cfg.recall_gate_ratio, topic="情感")
    per = (time.perf_counter() - t0) / 100 * 1000
    print("  avg recall %.2f ms" % per)
    check("perf-avg-under-50ms", per < 50, per)

    errors = []
    results = []

    def worker():
        try:
            for _ in range(30):
                results.append(tuple(index.recall("愿弦月之眼保佑你", gate_ratio=cfg.recall_gate_ratio)))
        except Exception as e:
            errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("concurrent-no-error", not errors, errors[:2])
    check("concurrent-stable", len(set(results)) == 1, len(set(results)))


def main():
    data = load_real()
    print("real entries:", len(data))
    test_data_integrity(data)

    t0 = time.perf_counter()
    index = MeowRecallIndex(data, Seg())
    print("index build: %.1f ms" % ((time.perf_counter() - t0) * 1000))
    cfg = MeowCatBrainConfig()

    test_edge_queries(index, cfg)
    test_dirty_docs()
    test_normalize()
    test_dedup_evidence()
    test_promise_helpers()
    test_parser()
    test_content_scenarios(index, cfg)
    test_perf_concurrency(index, cfg)

    print("\n== 汇总 ==")
    print("失败 %d 项" % len(FAIL))
    for name in FAIL:
        print("  -", name)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
