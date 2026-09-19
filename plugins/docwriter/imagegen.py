# -*- coding: utf-8 -*-
"""生图端口：硅基流动 SiliconFlow（Kwai-Kolors/Kolors）。

* 接口：POST {base_url}/images/generations（OpenAI 风格）
* 请求：{"model","prompt","negative_prompt","image_size","batch_size",
          "num_inference_steps","guidance_scale","seed"}
* 响应：{"images":[{"url":"..."}]}（也兼容 b64_json）
* Kolors 原生支持中文提示词，适合中文文档配图；产物落 assets/ 并记录来源

失败一律返回 ""（调用方自行降级），不抛异常打断出稿流程。
"""

import base64
import os
import time

import requests

DEFAULT_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "Kwai-Kolors/Kolors"

# 尺寸由调用方（模型）按用途决定，不写进配置；
# 优先使用模型原生训练分辨率（实测最干净），非原生比例放末位兜底
ASPECT_SIZES = {
    "square": ["1024x1024"],
    "wide": ["1024x768", "1280x720", "1024x1024"],
    "tall": ["768x1024", "960x1280", "1024x1024"],
}
FALLBACK_SIZE = "1024x1024"
SIZES = ["1024x1024", "960x1280", "768x1024", "720x1440", "1280x720", "1024x768"]

ASPECT_HINT = ("square 方图(1:1，图标/示意图) / wide 横图(16:9，正文配图、图表旁、封面) / "
               "tall 竖图(3:4，人物、手机界面、竖版长图)")

# 默认负向词：画质向 + 内容向（噪点主要由画质向标签压制）
DEFAULT_NEGATIVE = (
    "worst quality, low quality, lowres, jpeg artifacts, grain, noise, film grain, "
    "oversaturated, overexposed, underexposed, chromatic aberration, blurry, out of focus, "
    "水印, 文字, 署名, 签名, logo, 印章, 变形, 畸形, 多余手指, 残缺, 双头, 多肢, "
    "watermark, text, signature, deformed, bad anatomy, extra limbs"
)

STYLE_SUFFIX = "，高清细节，构图干净，无文字"


