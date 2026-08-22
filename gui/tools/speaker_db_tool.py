# -*- coding: utf-8 -*-
# gui/tools/speaker_db_tool.py
# 声纹库工具：列表 / 启用禁用 / 一键生成 / 新建用户（供 config_gui API 调用）

import os
import json
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SENSEVOICE_DIR = os.path.join(BASE_DIR, ".SenseVoice")
VOICETEXTURE_DIR = os.path.join(SENSEVOICE_DIR, "voicetexture")
SPEAKER_DB = os.path.join(VOICETEXTURE_DIR, "speaker_db.json")
SPEAKER_ENABLED = os.path.join(VOICETEXTURE_DIR, "speaker_enabled.json")
BUILD_SCRIPT = os.path.join(SENSEVOICE_DIR, "build_speaker_db.py")
BUILD_LOG = os.path.join(VOICETEXTURE_DIR, "build_progress.log")
RUNTIME_PYTHON = os.path.join(BASE_DIR, "runtime", "python.exe")


def _load_json(path, default):
    """读取 JSON 文件，缺失或损坏时返回默认值"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, default.__class__) else default
    except Exception:
        return default


def _save_json(path, data):
    """写入 JSON 文件"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_speakers():
    """返回声纹用户列表（含启用状态，默认启用）"""
    db = _load_json(SPEAKER_DB, {})
    enabled = _load_json(SPEAKER_ENABLED, {})
    result = []
    for name in db.keys():
        result.append({"name": name, "enabled": bool(enabled.get(name, True))})
    return result


def toggle_speaker(name, enabled):
    """启用或禁用指定用户"""
    data = _load_json(SPEAKER_ENABLED, {})
    data[name] = bool(enabled)
    _save_json(SPEAKER_ENABLED, data)
    return {"name": name, "enabled": bool(enabled)}


def start_build():
    """后台启动一键生成所有声纹，返回是否成功启动"""
    python = RUNTIME_PYTHON if os.path.exists(RUNTIME_PYTHON) else sys.executable
    log = open(BUILD_LOG, "w", encoding="utf-8")
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.Popen(
        [python, BUILD_SCRIPT],
        cwd=SENSEVOICE_DIR,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        env=env,
    )
    return True


def _read_build_log() -> str:
    """读取生成日志最后一行（兼容 UTF-8 与 GBK 编码）"""
    if not os.path.exists(BUILD_LOG):
        return ""
    raw = None
    try:
        with open(BUILD_LOG, "rb") as f:
            raw = f.read()
    except Exception:
        return ""
    if not raw:
        return ""
    # 优先 UTF-8，失败回退 GBK（Windows 子进程 stdout 默认 GBK）
    text = None
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def get_build_status():
    """读取生成进度（日志文件最后一行）"""
    progress = _read_build_log()
    # 进程是否仍在运行：日志最后一行命中完成/失败标记则视为已结束
    done = ("声纹库已写入" in progress) or ("未找到 wav" in progress) or ("失败" in progress)
    return {"running": not done, "progress": progress}


def create_speaker(name, wav_bytes):
    """新建用户：保存 wav 为 用户名.wav 并立即提取声纹写入库"""
    if not name:
        raise ValueError("用户名不能为空")
    # 清洗文件名
    import re
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', str(name)).strip()
    if not safe:
        raise ValueError("用户名不合法")
    wav_path = os.path.join(VOICETEXTURE_DIR, f"{safe}.wav")
    os.makedirs(VOICETEXTURE_DIR, exist_ok=True)
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)

    # 调用声纹提取（单文件模式）
    python = RUNTIME_PYTHON if os.path.exists(RUNTIME_PYTHON) else sys.executable
    try:
        result = subprocess.run(
            [python, BUILD_SCRIPT, "--single_name", safe, "--single_wav", wav_path],
            cwd=SENSEVOICE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        if result.returncode != 0:
            return {"status": "error", "message": result.stdout or result.stderr}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "声纹提取超时"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "name": safe}
