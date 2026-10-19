# -*- coding: utf-8 -*-
# scripts/ingest_animelist.py
# 把本地动画片单（D:\.Animations\.Animationlist\memory.json）注入知识库
#
# 数据形态：{番剧名: {poster, rating, review, screenshots}}
#   - rating: 0~5，0 表示未评分
#   - review: 个人短评
#
# 内容优先级（按用户要求）：
#   1. 萌娘百科条目正文（主）
#   2. 我的评分 / 短评（辅）
# 全部条目都会入库（片单里都是看过的），不是只入有打分的。
#
# 用法：
#   python scripts/ingest_animelist.py                 # 只报告（含萌百命中率）
#   python scripts/ingest_animelist.py --apply         # 入库
#   python scripts/ingest_animelist.py --apply --rebuild   # 先删旧 watchlist 再入

import argparse
import hashlib
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _bootstrap import install_log_fallback

install_log_fallback()

DEFAULT_LIST = r"D:\.Animations\.Animationlist\memory.json"
STAR = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}

_PAREN_RE = re.compile(r"[（(]([^（()）]{1,40})[）)]")
# 季数标记：第X季/第X期/Season N/S1/最终季
_SEASON_RE = re.compile(
    r"(第[一二三四五六七八九十0-9]+[季期]|Season\s*\d+|(?<![A-Za-z])S\d+(?![0-9])|最终季)",
    re.IGNORECASE)
# 版本后缀
_VERSION_RE = re.compile(r"(重制版|重置版|剧场版|TV版|完全版|新作)$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff·：:？?，,、～~！!]+")
_ASCII_RE = re.compile(r"[A-Za-z0-9\-_.!:' ]+")


# ==================== 标题变体 ====================
def title_variants(title: str) -> list:
    """生成用于萌百检索的候选标题（去重保序）

    memory.json 里的名字是「我习惯的叫法」，不一定是萌百条目名，实测需要：
      Bleach（死神）                → 去括号 "Bleach" 命中 BLEACH
      No Game No Life（游戏人生）     → 括号内中文名命中
      一拳超人 第一季 第二季          → 去掉全部季数标记 → 一拳超人
      乱码1/2 重制版 第一季           → 去季数+去"重制版" → 乱码1/2（萌百是乱马1/2，靠前缀命中）
      VIVY-FlouriteEyesSong         → 取首个词 VIVY
      继承的拖油瓶                   → 前缀命中完整长标题
    """
    t = str(title or "").strip()
    cands = []

    def add(x):
        x = str(x or "").strip(" ：:·-—_/")
        if x and x not in cands:
            cands.append(x)

    def strip_seasons(x, rounds=4):
        cur = str(x or "")
        for _ in range(rounds):
            nxt = _SEASON_RE.sub("", cur).strip(" ：:·-—_/")
            if nxt == cur:
                break
            cur = nxt
        return cur

    add(t)
    no_paren = _PAREN_RE.sub("", t).strip(" ：:·-—_/")
    add(no_paren)
    for i in [m.group(1) for m in _PAREN_RE.finditer(t)]:
        add(i)

    # 去季数（原串 + 去括号串各来一轮）
    for src in (t, no_paren):
        s = strip_seasons(src)
        add(s)

    # 去版本后缀
    for x in list(cands):
        s = _VERSION_RE.sub("", x).strip(" ：:·-—_/")
        if s and s != x:
            add(s)
            add(strip_seasons(s))

    # 只保留最长中文片段（英文名+中文副标题的混合写法）
    for x in list(cands):
        frags = _CJK_RE.findall(x)
        if frags:
            frag = max(frags, key=len).strip(" ：:·-—_/")
            if frag and frag != x:
                add(frag)

    # 纯英文名的首个词（VIVY-FlouriteEyesSong → VIVY）
    for x in list(cands):
        if _ASCII_RE.fullmatch(x):
            tok = re.split(r"[\-_:\.! ]+", x)[0].strip()
            if tok and len(tok) >= 4:
                add(tok)

    return cands


def _norm(s: str) -> str:
    """去掉空白/标点/大小写，便于比较"""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _plausible(query: str, hit: str) -> bool:
    """兜底搜索的命中是否可能就是同一部作品（长度合理性，防串味）

    上限放到 2.6 是为了容纳「简称 → 完整长标题」的情况
    （继母的拖油瓶 → 继母的拖油瓶是我的前女友）；同时仍能拦住
    Naruto → Naruto Shippūden: Original Soundtrack III（比值 6.8）这类串味。
    """
    q, h = _norm(query), _norm(hit)
    if not q or not h:
        return False
    ratio = len(h) / len(q)
    return 0.5 <= ratio <= 2.6


# ==================== 萌百解析 ====================
def resolve_wiki(title: str, spider, max_chars: int):
    """按候选标题逐个尝试，返回 (正文, 实际命中的条目名)

    每个候选先试精确条目，再试 opensearch 前 3 条（带合理性校验）。
    """
    for cand in title_variants(title):
        # 1) 精确条目
        txt = spider.extract(cand, "moegirl", chars=max_chars)
        if txt:
            return txt.strip(), cand
        # 2) opensearch 前缀搜索（取 6 条：正确条目常被同名词条挤到后面，
        #    例如 Naruto 的前 3 条都是原声带专辑）
        try:
            hits = spider.opensearch(cand, "moegirl", 6)
        except Exception:
            hits = []
        # 优先完全一致，其次长度最接近
        hits = [h for h in (hits or []) if _plausible(cand, h)]
        hits.sort(key=lambda h: (0 if _norm(h) == _norm(cand) else 1, abs(len(_norm(h)) - len(_norm(cand)))))
        for h in hits:
            txt = spider.extract(h, "moegirl", chars=max_chars)
            if txt:
                return txt.strip(), h
    return "", ""


