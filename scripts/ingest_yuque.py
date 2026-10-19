# -*- coding: utf-8 -*-
# scripts/ingest_yuque.py
# 把语雀知识库的文档正文注入知识库（语雀 API 免鉴权，返回 lake(HTML) 正文）
#
# 用法：
#   python scripts/ingest_yuque.py                          # 默认 mhmzh/bbs-mod，只报告
#   python scripts/ingest_yuque.py --apply                  # 真正入库
#   python scripts/ingest_yuque.py --book mhmzh/bbs-wiki --apply
#   python scripts/ingest_yuque.py --dry-sample 3           # 只抓前 3 篇看质量

import argparse
import hashlib
import os
import re
import sys
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _bootstrap import install_log_fallback

install_log_fallback()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_APPDATA_RE = re.compile(
    r'window\.appData\s*=\s*JSON\.parse\(decodeURIComponent\("([^"]+)"\)\)')


def _session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/json"})
    return s


def _appdata(html: str) -> dict:
    m = _APPDATA_RE.search(html or "")
    if not m:
        return {}
    import json
    try:
        return json.loads(unquote(m.group(1)))
    except Exception:
        return {}


def _html_to_text(html: str) -> str:
    """lake(HTML) → 纯文本，保留标题层级感"""
    if not html:
        return ""
    try:
        from lxml import html as lhtml
        doc = lhtml.fromstring(html)
        for bad in doc.xpath("//script | //style"):
            bad.getparent().remove(bad)
        lines = []
        for node in doc.iter():
            tag = node.tag if isinstance(node.tag, str) else ""
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                t = (node.text_content() or "").strip()
                if t:
                    lines.append(f"\n## {t}")
            elif tag == "li":
                t = (node.text_content() or "").strip()
                if t:
                    lines.append(f"- {t}")
            elif tag == "p":
                t = (node.text_content() or "").strip()
                if t:
                    lines.append(t)
        if not lines:
            return re.sub(r"\n{2,}", "\n", doc.text_content()).strip()
        text = "\n".join(lines)
        text = re.sub(r"[ \t\u3000]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "").strip()


def fetch_book(sess, book: str):
    """返回 (book_id, book_name, [doc_nodes])"""
    url = f"https://www.yuque.com/{book}"
    r = sess.get(url, timeout=25)
    d = _appdata(r.text)
    b = (d or {}).get("book") or {}
    if not b.get("id"):
        raise RuntimeError(f"未能解析书籍信息: {url}")
    docs = [n for n in (b.get("toc") or []) if n.get("type") == "DOC" and n.get("url")]
    return int(b["id"]), str(b.get("name") or book), docs


def fetch_doc(sess, book: str, book_id: int, slug: str):
    """返回 (title, url, text)"""
    api = f"https://www.yuque.com/api/docs/{slug}?book_id={book_id}"
    r = sess.get(api, timeout=30, headers={"Referer": f"https://www.yuque.com/{book}/{slug}"})
    if r.status_code != 200:
        return "", "", ""
    j = r.json()
    data = j.get("data") or {}
    title = str(data.get("title") or slug).strip()
    text = _html_to_text(str(data.get("content") or ""))
    return title, f"https://www.yuque.com/{book}/{slug}", text


def main():
    ap = argparse.ArgumentParser(description="语雀文档 → 知识库")
    ap.add_argument("--book", default="mhmzh/bbs-mod", help="语雀书籍路径，如 mhmzh/bbs-mod")
    ap.add_argument("--apply", action="store_true", help="真正入库（默认只报告）")
    ap.add_argument("--dry-sample", type=int, default=0,
                    help="只抓前 N 篇并打印摘要，入库流程不执行")
    args = ap.parse_args()

    sess = _session()
    book_id, book_name, nodes = fetch_book(sess, args.book)
    print(f"书籍: {book_name}（id={book_id}）  文档数: {len(nodes)}")

    limit = args.dry_sample or len(nodes)
    docs = []
    for i, n in enumerate(nodes[:limit], 1):
        slug = str(n.get("url") or "").strip()
        try:
            title, url, text = fetch_doc(sess, args.book, book_id, slug)
        except Exception as e:
            print(f"  [{i}/{limit}] {slug} 失败: {type(e).__name__}: {e}")
            continue
        if not text:
            print(f"  [{i}/{limit}] {slug} 正文为空，跳过")
            continue
        docs.append({
            "text": f"《{title}》\n\n{text}",
            "source_type": "yuque",
            "source_id": "yuque_" + hashlib.md5(url.encode("utf-8")).hexdigest()[:16],
            "doc_name": title,
            "url": url,
            "site": "yuque",
            "tags": book_name,
        })
        print(f"  [{i}/{limit}] {title}  正文 {len(text)} 字")

    total_chars = sum(len(d["text"]) for d in docs)
    print(f"\n抓到 {len(docs)} 篇，合计 {total_chars} 字")

    if args.dry_sample:
        for d in docs:
            print(f"\n--- {d['doc_name']} ---")
            print(d["text"][:400])
        return 0

    if not docs:
        print("没有可入库文档")
        return 1

    if not args.apply:
        print(f"\n[只报告] 未入库。确认后执行：")
        print(f"  runtime\\311\\python.exe scripts/ingest_yuque.py --book {args.book} --apply")
        return 0

    from func.database.store.source_ingest import CatLearnSourceIngest
    stats = CatLearnSourceIngest().ingest(docs)
    print(f"\n入库结果: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
