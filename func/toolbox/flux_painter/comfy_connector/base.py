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

    @staticmethod
    def _align16(v):
        """像素尺寸对齐到 16 的倍数（Anima/Cosmos 的 latent 需被 spatial_patch_size=2 整除）"""
        v = int(v)
        return v - (v % 16)

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
        # 尺寸对齐 16 的倍数：Anima(Cosmos Predict2) 要求 latent 的 H/W 能被 spatial_patch_size=2 整除，
        # 即像素尺寸须为 16 的倍数（1080 之类会产生 135 奇数 latent → KSampler 断言失败）
        width, height = self._align16(width), self._align16(height)
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
        # ===== LoRA 链（默认两个，可配可空）：叠加在 UNET 之后、shift/KSampler 之前 =====
        # anima 为 UNET+独立CLIP 架构，LoRA 只改 UNET → LoraLoaderModelOnly 即可
        model_src = ["1", 0]
        for _i, _lora in enumerate(getattr(self.config, "lora_chain", []) or [], start=11):
            graph[str(_i)] = {"class_type": "LoraLoaderModelOnly",
                              "inputs": {"lora_name": str(_lora["name"]),
                                         "strength_model": float(_lora.get("strength", 0.8)),
                                         "model": model_src}}
            model_src = [str(_i), 0]
        if model_src != ["1", 0]:
            # 有 LoRA 时：shift 输入链尾；无 shift 则 KSampler 直接接链尾
            if shift:
                graph["10"]["inputs"]["model"] = model_src
            else:
                graph["7"]["inputs"]["model"] = model_src
        return graph

    # ==================== Pro 全流程（04+05+06+07） ====================
    # pro 档位所需节点（第三方插件提供），缺失则自动降级快速档
    PRO_REQUIRED_NODES = ("UltimateSDUpscaleNoUpscale", "FaceDetailer",
                          "UltralyticsDetectorProvider", "SAMLoader",
                          "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale")

    def object_info(self, timeout=20):
        """GET /object_info（进程内缓存）；失败返回 {}"""
        cached = getattr(self, "_obj_info", None)
        if cached:
            return cached
        ok, data = self._request("GET", "/object_info", timeout=timeout)
        info = data if (ok and isinstance(data, dict)) else {}
        if info:
            self._obj_info = info
        return info

    def missing_pro_nodes(self):
        """pro 档位所需节点中，引擎未注册的清单（返回 [] 表示就绪）"""
        info = self.object_info()
        missing = ([n for n in self.PRO_REQUIRED_NODES if n not in info]
                   if info else list(self.PRO_REQUIRED_NODES))
        if missing and info:
            # 缓存可能过期（引擎刚重启/刚加载插件）：强制刷新一次再判定
            self._obj_info = None
            info2 = self.object_info()
            if info2:
                missing = [n for n in self.PRO_REQUIRED_NODES if n not in info2]
        return missing

    def conform_inputs(self, class_type, inputs):
        """按引擎 /object_info 的真实定义对齐输入：

        - 剔除该节点不认识的键（跨插件版本重命名/新增参数时避免 validation 失败）
        - 为缺失且带默认值的 required 参数补齐默认值（如 USDU 的 batch_size）
        - object_info 不可用时原样返回（不破坏离线构造）
        """
        info = self.object_info()
        if not info:
            return inputs
        spec = (info.get(class_type) or {}).get("input") or {}
        req = spec.get("required") or {}
        opt = spec.get("optional") or {}
        if not req and not opt:
            return inputs
        known = set(req) | set(opt)
        out = {k: v for k, v in (inputs or {}).items() if k in known}
        for k, v in req.items():
            if k in out:
                continue
            meta = (v[1] if isinstance(v, (list, tuple)) and len(v) > 1
                    and isinstance(v[1], dict) else {})
            if "default" in meta:
                out[k] = meta["default"]
        return out

    def build_pro_graph(self, positive, negative, width, height, prefix="flux",
                        clip_type="qwen_image", seed=None, params=None):
        """Pro 全流程织图：04 基础采样 → 05 模型放大 → 06 USDU 分块重绘 → 07 FaceDetailer×3。

        - 参数全部**按名称注入**（不依赖 UI widgets 下标，也不需要 Easy-Use 的变量中继）
        - params = config.pro 参数组（缺项已由 TBFluxPainterConfig 兜底为 pro 原值）
        - 组开关：hires.enabled / usdu.enabled / detailers.<hand|face|eye>.enabled
        """
        seed = seed if seed is not None else random.randint(0, 2 ** 63 - 1)
        width, height = self._align16(width), self._align16(height)
        p = params or {}
        hires = p.get("hires") or {}
        usdu = p.get("usdu") or {}
        dets = p.get("detailers") or {}
        sam_cfg = p.get("sam") or {}
        base_cfg = float(p.get("base_cfg", 4.0))
        base_steps = int(p.get("base_steps", 30))
        scale = float(hires.get("scale", 2.0) or 2.0)
        # 放大后的目标尺寸同样对齐 16 的倍数（scale 非整数时也要保证，否则下游会出奇数 latent）
        out_w, out_h = self._align16(int(width) * scale), self._align16(int(height) * scale)

        g = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": ANIMA_UNET, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": ANIMA_CLIP, "type": clip_type}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": ANIMA_VAE}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
            "6": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": int(width), "height": int(height), "batch_size": 1}},
        }

        # ---- LoRA 链（叠加在 UNET 之后）----
        model_src = ["1", 0]
        for i, lora in enumerate(getattr(self.config, "lora_chain", []) or [], start=30):
            g[str(i)] = {"class_type": "LoraLoaderModelOnly",
                         "inputs": {"lora_name": str(lora["name"]),
                                    "strength_model": float(lora.get("strength", 0.8)),
                                    "model": model_src}}
            model_src = [str(i), 0]
        shift = getattr(self.config, "sampler_shift", None)
        if shift:
            g["10"] = {"class_type": "ModelSamplingAuraFlow",
                       "inputs": {"model": model_src, "shift": float(shift)}}
            model_ref = ["10", 0]
        else:
            model_ref = model_src

        # ---- 04 基础采样（pro：cfg 4 / 30 步 / denoise 1.0）----
        g["7"] = {"class_type": "KSampler",
                  "inputs": {"model": model_ref, "positive": ["4", 0], "negative": ["5", 0],
                             "latent_image": ["6", 0], "seed": seed, "steps": base_steps,
                             "cfg": base_cfg, "sampler_name": self.config.sampler_name,
                             "scheduler": self.config.sampler_scheduler, "denoise": 1.0}}
        g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}}
        image_src = ["8", 0]

        # ---- 05 高清预处理：4x 模型放大 → ImageScale 缩到 画布×scale ----
        if hires.get("enabled", True) and hires.get("upscale_model"):
            g["11"] = {"class_type": "UpscaleModelLoader",
                       "inputs": {"model_name": str(hires["upscale_model"])}}
            g["12"] = {"class_type": "ImageUpscaleWithModel",
                       "inputs": {"upscale_model": ["11", 0], "image": image_src}}
            g["13"] = {"class_type": "ImageScale",
                       "inputs": {"image": ["12", 0],
                                  "upscale_method": str(hires.get("resize", "lanczos")),
                                  "width": out_w, "height": out_h, "crop": "disabled"}}
            image_src = ["13", 0]

        # ---- 06 USDU 分块重绘（NoUpscale：尺寸不变，只补细节）----
        if usdu.get("enabled", True):
            g["15"] = {"class_type": "UltimateSDUpscaleNoUpscale",
                       "inputs": {
                           "upscaled_image": image_src, "model": model_ref,
                           "positive": ["4", 0], "negative": ["5", 0], "vae": ["3", 0],
                           "seed": seed, "steps": int(usdu.get("steps", 20)),
                           "cfg": float(usdu.get("cfg", 8.0)),
                           "sampler_name": str(usdu.get("sampler", "euler")),
                           "scheduler": str(usdu.get("scheduler", "simple")),
                           "denoise": float(usdu.get("denoise", 0.15)),
                           "mode_type": str(usdu.get("mode_type", "Linear")),
                           "tile_width": int(usdu.get("tile_width", 512)),
                           "tile_height": int(usdu.get("tile_height", 512)),
                           "mask_blur": int(usdu.get("mask_blur", 32)),
                           "tile_padding": int(usdu.get("tile_padding", 256)),
                           "seam_fix_mode": str(usdu.get("seam_fix_mode", "None")),
                           "seam_fix_denoise": float(usdu.get("seam_fix_denoise", 1.0)),
                           "seam_fix_width": int(usdu.get("seam_fix_width", 64)),
                           "seam_fix_mask_blur": int(usdu.get("seam_fix_mask_blur", 8)),
                           "seam_fix_padding": int(usdu.get("seam_fix_padding", 16)),
                           "force_uniform_tiles": bool(usdu.get("force_uniform_tiles", True)),
                           "tiled_decode": bool(usdu.get("tiled_decode", False)),
                           "batch_size": int(usdu.get("batch_size", 1)),
                       }}
            image_src = ["15", 0]

        # ---- 07 局部细化：检测器 / SAM / 局部提示词 / 三段 FaceDetailer（链式）----
        if any((dets.get(k) or {}).get("enabled", True) for k in ("hand", "face", "eye")):
            g["20"] = {"class_type": "UltralyticsDetectorProvider",
                       "inputs": {"model_name": str((dets.get("hand") or {}).get("detector")
                                                    or "bbox/hand_yolov8s.pt")}}
            g["21"] = {"class_type": "UltralyticsDetectorProvider",
                       "inputs": {"model_name": str((dets.get("face") or {}).get("detector")
                                                    or "bbox/face_yolov8m.pt")}}
            if p.get("sam_model"):
                # 注意：SAMLoader 的输入名以引擎定义为准 = model_name（不是 sam_model_name）
                g["22"] = {"class_type": "SAMLoader",
                           "inputs": {"model_name": str(p["sam_model"]),
                                      "device_mode": "AUTO"}}
            g["23"] = {"class_type": "CLIPTextEncode",
                       "inputs": {"text": str(p.get("pos_hand") or "hand"), "clip": ["2", 0]}}
            g["24"] = {"class_type": "CLIPTextEncode",
                       "inputs": {"text": str(p.get("neg_hand") or negative), "clip": ["2", 0]}}
            cur = image_src
            idx = 40
            plan = (("hand", "20", "23", "24"),   # 手部：局部正/负词
                    ("face", "21", "4", "5"),     # 面部：主正/负词
                    ("eye", "21", "4", "5"))      # 眼脸：主正/负词（face 检测器）
            for name, det_id, pos_id, neg_id in plan:
                d = dets.get(name) or {}
                if not d.get("enabled", True):
                    continue
                inputs = {
                    "image": cur, "model": model_ref, "clip": ["2", 0], "vae": ["3", 0],
                    "positive": [pos_id, 0], "negative": [neg_id, 0],
                    "bbox_detector": [det_id, 0],
                    "guide_size": float(d.get("guide_size", 768)),
                    "guide_size_for": True,
                    "max_size": float(d.get("max_size", 1280)),
                    "seed": seed,
                    "steps": int(d.get("steps", 14)),
                    "cfg": float(d.get("cfg", 3.0)),
                    "sampler_name": self.config.sampler_name,
                    "scheduler": self.config.sampler_scheduler,
                    "denoise": float(d.get("denoise", 0.25)),
                    "feather": int(d.get("feather", 8)),
                    "noise_mask": bool(d.get("noise_mask", True)),
                    "force_inpaint": bool(d.get("force_inpaint", False)),
                    "bbox_threshold": float(d.get("bbox_threshold", 0.35)),
                    "bbox_dilation": int(d.get("bbox_dilation", 16)),
                    "bbox_crop_factor": float(d.get("bbox_crop_factor", 2.5)),
                    "sam_detection_hint": str(sam_cfg.get("sam_detection_hint", "center-1")),
                    "sam_dilation": int(sam_cfg.get("sam_dilation", 0)),
                    "sam_threshold": float(sam_cfg.get("sam_threshold", 0.93)),
                    "sam_bbox_expansion": int(sam_cfg.get("sam_bbox_expansion", 0)),
                    "sam_mask_hint_threshold": float(sam_cfg.get("sam_mask_hint_threshold", 0.7)),
                    "sam_mask_hint_use_negative": str(sam_cfg.get("sam_mask_hint_use_negative",
                                                                  "False")),
                    "drop_size": int(sam_cfg.get("drop_size", 10)),
                    "wildcard": "",
                    "cycle": int(sam_cfg.get("cycle", 1)),
                    "inpaint_model": False,
                    "noise_mask_feather": int(sam_cfg.get("noise_mask_feather", 20)),
                }
                if p.get("sam_model"):
                    inputs["sam_model_opt"] = ["22", 0]
                g[str(idx)] = {"class_type": "FaceDetailer", "inputs": inputs}
                cur = [str(idx), 0]
                idx += 1
            image_src = cur

        g["99"] = {"class_type": "SaveImage",
                   "inputs": {"images": image_src, "filename_prefix": str(prefix)}}
        # 按引擎真实节点定义对齐：剔除未知输入 + 为缺失的 required 补默认值（跨插件版本兜底）
        for _nid, _node in g.items():
            _node["inputs"] = self.conform_inputs(_node["class_type"], _node["inputs"])
        return g

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

    # ==================== 实时进度（WebSocket） ====================
    # 按 class_type 映射阶段与权重（不依赖节点 id，fast / pro 通用）
    STAGE_WEIGHTS = {
        "KSampler": (25, "基础采样"),
        "ImageUpscaleWithModel": (5, "高清放大"),
        "UltimateSDUpscale": (40, "分块重绘"),
        "UltimateSDUpscaleNoUpscale": (40, "分块重绘"),
        "FaceDetailer": (24, "局部细化"),
        "VAEDecode": (2, "解码"),
        "SaveImage": (2, "保存"),
    }
    _DEFAULT_STAGE_WEIGHT = 1

    def stage_plan(self, graph):
        """按图统计各阶段权重与执行次数（用于进度百分比 / k/n 文案）"""
        plan = {}
        total = 0
        for node in (graph or {}).values():
            ct = node.get("class_type") if isinstance(node, dict) else None
            if not ct:
                continue
            w, name = self.STAGE_WEIGHTS.get(ct, (self._DEFAULT_STAGE_WEIGHT, ct))
            item = plan.setdefault(name, {"weight": w, "count": 0})
            item["count"] += 1
            total += w
        return plan, max(total, 1)

    def watch(self, prompt_id, graph=None, timeout=900, on_progress=None, client_id=None):
        """订阅引擎 WebSocket 实时进度并等待完成；连接失败自动回退 wait() 轮询。

        on_progress(dict) 字段：
            stage   阶段文案（多次执行的阶段带 k/n，如「分块重绘 6/16」「局部细化 2/3」）
            percent 0~100
            step    当前节点的采样步进（如 "12/20"）
            blocks  [已完成, 总数]（多次执行的阶段才有）
            elapsed 已用秒数 / eta 预计总秒数（外部补充）
        返回 (ok, images, 说明) —— 与 wait() 同签名
        """
        try:
            import websocket  # websocket-client
        except Exception:
            self.log.warning("[flux_painter] 未安装 websocket-client，回退轮询进度")
            websocket = None

        t0 = time.time()
        plan, total_w = self.stage_plan(graph)
        id2class = {str(k): (v.get("class_type") if isinstance(v, dict) else "")
                    for k, v in (graph or {}).items()}
        counts, done_w, cur_node, cur_step = {}, 0, None, ""
        cur_frac = 0.0            # 当前节点内部步进比例 0~1（阶段内平滑推进用）
        err_detail, last_emit = "", 0.0

        def _cur_weight():
            """当前正在执行的节点的权重"""
            ct = id2class.get(cur_node or "") or ""
            return self.STAGE_WEIGHTS.get(ct, (self._DEFAULT_STAGE_WEIGHT, "运行中"))[0]

        def _percent():
            # 已完成阶段权重 + 当前阶段按步进插值：采样/分块途中也能连续走动，
            # 否则一次长采样期间恒为 0，画板看起来只有 0 和 100
            return min(99, int((done_w + _cur_weight() * cur_frac) * 100 / total_w))

        def emit(force=False):
            nonlocal last_emit
            if not on_progress:
                return
            now = time.time()
            if not force and (now - last_emit) < 0.4:
                return
            last_emit = now
            ct = id2class.get(cur_node or "") or ""
            _w, stage = self.STAGE_WEIGHTS.get(ct, (self._DEFAULT_STAGE_WEIGHT, "运行中"))
            total_cnt = int((plan.get(stage) or {}).get("count", 1) or 1)
            cnt = int(counts.get(stage, 0))
            ev = {"stage": (f"{stage} {cnt + 1}/{total_cnt}" if total_cnt > 1 and cnt < total_cnt
                            else stage),
                  "percent": _percent(), "step": cur_step or "",
                  "elapsed": int(now - t0)}
            if total_cnt > 1:
                ev["blocks"] = [cnt, total_cnt]
            on_progress(ev)

        if websocket is not None:
            cid = client_id or f"fluxpaint_{int(t0)}"
            url = f"ws://{self.config.comfy_host}:{self.config.comfy_port}/ws?clientId={cid}"
            ws = None
            try:
                ws = websocket.create_connection(url, timeout=15)
                ws.settimeout(5)
            except Exception as e:
                self.log.warning(f"[flux_painter] WS 连接失败({e})，回退轮询进度")
                ws = None
            if ws is not None:
                if on_progress:
                    on_progress({"stage": "已入队", "percent": 0, "step": "", "elapsed": 0})
                deadline = t0 + timeout
                try:
                    while time.time() < deadline:
                        try:
                            raw = ws.recv()
                        except Exception as e:
                            if "Timeout" in type(e).__name__:
                                emit()          # 心跳：长任务期间也持续刷新
                                continue
                            self.log.warning(f"[flux_painter] WS 断开({type(e).__name__})，转轮询")
                            break
                        if not raw:
                            continue
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        mtype = msg.get("type")
                        data = msg.get("data") or {}
                        pid = data.get("prompt_id")
                        if pid and pid != prompt_id:
                            continue
                        if mtype == "progress":
                            v, mx = data.get("value"), data.get("max")
                            cur_step = f"{v}/{mx}" if v is not None else ""
                            try:
                                cur_frac = (max(0.0, min(1.0, float(v) / float(mx)))
                                            if mx else 0.0)
                            except Exception:
                                cur_frac = 0.0
                            emit()
                        elif mtype == "executing":
                            node = data.get("node")
                            if node is None:
                                break                    # 队列执行结束
                            cur_node = str(node)
                            cur_step = ""
                            cur_frac = 0.0
                            emit(force=True)
                        elif mtype == "executed":
                            node = str(data.get("node") or "")
                            ct = id2class.get(node) or ""
                            _w, stage = self.STAGE_WEIGHTS.get(ct, (self._DEFAULT_STAGE_WEIGHT, ct))
                            counts[stage] = counts.get(stage, 0) + 1
                            done_w += _w
                            cur_frac = 0.0
                            emit(force=True)
                        elif mtype == "execution_error":
                            err_detail = str(data.get("exception_message") or "execution_error")[:400]
                        elif mtype == "execution_success":
                            break
                finally:
                    try:
                        ws.close()
                    except Exception:
                        pass

        # 取结果（WS 结束或回退后，统一从 history 取，保证与 wait() 结果一致）
        exists, entry = self.get_history(prompt_id)
        if exists and entry:
            status_raw = entry.get("status") or {}
            if isinstance(status_raw, dict):
                status_str = str(status_raw.get("status_str") or "").lower()
                messages = status_raw.get("messages") or []
            else:
                status_str = str(status_raw).lower()
                messages = entry.get("messages") or []
            images = []
            for node_out in (entry.get("outputs") or {}).values():
                if isinstance(node_out, dict):
                    images.extend(node_out.get("images") or [])
            if status_str == "error":
                detail = err_detail
                for m in messages or []:
                    if isinstance(m, (list, tuple)) and m and m[0] == "execution_error" and len(m) > 1:
                        info = m[1] or {}
                        detail = str(info.get("exception_message") or detail)[:400]
                        break
                return False, [], detail or "生成失败"
            if images:
                if on_progress:
                    on_progress({"stage": "生成完成", "percent": 100, "step": "",
                                 "elapsed": int(time.time() - t0)})
                return True, images, ""
        # 结果还没落库/WS 提前断开：交给轮询兜底（与旧逻辑一致）
        if on_progress:
            on_progress({"stage": "解码中", "percent": 99, "elapsed": int(time.time() - t0)})
        return self.wait(prompt_id, timeout=180)

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