# ==================== 文档组装 ====================
def build_overview(data: dict) -> str:
    """整份片单汇总成一篇可检索文档"""
    buckets = {5: [], 4: [], 3: [], 2: [], 1: [], 0: []}
    for title, info in data.items():
        r = int((info or {}).get("rating") or 0)
        buckets.setdefault(r if 0 <= r <= 5 else 0, []).append(title)

    lines = ["《我的动画片单》", "", f"共收录 {len(data)} 部看过的动画，按我的评分分档列出。"]
    for r in (5, 4, 3, 2, 1, 0):
        items = buckets.get(r) or []
        if not items:
            continue
        label = f"{r} 分（{STAR.get(r, '')}）" if r else "未评分"
        lines.append(f"\n## {label} —— {len(items)} 部")
        for t in items:
            lines.append(f"- {t}")
    return "\n".join(lines)


def build_doc(title: str, info: dict, wiki_text: str) -> str:
    """单部动画一篇：萌百正文优先，个人评分短评在后"""
    rating = int((info or {}).get("rating") or 0)
    review = str((info or {}).get("review") or "").strip()

    lines = [f"《{title}》"]
    if wiki_text:
        lines.append("\n## 萌娘百科条目\n" + wiki_text)

    lines.append("\n## 我的记录")
    if rating:
        lines.append(f"我的评分：{rating} 分（{STAR.get(rating, '')}）")
    else:
        lines.append("我的评分：未评分")
    if review:
        lines.append(f"我的短评：{review}")
    lines.append("状态：已看过（收录于我的动画片单）")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="动画片单 → 知识库")
    ap.add_argument("--list", default=DEFAULT_LIST, help="memory.json 路径")
    ap.add_argument("--apply", action="store_true", help="真正入库（默认只报告）")
    ap.add_argument("--no-enrich", action="store_true", help="不抓萌娘百科（只入评分短评）")
    ap.add_argument("--max-chars", type=int, default=3000, help="单部萌百正文上限")
    ap.add_argument("--sleep", type=float, default=0.6, help="每次百科请求间隔秒")
    ap.add_argument("--rebuild", action="store_true",
                    help="入库前先删除已有 watchlist 来源（修正元数据后重建）")
    args = ap.parse_args()

    if not os.path.exists(args.list):
        print(f"片单不存在: {args.list}")
        return 1

    with open(args.list, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        print("memory.json 结构异常")
        return 1
    print(f"片单: {len(data)} 部（全部入库）")

    spider = None
    if not args.no_enrich:
        from func.database.search.spider.mediawiki_spider import CatLearnMediaWikiSpider
        spider = CatLearnMediaWikiSpider()

    docs = [{
        "text": build_overview(data),
        "source_type": "watchlist",
        "source_id": "watch_overview",
        "doc_name": "我的动画片单",
        "url": "",
        "site": "animelist",
        "tags": "动画/片单/评分",
    }]

    hit, miss = 0, []
    for i, (title, info) in enumerate(data.items(), 1):
        wiki_text, hit_title = "", ""
        if spider is not None:
            wiki_text, hit_title = resolve_wiki(title, spider, args.max_chars)
            if wiki_text:
                hit += 1
            else:
                miss.append(title)
            time.sleep(max(0.0, args.sleep))

        docs.append({
            "text": build_doc(title, (info or {}), wiki_text),
            "source_type": "watchlist",
            "source_id": "watch_" + hashlib.md5(title.encode("utf-8")).hexdigest()[:16],
            "doc_name": title,
            "url": ("https://mzh.moegirl.org.cn/" + hit_title) if hit_title else "",
            "site": "animelist",
            "tags": f"动画/片单/评分{int((info or {}).get('rating') or 0)}",
        })
        if i % 20 == 0 or i <= 2:
            print(f"  [{i}/{len(data)}] {title}  "
                  f"{'✓ ' + hit_title if hit_title else '✗ 无萌百'}  "
                  f"正文 {len(docs[-1]['text'])} 字")

    total = sum(len(d["text"]) for d in docs)
    print(f"\n文档 {len(docs)} 篇（1 汇总 + {len(data)} 单片），合计 {total} 字")
    if spider is not None:
        print(f"萌百命中 {hit}/{len(data)}（{hit / max(1, len(data)) * 100:.0f}%）")
    if miss:
        print(f"\n未命中萌百的 {len(miss)} 部（仅入库评分/短评）：")
        for t in miss:
            print(f"  - {t}")

    if not args.apply:
        print("\n[只报告] 未入库。确认后执行：")
        print("  runtime\\311\\python.exe scripts/ingest_animelist.py --apply"
              + (" --rebuild" if args.rebuild else ""))
        return 0

    from func.database.store.source_ingest import CatLearnSourceIngest
    if args.rebuild:
        from func.database.store.vector_db import CatLearnVectorDB
        removed = CatLearnVectorDB().delete_source("watchlist")
        print(f"\n[重建] 已删除旧 watchlist 来源: {removed} 个 chunk")
    stats = CatLearnSourceIngest().ingest(docs)
    print(f"\n入库结果: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
