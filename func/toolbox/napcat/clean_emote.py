# -*- coding: utf-8 -*-
# func/toolbox/napcat/clean_emote.py
# 清理 .NapCat/EmoteLab 表情包文件名：MiaoWu_名字_日期.gif → 名字.gif
# 同名（完全相同名字）仅保留最新一个，其余删除

import os
import re
import datetime

# 项目根目录（clean_emote.py 位于 func/toolbox/napcat/，向上三级为根目录）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
EMOTE_DIR = os.path.join(_PROJECT_ROOT, ".NapCat", "EmoteLab")
# 日期后缀：_YYYY-MM-DD-HH-MM-SS.gif
DATE_RE = re.compile(r"_(?P<date>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})\.gif$", re.IGNORECASE)


def _parse_name(filename: str):
    """解析文件名，返回 (表情名, 日期) 或 None"""
    if not filename.lower().endswith(".gif"):
        return None
    base = filename[:-4]  # 去 .gif
    if not base.startswith("MiaoWu_"):
        return None
    inner = base[len("MiaoWu_"):]
    m = DATE_RE.search("_" + inner + ".gif")
    if m:
        name = inner[: len(inner) - len(m.group("date")) - 1]
        try:
            dt = datetime.datetime.strptime(m.group("date"), "%Y-%m-%d-%H-%M-%S")
            return name.strip(), dt
        except ValueError:
            return None
    return None


def clean():
    if not os.path.isdir(EMOTE_DIR):
        print(f"目录不存在: {EMOTE_DIR}")
        return
    # name -> (latest_dt, src_filename)
    latest = {}
    for fn in os.listdir(EMOTE_DIR):
        parsed = _parse_name(fn)
        if not parsed:
            continue
        name, dt = parsed
        if name not in latest or dt > latest[name][0]:
            latest[name] = (dt, fn)

    for name, (dt, src_fn) in latest.items():
        target = os.path.join(EMOTE_DIR, f"{name}.gif")
        src = os.path.join(EMOTE_DIR, src_fn)
        if src_fn != f"{name}.gif":
            try:
                os.replace(src, target)
                print(f"重命名: {src_fn} -> {name}.gif")
            except Exception as e:
                print(f"重命名失败 {src_fn}: {e}")

    # 删除所有非 .gif 以及未清理的历史 MiaoWu_*.gif（已由重命名处理，此处兜底清理残留旧文件）
    for fn in os.listdir(EMOTE_DIR):
        if not fn.lower().endswith(".gif"):
            continue
        parsed = _parse_name(fn)
        if parsed and fn != f"{parsed[0]}.gif":
            try:
                os.remove(os.path.join(EMOTE_DIR, fn))
                print(f"删除旧文件: {fn}")
            except Exception as e:
                print(f"删除失败 {fn}: {e}")

    print("表情包文件名清理完成")


if __name__ == "__main__":
    clean()
