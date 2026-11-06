# -*- coding: utf-8 -*-
# gui/tools/speaker_db_tool.py
# 声纹库工具：列表 / 启用禁用 / 一键生成 / 新建用户（供 config_gui API 调用）

import os
import json
import re
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SENSEVOICE_DIR = os.path.join(BASE_DIR, ".vendor/.SenseVoice")
VOICETEXTURE_DIR = os.path.join(SENSEVOICE_DIR, "voicetexture")
SPEAKER_DB = os.path.join(VOICETEXTURE_DIR, "speaker_db.json")
SPEAKER_ENABLED = os.path.join(VOICETEXTURE_DIR, "speaker_enabled.json")
BUILD_SCRIPT = os.path.join(SENSEVOICE_DIR, "build_speaker_db.py")
BUILD_LOG = os.path.join(VOICETEXTURE_DIR, "build_progress.log")
RUNTIME_PYTHON = os.path.join(BASE_DIR, "runtime", "311", "python.exe")


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


SPEAKER_NAME_RE = re.compile(r"^(?P<nickname>.*?)\s*[（(]\s*(?P<uid>\d{6})\s*[)）]\s*$")


def split_speaker_name(name):
    """声纹名拆成 (昵称, 编号)：纯编号（000001）和「昵称(000001)」两种写法都认"""
    text = str(name or "").strip()
    if not text:
        return "", ""
    if len(text) == 6 and text.isdigit():
        return "", text
    match = SPEAKER_NAME_RE.match(text)
    if not match:
        return text, ""
    nickname = match.group("nickname").strip() or text
    return nickname, match.group("uid")


def compose_speaker_name(nickname, uid=""):
    """声纹文件名：填了编号就用编号，没填才退回昵称"""
    uid = str(uid or "").strip()
    if uid:
        return uid
    return str(nickname or "").strip()


def _nickname_of(uid):
    """顺手问一下这个编号叫什么（读不到就留空，声纹本身不依赖档案）"""
    if not uid:
        return ""
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        from func.pipeline.id_signup import IdSignupBridge
        return IdSignupBridge().nickname_of(uid) or ""
    except Exception:
        return ""


def _wav_path(safe, kind="speech"):
    """声纹音频文件路径：说话 `xxx.wav` / 哼唱 `xxx-sing.wav`"""
    suffix = "-sing" if kind == "sing" else ""
    return os.path.join(VOICETEXTURE_DIR, f"{safe}{suffix}.wav")


def _entry_of(raw):
    """声纹库条目归一：旧格式（向量）视为只有说话模板"""
    if isinstance(raw, dict):
        return raw
    return {"speech": raw} if raw is not None else {}


def list_speakers():
    """返回声纹用户列表（编号、昵称、启用状态、说话/哼唱两条语音是否已录入）"""
    db = _load_json(SPEAKER_DB, {})
    enabled = _load_json(SPEAKER_ENABLED, {})
    result = []
    for name in db.keys():
        nickname, uid = split_speaker_name(name)
        if uid and not nickname:
            nickname = _nickname_of(uid)
        entry = _entry_of(db.get(name))
        has_speech = entry.get("speech") is not None
        has_sing = entry.get("sing") is not None
        result.append({
            "name": name,
            "nickname": nickname,
            "id": uid,
            "enabled": bool(enabled.get(name, True)),
            "has_speech": has_speech,
            "has_sing": has_sing,
            "has_speech_wav": os.path.exists(_wav_path(name, "speech")),
            "has_sing_wav": os.path.exists(_wav_path(name, "sing")),
        })
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


def _run_single_extract(single_name, wav_path):
    """调用 build_speaker_db.py 单文件模式抽一条声纹，返回 (ok, message)"""
    python = RUNTIME_PYTHON if os.path.exists(RUNTIME_PYTHON) else sys.executable
    try:
        result = subprocess.run(
            [python, BUILD_SCRIPT, "--single_name", single_name, "--single_wav", wav_path],
            cwd=SENSEVOICE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        if result.returncode != 0:
            return False, (result.stdout or result.stderr or "声纹提取失败")
    except subprocess.TimeoutExpired:
        return False, "声纹提取超时"
    except Exception as e:
        return False, str(e)
    return True, ""


def create_speaker(nickname, wav_bytes, uid="", kind="speech"):
    """新建用户：按「昵称(编号)」命名保存 wav 并立即提取声纹写入库（kind: speech/sing）"""
    safe = compose_speaker_name(nickname, uid)
    if not safe:
        raise ValueError("昵称不能为空")
    # 清洗文件名
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', str(safe)).strip()
    if not safe:
        raise ValueError("昵称不合法")
    kind = "sing" if kind == "sing" else "speech"
    wav_path = _wav_path(safe, kind)
    os.makedirs(VOICETEXTURE_DIR, exist_ok=True)
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)

    # 调用声纹提取（单文件模式）；哼唱模板走 `-sing` 后缀分流
    single_name = f"{safe}-sing" if kind == "sing" else safe
    ok, message = _run_single_extract(single_name, wav_path)
    if not ok:
        return {"status": "error", "message": message}
    return {"status": "ok", "name": safe, "kind": kind}


def upload_audio(name, wav_bytes, kind="speech"):
    """为已有声纹用户替换说话/哼唱语音，并立即重建该域向量"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("缺少声纹用户")
    db = _load_json(SPEAKER_DB, {})
    if name not in db:
        raise ValueError("声纹用户不存在")
    kind = "sing" if kind == "sing" else "speech"
    wav_path = _wav_path(name, kind)
    os.makedirs(VOICETEXTURE_DIR, exist_ok=True)
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)
    single_name = f"{name}-sing" if kind == "sing" else name
    ok, message = _run_single_extract(single_name, wav_path)
    if not ok:
        return {"status": "error", "message": message}
    return {"status": "ok", "name": name, "kind": kind}
