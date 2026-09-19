import json
import os
import re
import time


def _path(state_dir, book):
    """进度文件路径"""
    safe = re.sub(r'[\\/:*?"<>|]', "_", str(book or "book"))[:80]
    return os.path.join(state_dir, f"{safe}.json")


def load_state(state_dir, book):
    """读取阅读进度"""
    path = _path(state_dir, book)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state_dir, book, chapter, section, finished=False):
    """保存阅读进度（读完不删档）"""
    try:
        os.makedirs(state_dir, exist_ok=True)
        data = {"book": book, "chapter": int(chapter), "section": int(section),
                "finished": bool(finished), "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(_path(state_dir, book), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception:
        return {}
