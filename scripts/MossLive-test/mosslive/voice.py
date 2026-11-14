# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive/voice.py
# 参考音频 → MOSS 音色：
#   1) 从主项目 character/ref_audio/config.json 找到角色对应情绪的参考音频；
#   2) 转成单声道 16bit WAV，裁到 <= 29 秒（接口限制：<=10MB、<=30 秒）；
#   3) 调 POST /v1/audio/voices 复刻成 voice_id，结果缓存在 voice_cache.json。
# 之后在 MOSS-Live 里用 change_voice 指定这个 voice_id。
#
# 复刻失败时回落到 voice.fallback_name（一个现成音色 ID），保证通话能继续。

import hashlib
import json
import tempfile
import time
from pathlib import Path

import numpy as np
import requests


class VoiceError(Exception):
    """参考音频/复刻相关错误"""


class VoiceSelection:
    """最终的音色选择"""

    def __init__(self, voice_id: str = "", origin: str = "default", detail: str = "", ref_path=None):
        self.voice_id = voice_id
        self.origin = origin
        self.detail = detail
        self.ref_path = Path(ref_path) if ref_path else None

    def describe(self) -> str:
        if self.origin == "演练":
            return f"演练：将用参考音频复刻音色（{self.ref_path}），未上传"
        if not self.voice_id:
            return f"使用服务端默认音色（{self.detail or '未指定'}）"
        path = f"，参考音频 {self.ref_path}" if self.ref_path else ""
        return f"音色 {self.voice_id}（{self.origin}{path}）"


# ---------- 参考音频定位 ----------