class ImageGen:
    def __init__(self, config):
        """生图端口（独立配置，与 LLM 端口同构）"""
        cfg = getattr(config, "image", None) or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.provider = str(cfg.get("provider", "siliconflow")).lower()
        self.api_key = str(cfg.get("api_key") or "")
        self.base_url = str(cfg.get("base_url") or DEFAULT_BASE).rstrip("/")
        self.model = str(cfg.get("model") or DEFAULT_MODEL)
        self.steps = int(cfg.get("steps", 20) or 20)
        self.guidance = float(cfg.get("guidance", 7.5) or 7.5)
        self.negative = str(cfg.get("negative_prompt") or DEFAULT_NEGATIVE)
        self.timeout = int(cfg.get("timeout", 180) or 180)
        self.style = bool(cfg.get("style_suffix", True))
        self.retry = int(cfg.get("retry", 2) or 0)              # 429 重试次数
        self.retry_wait = int(cfg.get("retry_wait", 20) or 20)   # 首次退避秒数
        self._ok_size = {}          # 画幅 -> 实测可用尺寸（本次运行内记忆）
        self.last_error = ""
        self.last_url = ""
        self.last_size = ""

    # ---------- 状态 ----------
    def available(self):
        """端口是否可用"""
        if not self.enabled:
            self.last_error = "生图未启用"
            return False
        if not self.api_key:
            self.last_error = "未配置生图 API Key（硅基流动）"
            return False
        return True

    def probe(self):
        """连通性探测：返回 (ok, 说明)。key 无效/未开通会在这里暴露。"""
        if not self.available():
            return False, self.last_error
        t0 = time.time()
        try:
            resp = requests.post(
                f"{self.base_url}/images/generations",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.model, "prompt": "一朵白色的花", "image_size": FALLBACK_SIZE,
                      "batch_size": 1, "num_inference_steps": min(self.steps, 10)},
                timeout=60)
        except Exception as e:
            self.last_error = f"请求失败：{e}"
            return False, self.last_error
        cost = round(time.time() - t0, 1)
        if resp.status_code == 200:
            try:
                url = (resp.json().get("images") or [{}])[0].get("url", "")
            except Exception:
                url = ""
            return True, f"可用（{cost}s）{'，返回图片链接' if url else ''}"
        self.last_error = f"HTTP {resp.status_code}: {resp.text[:180]}"
        return False, self.last_error

    # ---------- 生成 ----------
    def generate(self, prompt, out_dir, filename=None, negative="", aspect=None, size=None,
                 seed=None):
        """生成一张图并落盘，返回文件路径（失败返回 ""）

        aspect：square / wide / tall，由调用方按用途决定；size 可直接指定（优先级最高）。
        逐个候选尺寸尝试，成功一次即记住该画幅的可用尺寸，后续直接复用。
        """
        if not self.available():
            return ""
        os.makedirs(out_dir, exist_ok=True)
        text = self._compose_prompt(prompt)
        key = str(aspect or "square").lower()
        candidates = []
        if size:
            candidates.append(str(size))
        known = self._ok_size.get(key)
        if known:
            candidates.append(known)
        candidates += ASPECT_SIZES.get(key, ASPECT_SIZES["square"])
        candidates.append(FALLBACK_SIZE)
        tried = set()
        for sz in candidates:
            if not sz or sz in tried:
                continue
            tried.add(sz)
            data = self._request(text, negative, sz, seed)
            if data:
                path = self._save(data, out_dir, filename)
                if path:
                    self._ok_size[key] = sz
                    self.last_size = sz
                    return path
        return ""

    def _compose_prompt(self, prompt):
        """补风格词（可用 image.style_suffix 关闭）"""
        text = str(prompt or "").strip()
        if not text:
            return ""
        if self.style and STYLE_SUFFIX.strip("，") not in text:
            return text + STYLE_SUFFIX
        return text

    def _request(self, prompt, negative, size, seed):
        """调用一次接口，返回图片二进制或 base64 字符串

        硅基流动对生图有 IPM（每分钟张数）限制，超了会返回 429/50604，
        这里做指数退避重试（20s / 40s），避免批量配图时直接失败。
        """
        if not prompt:
            self.last_error = "提示词为空"
            return b""
        payload = {"model": self.model, "prompt": prompt,
                   "negative_prompt": negative or self.negative,
                   "batch_size": 1, "num_inference_steps": self.steps,
                   "guidance_scale": self.guidance}
        if size:
            payload["image_size"] = size
        if seed is not None:
            payload["seed"] = int(seed)
        for attempt in range(self.retry + 1):
            try:
                resp = requests.post(
                    f"{self.base_url}/images/generations",
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    json=payload, timeout=self.timeout)
            except Exception as e:
                self.last_error = f"请求失败：{e}"
                return b""
            if resp.status_code == 429 and attempt < self.retry:
                wait = self.retry_wait * (attempt + 1)
                self.last_error = f"生图频率限制（429），{wait}s 后重试"
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                self.last_error = f"HTTP {resp.status_code}: {resp.text[:180]}"
                return b""
            try:
                item = (resp.json().get("images") or [{}])[0]
            except Exception as e:
                self.last_error = f"响应解析失败：{e}"
                return b""
            if item.get("b64_json"):
                return "b64:" + item["b64_json"]
            url = item.get("url") or ""
            if not url:
                self.last_error = "响应中没有图片地址"
                return b""
            self.last_url = url
            try:
                r = requests.get(url, timeout=self.timeout)
                r.raise_for_status()
                return r.content
            except Exception as e:
                self.last_error = f"下载生成图失败：{e}"
                return b""
        return b""

    def _save(self, data, out_dir, filename=None):
        """落盘并用 Pillow 校验（按真实格式命名：png/jpg/webp）"""
        import hashlib

        from PIL import Image

        if isinstance(data, str) and data.startswith("b64:"):
            try:
                raw = base64.b64decode(data[4:])
            except Exception as e:
                self.last_error = f"base64 解码失败：{e}"
                return ""
        else:
            raw = data
        if not raw:
            return ""
        name = str(filename or "").strip() or f"gen_{int(time.time())}"
        name = "".join(c for c in name if c not in '\\/:*?"<>|')[:40]
        tmp = os.path.join(out_dir, f".tmp_{name}_{int(time.time() * 1000)}")
        try:
            with open(tmp, "wb") as f:
                f.write(raw)
            with Image.open(tmp) as im:
                fmt = (im.format or "PNG").upper()
                im.verify()
            ext = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(fmt, ".png")
            tag = hashlib.md5(raw).hexdigest()[:8]
            final = os.path.join(out_dir, f"{name}_{tag}{ext}")
            os.replace(tmp, final)
            return final
        except Exception as e:
            self.last_error = f"图片写入/校验失败：{e}"
            try:
                os.remove(tmp)
            except Exception:
                pass
            return ""
