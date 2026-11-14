# -*- coding: utf-8 -*-
"""预热：把 characters.json 里每个角色的 danbooru 高频画面 tag 抓下来并缓存。

用法：python scripts/prewarm_character_tags.py [--limit 100] [--only 马剃天爱星]

结果写入 .vendor/.ComfyNode/prompt_reference/danbooru_character_tags.json，
写入后永久保留（不再过期），之后离线也能用。
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Log:
    def info(self, m="", *a):
        print(m)

    warning = info
    error = info
    debug = info
    exception = info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--only", default="")
    ap.add_argument("--sleep", type=float, default=1.2)
    ap.add_argument("--cookie", default="",
                    help="danbooru 的 cf_clearance cookie，形如 cf_clearance=xxxx")
    ap.add_argument("--ua", default="",
                    help="浏览器 User-Agent（cf_clearance 与之绑定，建议一起给）")
    args = ap.parse_args()

    from func.toolbox.flux_painter.config import TBFluxPainterConfig
    from func.toolbox.flux_painter.prompts.danbooru_tool import top_tags

    cfg = TBFluxPainterConfig()
    if args.cookie:
        cfg.danbooru_cookie = args.cookie
    if args.ua:
        cfg.danbooru_user_agent = args.ua
    if not cfg.danbooru_cookie:
        print("提示：danbooru 有 Cloudflare 人机验证，裸脚本会被 403。")
        print("     请在浏览器打开 danbooru → F12 → Application → Cookies，")
        print("     复制 cf_clearance 的值，然后：")
        print("     python scripts/prewarm_character_tags.py --cookie \"cf_clearance=xxxx\"")
        print("     （或把同一串填进 config.yml 的 flux_painter.danbooru_cookie）")
    ref = os.path.join(cfg.comfy_node_dir, "prompt_reference", "characters.json")
    doc = json.load(open(ref, encoding="utf-8"))
    chars = doc.get("characters") or []
    if args.only:
        chars = [c for c in chars if args.only in (c.get("name") or "") or
                 args.only.lower() in (c.get("name_en") or "").lower()]

    ok_n = 0
    for c in chars:
        tag = c.get("tag") or c.get("name_en")
        ok, tags = top_tags(tag, config=cfg, log=_Log(), limit=args.limit)
        print("%-28s %s" % (tag, ", ".join(tags[:8]) if ok else "（失败/无数据）"))
        ok_n += 1 if ok else 0
        time.sleep(args.sleep)
    print("完成：%d/%d 个角色有数据" % (ok_n, len(chars)))


if __name__ == "__main__":
    main()
