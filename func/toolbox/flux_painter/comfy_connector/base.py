# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/base.py
import json
import os
import random
import time
import urllib.request
import urllib.error

from func.log.default_log import DefaultLog

ANIMA_UNET = "anima_baseV10.safetensors"
ANIMA_CLIP = "anima_baseV10_txt.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"


class TBComfyBase:
    """内置/外部 ComfyUI 连接公共层：健康检查/最小图构造/提交/轮询/取图"""

    def __init__(self, config):
        self.config = config
        self.log = DefaultLog().getLogger()

    def base_url(self) -> str:
        """当前 ComfyUI http 根地址"""
        return self.config.comfy_base()

    def _request(self, method, path, payload=None, timeout=15):
        """请求 ComfyUI REST，返回 (ok, json或None)"""
        url = self.base_url() + path
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", errors="ignore")
                return True, json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            try:
                return False, json.loads(e.read().decode("utf-8", errors="ignore"))
            except Exception:
                return False, {"error": f"http {e.code}"}
        except Exception as e:
            return False, {"error": str(e)}

    def health(self) -> bool:
        """GET /system_stats 探测服务存活"""
        ok, _ = self._request("GET", "/system_stats", timeout=5)
        return ok

    def build_graph(self, positive, negative, width, height, seed=None,
                    prefix="flux", clip_type="qwen_image", steps=None,
                    cfg=None, sampler=None, scheduler=None, model_sampling_shift=None):
        """构造最小原生 API 图（参考 workflow：质量/画师在前、ModelSamplingAuraFlow shift、负向长库）"""
        seed = seed if seed is not None else random.randint(0, 2 ** 63 - 1)
        cfg = cfg if cfg is not None else self.config.sampler_cfg
        steps = steps if steps is not None else self.config.sampler_steps
        sampler = sampler or self.config.sampler_name
        scheduler = scheduler or self.config.sampler_scheduler
        shift = model_sampling_shift if model_sampling_shift is not None else getattr(self.config, "sampler_shift", None)
        graph = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": ANIMA_UNET, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": ANIMA_CLIP, "type": clip_type}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": ANIMA_VAE}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
            "6": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": int(width), "height": int(height), "batch_size": 1}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0],
                                                        "filename_prefix": str(prefix)}},
        }
        if shift:
            graph["10"] = {"class_type": "ModelSamplingAuraFlow",
                           "inputs": {"model": ["1", 0], "shift": float(shift)}}
            graph["7"] = {"class_type": "KSampler",
                          "inputs": {"model": ["10", 0], "positive": ["4", 0], "negative": ["5", 0],
                                     "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": cfg,
                                     "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0}}
        else:
            graph["7"] = {"class_type": "KSampler",
                          "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                                     "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": cfg,
                                     "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0}}
        return graph

    def submit(self, graph, client_id=None):
        """POST /prompt 提交，返回 (ok, prompt_id, 说明)"""
        payload = {"prompt": graph}
        if client_id:
            payload["client_id"] = client_id
        ok, data = self._request("POST", "/prompt", payload=payload, timeout=30)
        if ok and isinstance(data, dict) and data.get("prompt_id"):
            return True, data["prompt_id"], ""
        detail = data if isinstance(data, dict) else {"error": "no data"}
        err = detail.get("error")
        return False, "", (err.get("message") if isinstance(err, dict) else str(detail))[:500]

    def get_history(self, prompt_id):
        """GET /history/{pid}，返回 (存在, entry)"""
        ok, data = self._request("GET", f"/history/{prompt_id}", timeout=10)
        if ok and isinstance(data, dict):
            entry = data.get(prompt_id)
            if entry:
                return True, entry
        return False, None

    def wait(self, prompt_id, timeout=900, on_event=None):
        """轮询直到完成/出错，返回 (ok, images列表, 说明)；兼容 ComfyUI 0.11 status=dict"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            exists, entry = self.get_history(prompt_id)
            if exists and entry:
                status_raw = entry.get("status") or {}
                if isinstance(status_raw, dict):
                    status_str = str(status_raw.get("status_str") or "").lower()
                    messages = status_raw.get("messages") or []
                else:
                    status_str = str(status_raw).lower()
                    messages = entry.get("messages") or []
                outputs = entry.get("outputs") or {}
                images = []
                for node_out in outputs.values():
                    if isinstance(node_out, dict):
                        images.extend(node_out.get("images") or [])
                if status_str == "error":
                    detail = ""
                    for m in messages or []:
                        if isinstance(m, (list, tuple)) and m and m[0] == "execution_error" and len(m) > 1:
                            info = m[1] or {}
                            detail = (str(info.get("exception_message") or "")[:400]
                                      if isinstance(info, dict) else str(info)[:400])
                            break
                    return False, [], detail or "生成失败"
                if images:
                    if on_event:
                        on_event("生成完成")
                    return True, images, ""
                if on_event:
                    on_event("解码中")
            else:
                if on_event:
                    on_event("排队中")
            time.sleep(1.0)
        return False, [], "等待超时"

    def image_path(self, image_entry):
        """把 ComfyUI 图片条目解析为本地绝对路径（output 目录）"""
        filename = image_entry.get("filename", "")
        subfolder = image_entry.get("subfolder", "") or ""
        out_dir = self.config.comfy_output_dir
        return os.path.join(out_dir, subfolder, filename)

    def _download_image(self, image_entry):
        """经 ComfyUI /view 下载图片到 comfy_output_dir（不依赖引擎磁盘布局猜测），
        成功返回本地绝对路径，失败返回 None"""
        filename = str(image_entry.get("filename", "") or "")
        subfolder = str(image_entry.get("subfolder", "") or "")
        typ = str(image_entry.get("type", "") or "output")
        if not filename:
            return None
        import urllib.parse
        import urllib.request
        q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": typ})
        url = self.base_url() + f"/view?{q}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=30) as r:
                blob = r.read()
        except Exception as e:
            self.log.error(f"[flux_painter] 下载图片失败 {filename}: {e}")
            return None
        if not blob or len(blob) < 1000:
            return None
        out_dir = self.config.comfy_output_dir
        if subfolder:
            out_dir = os.path.join(out_dir, subfolder)
        try:
            os.makedirs(out_dir, exist_ok=True)
            dest = os.path.join(out_dir, filename)
            with open(dest, "wb") as f:
                f.write(blob)
            return dest if os.path.isfile(dest) else None
        except Exception:
            return None

    def images_local(self, images):
        """返回图片条目对应的本地绝对路径：优先已有文件，缺失则经 /view 下载"""
        paths = []
        for entry in images or []:
            if not isinstance(entry, dict):
                continue
            p = self.image_path(entry)
            if p and os.path.isfile(p):
                paths.append(p)
                continue
            got = self._download_image(entry)
            if got:
                paths.append(got)
        return paths