def resolve_ref_audio(cfg, character_name: str, console) -> tuple:
    """返回 (wav_path, meta_dict)；找不到返回 (None, {})"""
    ra = cfg.voice.get("ref_audio") or {}
    explicit = str(ra.get("file") or "").strip()
    if explicit:
        path = cfg.project_path(explicit)
        if path.exists():
            return path, {"file": str(path), "origin": "显式配置"}
        console.warn(f"voice.ref_audio.file 不存在: {path}")

    source = str(ra.get("source") or "").strip()
    if not source:
        return None, {}
    config_path = cfg.project_path(source)
    if not config_path.exists():
        console.warn(f"参考音频配置不存在: {config_path}")
        return None, {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        console.warn(f"参考音频配置解析失败 {config_path}: {e}")
        return None, {}
    if not isinstance(data, dict) or not data:
        console.warn(f"参考音频配置为空: {config_path}")
        return None, {}

    wanted = str(ra.get("character") or character_name or "").strip()
    character = wanted if wanted in data else ""
    if not character:
        character = next(iter(data))
        if wanted:
            console.warn(f"参考音频里没有角色“{wanted}”，改用“{character}”")
    emotions = data.get(character) or {}
    if not isinstance(emotions, dict) or not emotions:
        console.warn(f"角色“{character}”没有参考音频条目")
        return None, {}

    emotion = str(ra.get("emotion") or "neutral").strip()
    entry = emotions.get(emotion)
    if not isinstance(entry, dict):
        emotion, entry = next(iter(emotions.items()))
        console.warn(f"没有指定情绪“{ra.get('emotion')}”，改用“{emotion}”")
    audio = str((entry or {}).get("audio") or "").strip()
    if not audio:
        console.warn(f"参考音频条目没有 audio 字段: {character}/{emotion}")
        return None, {}

    path = cfg.project_path(audio)
    if not path.exists():
        console.warn(f"参考音频文件不存在: {path}")
        return None, {}
    return path, {
        "character": character,
        "emotion": emotion,
        "text": str((entry or {}).get("text") or ""),
        "lang": str((entry or {}).get("lang") or "zh"),
        "origin": f"{_display(config_path, cfg.project_root)} → {character}/{emotion}",
    }


def _display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _fingerprint(path: Path, max_seconds: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    h.update(f"|{max_seconds}".encode("utf-8"))
    return h.hexdigest()


# ---------- 参考音频准备 ----------

def prepare_sample(path: Path, max_seconds: int, console) -> Path:
    """读参考音频 → 单声道 int16 WAV（裁到 max_seconds 秒），写入系统临时文件"""
    try:
        import soundfile as sf
    except Exception as e:
        raise VoiceError(f"需要 soundfile 读取参考音频: {e}") from e

    try:
        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as e:
        raise VoiceError(f"参考音频读取失败 {path}: {e}") from e
    if audio.size == 0:
        raise VoiceError(f"参考音频为空: {path}")

    mono = audio.mean(axis=1)
    limit = max(1, int(max_seconds * sr))
    truncated = mono.size > limit
    if truncated:
        mono = mono[:limit]
    console.info(
        f"参考音频: {path.name} {sr}Hz 单声道 {mono.size / sr:.1f}s"
        + ("（已裁剪）" if truncated else "")
    )

    mono = np.clip(mono, -1.0, 1.0)
    tmp = tempfile.NamedTemporaryFile(prefix="mosslive_ref_", suffix=".wav", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        sf.write(str(out), mono, sr, subtype="PCM_16")
    except Exception as e:
        raise VoiceError(f"参考音频转写失败: {e}") from e

    size = out.stat().st_size
    if size > 10 * 1024 * 1024:
        out.unlink(missing_ok=True)
        raise VoiceError(f"参考音频处理后仍超过 10MB（{size / 1024 / 1024:.1f}MB）")
    return out


# ---------- 缓存 ----------

def _cache_path(cfg) -> Path:
    return cfg.local_path((cfg.voice.get("clone") or {}).get("cache_file") or "voice_cache.json")


def load_cache(cfg) -> dict:
    path = _cache_path(cfg)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(cfg, data: dict, console=None):
    path = _cache_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        if console:
            console.warn(f"音色缓存写入失败 {path}: {e}")


# ---------- 复刻 ----------

def clone_voice(cfg, sample: Path, console) -> str:
    """上传参考音频，创建音色，返回 voice_id"""
    key = cfg.api_key
    if not key:
        raise VoiceError(cfg.key_hint())
    url = str(cfg.api.get("http_base") or "https://api.mosi.cn").rstrip("/") + "/v1/audio/voices"
    clone_cfg = cfg.voice.get("clone") or {}
    name = str(clone_cfg.get("voice_name") or "mosslive-test").strip()

    console.info(f"上传参考音频复刻音色（{name}）…")
    try:
        with open(sample, "rb") as f:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                data={"name": name},
                files={"audio_sample": (sample.name, f, "audio/wav")},
                timeout=120,
            )
    except requests.RequestException as e:
        raise VoiceError(f"复刻请求失败: {e}") from e

    if resp.status_code >= 400:
        body = resp.text[:500]
        raise VoiceError(f"复刻失败 HTTP {resp.status_code}: {body}")
    try:
        obj = resp.json()
    except Exception as e:
        raise VoiceError(f"复刻返回不是 JSON: {resp.text[:300]}") from e
    voice_id = str((obj or {}).get("id") or "").strip()
    if not voice_id:
        raise VoiceError(f"复刻返回缺少 id: {obj}")
    console.info(f"复刻成功: voice_id={voice_id}")
    return voice_id


# ---------- 对外入口 ----------

def resolve_voice(cfg, character_name: str, console, allow_network: bool = True) -> VoiceSelection:
    """按配置选择音色：clone（默认）/ name / default"""
    mode = str(cfg.voice.get("mode") or "clone")
    fallback = str(cfg.voice.get("fallback_name") or "").strip()

    if mode == "default":
        return VoiceSelection("", "default", "voice.mode=default")

    if mode == "name":
        name = str(cfg.voice.get("name") or "").strip()
        if not name:
            raise VoiceError("voice.mode=name 时 voice.name 不能为空")
        return VoiceSelection(name, "配置指定", "voice.name")

    # ---- clone ----
    ref_path, meta = resolve_ref_audio(cfg, character_name, console)
    if not ref_path:
        if fallback:
            console.warn(f"没有可用参考音频，回落到音色 {fallback}")
            return VoiceSelection(fallback, "回落", "无参考音频")
        console.warn("没有可用参考音频，将使用服务端默认音色")
        return VoiceSelection("", "default", "无参考音频")

    clone_cfg = cfg.voice.get("clone") or {}
    max_seconds = int(clone_cfg.get("max_seconds") or 29)
    fingerprint = _fingerprint(ref_path, max_seconds)
    cache = load_cache(cfg)
    if (
        not clone_cfg.get("recreate")
        and cache.get("fingerprint") == fingerprint
        and cache.get("voice_id")
        and cache.get("voice_name") == str(clone_cfg.get("voice_name") or "")
    ):
        console.info(f"复用已复刻音色: {cache.get('voice_id')}")
        return VoiceSelection(str(cache["voice_id"]), "复刻缓存", "voice_cache.json", ref_path)

    if not allow_network:
        console.info(f"[演练] 将用参考音频复刻音色: {ref_path}")
        return VoiceSelection("", "演练", "未上传", ref_path)

    sample = prepare_sample(ref_path, max_seconds, console)
    try:
        voice_id = clone_voice(cfg, sample, console)
    except VoiceError as e:
        if fallback:
            console.warn(f"{e}；回落到音色 {fallback}")
            return VoiceSelection(fallback, "回落", str(e), ref_path)
        console.warn(f"{e}；将使用服务端默认音色")
        return VoiceSelection("", "default", str(e), ref_path)
    finally:
        try:
            sample.unlink(missing_ok=True)
        except Exception:
            pass

    save_cache(cfg, {
        "voice_id": voice_id,
        "voice_name": str(clone_cfg.get("voice_name") or ""),
        "fingerprint": fingerprint,
        "ref_audio": str(ref_path),
        "character": meta.get("character", ""),
        "emotion": meta.get("emotion", ""),
        "created_at": int(time.time()),
    }, console)
    return VoiceSelection(voice_id, "参考音频复刻", str(ref_path), ref_path)
