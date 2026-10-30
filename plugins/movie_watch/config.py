# -*- coding: utf-8 -*-
"""观影陪伴插件配置：读 plugins/movie_watch/config.yml（由 schema.py 生成）并做边界钳制。

不 import 主项目代码；主程序配置（视觉 key / SenseVoice 地址）只按 YAML 读取数据。
"""

import os


def _dict(data, key):
    value = (data or {}).get(key)
    return value if isinstance(value, dict) else {}


def _int(data, key, default, low, high):
    try:
        value = int(data.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _float(data, key, default, low, high):
    try:
        value = float(data.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _bool(data, key, default):
    value = data.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def _str(data, key, default=""):
    value = data.get(key, default)
    return str(value if value is not None else default).strip()


class MovieConfig:
    """单场观影的全部可调参数（每次 start 时重新读取，改配置后下一场生效）"""

    def __init__(self, ctx):
        data = ctx.config or {}
        # 主程序 config.yml：只读节点数据（视觉 key / sensevoice 地址），不引用其代码
        self.project_config = ctx.resolve("config.yml")

        # ---------- 截屏 ----------
        cap = _dict(data, "capture")
        self.mode = _str(cap, "mode", "window").lower()
        if self.mode not in ("window", "fullscreen"):
            self.mode = "window"
        self.window_title = _str(cap, "window_title", "")
        self.all_screens = _bool(cap, "all_screens", True)
        self.min_interval = _int(cap, "min_interval", 180, 10, 3600)
        self.max_interval = _int(cap, "max_interval", 240, 10, 3600)
        if self.max_interval < self.min_interval:
            self.max_interval = self.min_interval
        self.max_duration = _int(cap, "max_duration", 4 * 60 * 60, 60, 24 * 60 * 60)
        self.max_side = _int(cap, "max_side", 1280, 320, 3840)
        self.jpeg_quality = _int(cap, "jpeg_quality", 82, 40, 95)
        self.window_gone_confirm = _int(cap, "window_gone_confirm", 90, 0, 1800)
        self.confirm_video_window = _bool(cap, "confirm_video_window", True)
        self.confirm_by_audio = _bool(cap, "confirm_by_audio", True)
        self.confirm_audio_level = _int(cap, "confirm_audio_level", 80, 1, 5000)
        self.confirm_audio_seconds = _float(cap, "confirm_audio_seconds", 2.5, 0.5, 10.0)
        self.allow_fullscreen_fallback = _bool(cap, "allow_fullscreen_fallback", False)

        # ---------- 视觉模型 ----------
        vision = _dict(data, "vision")
        self.vision_source = _str(vision, "source", "meowvision").lower()
        if self.vision_source not in ("meowvision", "custom"):
            self.vision_source = "meowvision"
        self.vision_provider = _str(vision, "provider", "aliyun").lower()
        self.vision_api_key = _str(vision, "api_key", "")
        self.vision_base_url = _str(vision, "base_url", "")
        self.vision_model = _str(vision, "model", "")
        self.vision_max_tokens = _int(vision, "max_tokens", 512, 32, 4096)
        self.vision_temperature = _float(vision, "temperature", 0.8, 0.0, 2.0)
        self.vision_thinking = _bool(vision, "thinking", False)

        # ---------- 记录 ----------
        rec = _dict(data, "record")
        self.keep_shots = _bool(rec, "keep_shots", True)
        self.max_notes = _int(rec, "max_notes", 300, 1, 5000)
        self.context_notes = _int(rec, "context_notes", 40, 1, 200)
        self.short_memory = _bool(rec, "short_memory", True)
        # 只做安全截断：模型写多长就多长，超过这个字数才砍
        self.comment_chars = _int(rec, "comment_chars", 400, 50, 2000)

        # ---------- 台词（扬声器回环 + SenseVoice 服务） ----------
        dlg = _dict(data, "dialogue")
        self.dialogue_enabled = _bool(dlg, "enabled", True)
        self.dialogue_device = _int(dlg, "device_index", -1, -1, 64)
        # 台词回看上限：实际窗口 = 上一帧到现在（跟着截屏间隔自动吻合），超过这个值才截断
        self.dialogue_window = _int(dlg, "window", 300, 30, 1800)
        self.dialogue_chars = _int(dlg, "max_chars", 600, 0, 4000)
        self.dialogue_server = _str(dlg, "server_url", "")
        # 背景音乐常年盖过能量阈值，靠它强制断句才有台词产出
        self.dialogue_segment_seconds = _float(dlg, "segment_seconds", 8.0, 1.0, 60.0)
        # 0 = 用主程序 sensevoice.vad_energy_threshold；片源本身声音小就调低这里
        self.dialogue_vad_threshold = _int(dlg, "vad_threshold", 0, 0, 10000)

        # ---------- 语音 ----------
        voice = _dict(data, "voice")
        self.start_line = _bool(voice, "start_line", True)
        self.start_hint = _str(voice, "start_hint", "")
        self.emotion = _str(voice, "emotion", "")
        self.report_window = _bool(voice, "report_window", True)
        self.tts_source = "toolbox_movie_watch"

        # ---------- 目录 ----------
        arch = _dict(data, "archive")
        temp = _str(data, "temp_dir", "") or os.path.join(".temp", "movie_watch")
        self.temp_root = ctx.resolve(temp)
        arch_dir = _str(arch, "dir", "")
        self.archive_base = ctx.resolve(arch_dir) if arch_dir else ctx.data_dir(per_user="")
        self.keep_temp = _bool(arch, "keep_temp", False)
