# -*- coding: utf-8 -*-
# func/database/seed.py
# 知识库预填充：按 gui/tools/prefill_seed.json 的站点+词条，爬取真实网页正文入库

import os
import sys
import time
import json
import re
import hashlib

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.search.crawler import CatLearnCrawler
from func.database.commet.chunker import CatLearnChunker
from func.database.store.port import get_embedding
from func.database.store.vector_db import CatLearnVectorDB

SOURCE_TYPE = "seed"
PER_ITEM = 2
CONFIG_PATH = os.path.join(_ROOT, "gui", "tools", "prefill_seed.json")


def load_config() -> dict:
    """读 prefill_seed.json → {site: {"label": str, "keywords": [..]}}，失败返回空"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            sites = (json.load(f) or {}).get("sites") or {}
        out = {}
        for site, cfg in sites.items():
            if isinstance(cfg, dict):
                kws = [str(k).strip() for k in (cfg.get("keywords") or []) if str(k).strip()]
                out[str(site)] = {"label": str(cfg.get("label") or site), "keywords": kws}
        return out
    except Exception:
        return {}


@singleton
class CatLearnSeed:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.crawler = CatLearnCrawler()
        self.chunker = CatLearnChunker()
        self.embedding = get_embedding()
        self.vdb = CatLearnVectorDB()

    @staticmethod
    def _cid(site, name, i):
        return "seed_" + hashlib.md5(f"{site}:{name}:{i}".encode()).hexdigest()[:20]

    @staticmethod
    def _safe(name):
        return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(name))

    def _archive(self, site, name, pages):
        dest = os.path.join(".DataBase", "raw_seed", site, self._safe(name) + ".json")
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(pages, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception(f"归档失败: {name}")

    def seed(self, reset=True, sites=None, site_keywords=None):
        if not self.vdb.available or not self.embedding.available:
            self.log.error("向量库或 embedding 不可用，跳过预填充")
            return 0

        cfg = load_config()
        # 调用方传入的自定义词条覆盖 json 配置
        if site_keywords:
            for site, kws in site_keywords.items():
                cfg.setdefault(str(site), {"label": str(site), "keywords": []})
                cfg[str(site)]["keywords"] = [str(k).strip() for k in (kws or []) if str(k).strip()]

        if reset:
            removed = self.vdb.delete_source(SOURCE_TYPE)
            if removed:
                self.log.info(f"已清理历史预填充数据 {removed} 条")

        total = 0
        for site, c in cfg.items():
            if sites and site not in sites:
                continue
            for name in c.get("keywords") or []:
                try:
                    total += self._crawl_one(site, c.get("label") or site, name)
                except Exception:
                    self.log.exception(f"预填充失败: {site}/{name}")
                time.sleep(0.5)

        self.log.info(f"预填充完成，共入库 {total} 条")
        return total

    def _crawl_one(self, site, label, name):
        results = self.crawler.search_site(site, name)
        used = site
        if not results and site != "baidu":
            results = self.crawler.search_site("baidu", name)
            used = "baidu"
        results = (results or [])[:PER_ITEM]
        if not results:
            return 0

        pages = []
        for r in results:
            url = str(r.get("url") or "").strip()
            if not url:
                continue
            content = self.crawler.direct_spider.fetch_detail(url)
            if content and content.strip():
                pages.append({"title": str(r.get("title") or name), "url": url, "content": content.strip()})
            time.sleep(0.3)

        if not pages:
            return 0

        self._archive(site, name, pages)
        text = "\n\n".join(f"【{p['title']}】\n{p['content']}" for p in pages)
        chunks = [c for c in self.chunker.chunk(text, 256, 0.1) if c.strip()]
        vectors = self.embedding.embed_texts(chunks)
        if len(vectors) != len(chunks):
            return 0

        ids = [self._cid(site, name, i) for i in range(len(chunks))]
        payload = [{
            "text": c,
            "metadata": {
                "source_type": SOURCE_TYPE,
                "source_id": ids[i],
                "doc_name": name,
                "site": used,
                "origin_site": site,
                "label": label,
                "tags": label,
                "url": pages[0]["url"],
            },
        } for i, c in enumerate(chunks)]

        n = self.vdb.upsert_with_embeddings(payload, vectors, ids)
        self.log.info(f"[预填充] {site}/{label} {name} → {n} 块")
        return n


def run_seed(reset=True, sites=None, site_keywords=None):
    return CatLearnSeed().seed(reset, sites, site_keywords)


def main():
    import argparse
    p = argparse.ArgumentParser(description="知识库预填充")
    p.add_argument("--no-reset", action="store_true")
    p.add_argument("--site")
    a = p.parse_args()
    print(f"预填充完成：{run_seed(reset=not a.no_reset, sites=[a.site] if a.site else None)} 条")


if __name__ == "__main__":
    main()
