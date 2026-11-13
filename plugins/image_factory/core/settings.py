# -*- coding: utf-8 -*-
"""插件配置（只保留蔚蓝档案 + MOSS 出图需要的东西）。"""


import json


def _get(d, path, default=None):
    """按点分路径取配置值。"""
    cur = d
    for key in str(path).split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


_BAD = {"", "undefined", "null", "none", "nil"}


def _text(value, default=""):
    """取字符串配置，空值/undefined 走默认。"""
    s = str(value if value is not None else "").strip()
    return default if s.lower() in _BAD else s


class Settings:
    """插件配置的只读视图。"""
    def __init__(self, raw, root):
        """解析全部配置项。"""
        self.raw = raw or {}
        self.root = str(root)

        self.enabled = bool(_get(self.raw, "enabled", True))
        self.trigger = _text(_get(self.raw, "trigger"), "Meowlisis蔚蓝色图")
        self.cooldown = max(0, int(_get(self.raw, "cooldown_seconds", 60) or 0))
        self.max_images = max(1, min(9, int(_get(self.raw, "max_images", 9) or 9)))
        self.default_images = max(1, min(self.max_images,
                                        int(_get(self.raw, "default_images", 1) or 1)))

        # ---- 引擎 ----
        self.host = _text(_get(self.raw, "engine.host"), "127.0.0.1")
        self.port = int(_get(self.raw, "engine.port", 8188) or 8188)
        self.autostart = bool(_get(self.raw, "engine.autostart", True))
        self.boot_timeout = max(30, int(_get(self.raw, "engine.boot_timeout", 120) or 120))
        self.stall_timeout = max(60, int(_get(self.raw, "engine.stall_timeout", 900) or 900))
        self.output_dir = self._path(_get(self.raw, "engine.output_dir", ".temp/image_factory"))
        self.python = self._path(_get(self.raw, "engine.python", "runtime/312/python.exe"))
        self.kernel = self._path(_get(self.raw, "engine.kernel_dir", ".vendor/.ComfyNode/ComfyUI"))

        # ---- 模型（MOSS 三件套 + DMD）----
        self.unet = _text(_get(self.raw, "models.unet"), "moss_image_sft_bf16.safetensors")
        self.clip = _text(_get(self.raw, "models.clip"), "qwen3.5_9b_w4a8_gptq.safetensors")
        self.vae = _text(_get(self.raw, "models.vae"), "flux2-vae.safetensors")
        self.dmd_lora = _text(_get(self.raw, "models.dmd_lora"),
                              "MOSS-Image-SFT-8-steps-dmd.safetensors")
        self.dmd_strength = float(_get(self.raw, "models.dmd_strength", 0.7) or 0.7)
        self.clip_device = _text(_get(self.raw, "models.clip_device"), "default").lower()
        if self.clip_device not in ("default", "cpu"):
            self.clip_device = "default"
        # 额外 LoRA 链（风格件/滑块件）：[{name, strength, enabled, trigger}]
        self.loras = self._parse_loras(_get(self.raw, "models.loras", []))

        # ---- 采样：固定 8 步 DMD（与官方工作流开关开启档一致）----
        self.width = int(_get(self.raw, "sampling.width", 832) or 832)
        self.height = int(_get(self.raw, "sampling.height", 1216) or 1216)
        self.steps = int(_get(self.raw, "sampling.steps", 8) or 8)
        self.cfg = float(_get(self.raw, "sampling.cfg", 1.0) or 1.0)
        self.shift = float(_get(self.raw, "sampling.shift", 5.0) or 5.0)
        self.sampler = _text(_get(self.raw, "sampling.sampler"), "euler")
        self.scheduler = _text(_get(self.raw, "sampling.scheduler"), "sgm_uniform")
        self.seed = int(_get(self.raw, "sampling.seed", -1))
        self.quality = _text(_get(self.raw, "sampling.quality"), "best quality, highres")
        self.negative = _text(
            _get(self.raw, "sampling.negative"),
            "worst quality, bad anatomy, watermark, jpeg artifact, "
            "censored, mosaic censoring, bar censor")

        # ---- 提示词 ----
        self.adult = bool(_get(self.raw, "prompt.adult", True))
        self.unlock = bool(_get(self.raw, "prompt.unlock", True))
        self.use_law = bool(_get(self.raw, "prompt.use_law", True))
        self.law_file = self._path(_get(self.raw, "prompt.law_file",
                                        ".vendor/.ComfyNode/prompt_reference/ANIMA3_prompt_law.md"))
        self.law_budget = max(2000, int(_get(self.raw, "prompt.law_budget", 24000) or 24000))
        self.llm_max_tokens = max(256, int(_get(self.raw, "prompt.llm_max_tokens", 1600) or 1600))
        self.temperature = float(_get(self.raw, "prompt.temperature", 0.9) or 0.9)
        self.style_extra = _text(_get(self.raw, "prompt.style_extra"))
        self.json_layout = bool(_get(self.raw, "prompt.json_layout", False))
        self.appear_file = self._path(_get(self.raw, "prompt.appear_file",
                                           "plugins/image_factory/data/appearance.json"))
        self.tag_cache_file = self._path(_get(self.raw, "prompt.tag_cache_file",
                                              "plugins/image_factory/data/danbooru_tags.json"))
        self.danbooru_enabled = bool(_get(self.raw, "prompt.danbooru", True))
        self.danbooru_timeout = max(3, int(_get(self.raw, "prompt.danbooru_timeout", 12) or 12))

        # ---- 归档 / 发送 ----
        self.archive_dir = self._path(_get(self.raw, "archive.dir",
                                           "character/plugin_data/image_factory"))
        self.keep_images = int(_get(self.raw, "forward.keep_images", 0) or 0)
        self.forward_enabled = bool(_get(self.raw, "forward.enabled", True))
        self.forward_title = _text(_get(self.raw, "forward.title"), "蔚蓝色图")
        self.forward_sender = _text(_get(self.raw, "forward.sender_name"), "图片工厂")
        self.forward_fallback = bool(_get(self.raw, "forward.fallback_single", True))
        self.pay_image = self._path(_get(self.raw, "forward.pay_image",
                                         "plugins/image_factory/pay.jpg"))
        self.notify_progress = bool(_get(self.raw, "notify.progress", False))
        self.notify_each = bool(_get(self.raw, "notify.each_image", False))

    def _parse_loras(self, items):
        """解析额外 LoRA 链；接受 JSON 字符串 / 列表，坏数据一律当空。"""
        if isinstance(items, str):
            try:
                items = json.loads(items or "[]")
            except Exception:
                return []
        if not isinstance(items, list):
            return []
        out = []
        for it in items:
            if not isinstance(it, dict) or not str(it.get("name") or "").strip():
                continue
            if not it.get("enabled", True):
                continue
            out.append({"name": str(it["name"]).strip(),
                        "strength": float(it.get("strength", 0.8) or 0.0),
                        "trigger": str(it.get("trigger") or "").strip()})
        return out

    def _path(self, value):
        """相对路径按项目根拼接；注意 `.vendor` / `.temp` 这类点开头目录不能被吃掉"""
        p = str(value or "").strip()
        if not p:
            return ""
        if len(p) > 1 and p[1] == ":":
            return p
        if not self.root:
            return p
        if p.startswith("./") or p.startswith(".\\"):
            p = p[2:]
        return self.root.replace("\\", "/").rstrip("/") + "/" + p.replace("\\", "/").lstrip("/")

    @property
    def base_url(self):
        """内核 HTTP 地址。"""
        return "http://%s:%d" % (self.host, self.port)
