# -*- coding: utf-8 -*-
# scripts/check_config_keys.py
"""死键体检：找出 config.yml 里"没有任何代码引用"的配置节点，用于清理过期配置。

跑法（项目根目录）：
    runtime\\python.exe scripts\\check_config_keys.py                 # 全量
    runtime\\python.exe scripts\\check_config_keys.py flux_painter     # 只看某个一级节点
    runtime\\python.exe scripts\\check_config_keys.py --only-dead     # 只列死键

判定方式：取叶子键名（如 default_style），在 func/ gui/ scripts/ api.py *.py 里找字面量。
      命中 = 活着；0 命中 = 疑似死键（可能只是字符串拼接出来的，需人工确认）。
"""
import argparse
import os
import re
import sys

import yaml

SKIP_DIRS = {".git", ".temp", ".ComfyNode", "logs", "character", "runtime", "__pycache__",
             ".NapCat", ".Sovits", ".RVC", ".desktopet", ".phone", ".NeteaseMusic", "node_modules",
             "model", "models", "refers", "database"}
CODE_EXT = {".py", ".js", ".html", ".json"}


def walk_leaves(node, path=""):
    """展开 YAML 到 [(路径, 叶子键名)]"""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            out += walk_leaves(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += walk_leaves(v, f"{path}[]")
    else:
        out.append((path, path.split(".")[-1].replace("[]", "")))
    return out


def collect_code(root):
    """把所有代码文件读成 (路径, 内容)；区分后端(func/、根 py)与前端(gui/)"""
    blobs = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root).replace("\\", "/")
        top = rel.split("/")[0]
        if rel not in (".", "") and (top in SKIP_DIRS or rel.startswith(".")):
            dirnames[:] = []
            continue
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in CODE_EXT or fn == "config.yml":
                continue
            p = os.path.join(dirpath, fn)
            relp = os.path.relpath(p, root).replace("\\", "/")
            try:
                if os.path.getsize(p) > 4 * 1024 * 1024:
                    continue
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    blobs.append((relp, f.read()))
            except Exception:
                pass
    return blobs


def is_frontend(relp):
    return relp.startswith("gui/")


def main():
    ap = argparse.ArgumentParser(description="config.yml 死键体检")
    ap.add_argument("section", nargs="?", default="", help="只看某个一级节点，如 flux_painter")
    ap.add_argument("--only-dead", action="store_true", help="只列问题键")
    ap.add_argument("--root", default=".", help="项目根目录")
    args = ap.parse_args()

    cfg_path = os.path.join(args.root, "config.yml")
    if not os.path.isfile(cfg_path):
        print("找不到 config.yml：", cfg_path)
        return 1
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    node = cfg
    if args.section:
        for seg in args.section.split("."):
            node = (node or {}).get(seg)
        if node is None:
            print("没有这个节点：", args.section)
            return 1

    leaves = walk_leaves(node, args.section)
    blobs = collect_code(args.root)

    rows = []
    for path, key in leaves:
        if not key or len(key) < 3:
            continue
        pat = re.compile(r"(?<![\w.])" + re.escape(key) + r"(?![\w])")
        be, fe = [], []
        for relp, text in blobs:
            if pat.search(text):
                (fe if is_frontend(relp) else be).append(relp)
        rows.append((path, be, fe))

    no_be = [r for r in rows if not r[1]]
    print(f"config.yml 叶子键 {len(rows)} 个："
          f"后端有读取 {len(rows) - len(no_be)} 个 / 后端从不读取 {len(no_be)} 个")
    print("=" * 100)
    if not args.only_dead:
        print("--- 后端有读取 ---")
        for path, be, fe in sorted(rows):
            if be:
                print(f"  OK   {path:50s} <- {', '.join(be[:2])}")
    if no_be:
        print("--- 后端从不读取（前端若还有文本框 => 无效界面，可删）---")
        for path, be, fe in sorted(no_be):
            mark = "前端有" if fe else "前端也无"
            print(f"  DEAD {path:50s} [{mark}: {', '.join(fe[:2]) or '-'}]")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
