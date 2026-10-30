# -*- coding: utf-8 -*-
"""观影缓存与归档。

运行期：.temp/movie_watch/<场次>/{meta.json, notes.jsonl, shots/, ending.txt}
结束后：character/plugin_data/movie_watch/<编号>/<场次>/{meta.json, notes.jsonl,
        shots/, ending.txt, summary.md}，并在 <编号>/latest.json 记下最近一场。
"""

import json
import os
import shutil
import time


def new_session_id():
    return time.strftime("%Y%m%d_%H%M%S")


def session_dir(config, session_id):
    return os.path.join(config.temp_root, str(session_id))


def shots_dir(path):
    return os.path.join(path, "shots")


def notes_path(path):
    return os.path.join(path, "notes.jsonl")


def meta_path(path):
    return os.path.join(path, "meta.json")


def ending_path(path):
    return os.path.join(path, "ending.txt")


def summary_path(path):
    return os.path.join(path, "summary.md")


def prepare(path):
    """建好一场的目录骨架"""
    os.makedirs(shots_dir(path), exist_ok=True)
    return path


def read_json(path, default=None):
    try:
        if not os.path.isfile(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    """原子写 JSON"""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_note(path, note):
    """追加一条记录（JSONL，异常不抛出）"""
    line = json.dumps(note, ensure_ascii=False)
    with open(notes_path(path), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_notes(path, limit=0):
    """读回记录（limit>0 时只取最后 limit 条）"""
    file_path = notes_path(path)
    notes = []
    if not os.path.isfile(file_path):
        return notes
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    notes.append(item)
    except Exception:
        return notes
    return notes[-limit:] if limit and limit > 0 else notes


def write_text(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(text or ""))


# ==================== 归档 ====================
def owner_of(uid):
    uid = str(uid or "").strip()
    return uid or "_shared"


def owner_dir(config, uid):
    return os.path.join(config.archive_base, owner_of(uid))


def latest_path(config, uid):
    return os.path.join(owner_dir(config, uid), "latest.json")


def archive(config, path, uid, session_id, meta, notes, ending):
    """把一场缓存归档到 plugin_data，返回归档目录（失败返回 ""）"""
    dest = os.path.join(owner_dir(config, uid), str(session_id))
    try:
        os.makedirs(dest, exist_ok=True)
        write_json(os.path.join(dest, "meta.json"), meta)
        with open(notes_path(dest), "w", encoding="utf-8") as f:
            for note in notes:
                f.write(json.dumps(note, ensure_ascii=False) + "\n")
        write_text(ending_path(dest), ending)
        write_text(summary_path(dest), build_summary(meta, notes, ending))
        src_shots = shots_dir(path)
        if config.keep_shots and os.path.isdir(src_shots):
            shutil.copytree(src_shots, shots_dir(dest), dirs_exist_ok=True)
    except Exception:
        return ""
    info = {
        "session": str(session_id),
        "dir": dest,
        "uid": str(uid or ""),
        "started": meta.get("started", ""),
        "ended": meta.get("ended", ""),
        "duration": meta.get("duration_text", ""),
        "window": meta.get("window_title", ""),
        "notes": len(notes),
        "ending": ending,
    }
    try:
        write_json(latest_path(config, uid), info)
        index = os.path.join(config.archive_base, "index.jsonl")
        with open(index, "a", encoding="utf-8") as f:
            f.write(json.dumps(info, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if not config.keep_temp:
        shutil.rmtree(path, ignore_errors=True)
    return dest


def load_latest(config, uid):
    """最近一场归档的索引（不存在返回空 dict）"""
    data = read_json(latest_path(config, uid), {})
    return data if isinstance(data, dict) else {}


def build_summary(meta, notes, ending):
    """归档用的可读摘要"""
    lines = ["# 观影记录 %s" % meta.get("session", ""), ""]
    for key, label in (("started", "开始"), ("ended", "结束"),
                       ("duration_text", "时长"), ("window_title", "窗口"),
                       ("vision", "视觉模型"), ("dialogue", "台词来源"),
                       ("interval_text", "截屏间隔")):
        value = meta.get(key)
        if value:
            lines.append(f"- {label}：{value}")
    lines.append(f"- 记录：{len(notes)} 帧")
    lines.append("")
    lines.append("## 我的记录")
    if not notes:
        lines.append("（这一场没有记到画面）")
    for note in notes:
        clock = note.get("clock") or "--:--"
        scene = note.get("scene") or ""
        comment = note.get("comment") or ""
        dialogue = note.get("dialogue") or ""
        head = f"- **{clock}**"
        if scene:
            head += f" 画面：{scene}"
        lines.append(head)
        if dialogue:
            lines.append(f"  - 台词：{dialogue}")
        if comment:
            lines.append(f"  - 感想：{comment}")
    lines.append("")
    lines.append("## 整体感觉")
    lines.append(ending or "（无）")
    lines.append("")
    return "\n".join(lines)
