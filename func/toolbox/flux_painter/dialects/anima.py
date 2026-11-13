# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/dialects/anima.py
# Anima（Cosmos Predict2 系）工作流方言：fast 单段采样 / pro 四段全流程
#
# 模型三件套固定：UNET + 独立文本编码器 + qwen_image VAE
# 采样：ModelSamplingAuraFlow(shift) 之后接 KSampler，LoRA 只改 UNET（LoraLoaderModelOnly）

import random

# 家族常量：底模被删除/改名时仍能兜底运行
ANIMA_UNET = "anima_baseV10.safetensors"
ANIMA_CLIP = "anima_baseV10_txt.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"

# CLIPLoader 的 type 候选：引擎版本不同认的枚举不一样，按顺序试
ANIMA_CLIP_TYPES = ("qwen_image", "stable_diffusion", "flux2")

# pro 档位依赖的第三方节点（缺失自动降级 fast）
ANIMA_PRO_NODES = ("UltimateSDUpscaleNoUpscale", "FaceDetailer",
                   "UltralyticsDetectorProvider", "SAMLoader",
                   "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale")


class AnimaDialect:
    """Anima 方言：两档（fast=单段采样 / pro=04 基础→05 放大→06 分块→07 细化）"""

    family = "anima"
    label = "Anima（喵喵 / baseV10）"
    # 档位语义：fast=单段采样，pro=四段全流程
    quality_modes = ("fast", "pro")
    quality_labels = {"fast": "快速（单段采样）", "pro": "清晰（放大+分块+细化）"}

    unet_default = ANIMA_UNET
    clip_default = ANIMA_CLIP
    vae_default = ANIMA_VAE
    clip_types = ANIMA_CLIP_TYPES
    pro_nodes = ANIMA_PRO_NODES

    # 提示词形态：tag 锚点 + 自然语言镜头段（cinema）
    prompt_style = "anima_tags"

    def unet(self, conn):
        """底模文件名：配置优先，缺省回退家族常量"""
        return str(getattr(conn.config, "unet_model", "") or "").strip() or self.unet_default

    def clip(self, conn):
        """取当前家族的文本编码器文件名。"""
        return ANIMA_CLIP

    def vae(self, conn):
        """取当前家族的 VAE 文件名。"""
        return ANIMA_VAE

    def loras(self, conn):
        """Anima 的 LoRA 链（config.yml flux_painter.lora_chain）"""
        return [x for x in (getattr(conn.config, "lora_chain", []) or []) if x.get("name")]

    # ==================== 快速档：单段采样 ====================
    def build_graph(self, conn, positive, negative, width, height, seed=None,
                    prefix="flux", clip_type=None, steps=None,
                    cfg=None, sampler=None, scheduler=None, model_sampling_shift=None):
        """快速档最小图：UNET → LoRA 链 → shift → KSampler → 解码 → 保存"""
        seed = seed if seed is not None else random.randint(0, 2 ** 63 - 1)
        # 尺寸对齐 16 的倍数：Anima(Cosmos Predict2) 要求 latent 的 H/W 能被 spatial_patch_size=2 整除，
        # 即像素尺寸须为 16 的倍数（1080 之类会产生 135 奇数 latent → KSampler 断言失败）
        width, height = conn._align16(width), conn._align16(height)
        cfg = cfg if cfg is not None else conn.config.sampler_cfg
        steps = steps if steps is not None else conn.config.sampler_steps
        sampler = sampler or conn.config.sampler_name
        scheduler = scheduler or conn.config.sampler_scheduler
        shift = (model_sampling_shift if model_sampling_shift is not None
                 else getattr(conn.config, "sampler_shift", None))
        graph = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": self.unet(conn), "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": self.clip(conn),
                             "type": clip_type or self.clip_types[0]}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": self.vae(conn)}},
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
                                     "latent_image": ["6", 0], "seed": seed, "steps": steps,
                                     "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler,
                                     "denoise": 1.0}}
        else:
            graph["7"] = {"class_type": "KSampler",
                          "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                                     "latent_image": ["6", 0], "seed": seed, "steps": steps,
                                     "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler,
                                     "denoise": 1.0}}
        # ===== LoRA 链：叠加在 UNET 之后、shift/KSampler 之前 =====
        # anima 为 UNET+独立CLIP 架构，LoRA 只改 UNET → LoraLoaderModelOnly 即可
        model_src = ["1", 0]
        for _i, _lora in enumerate(self.loras(conn), start=11):
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

    # ==================== 清晰档：04+05+06+07 全流程 ====================
    def build_pro_graph(self, conn, positive, negative, width, height, prefix="flux",
                        clip_type=None, seed=None, params=None):
        """Pro 全流程织图：04 基础采样 → 05 模型放大 → 06 USDU 分块重绘 → 07 FaceDetailer×3。

        - 参数全部**按名称注入**（不依赖 UI widgets 下标，也不需要 Easy-Use 的变量中继）
        - params = config.pro 参数组（缺项已由 TBFluxPainterConfig 兜底为 pro 原值）
        - 组开关：hires.enabled / usdu.enabled / detailers.<hand|face|eye>.enabled
        """
        seed = seed if seed is not None else random.randint(0, 2 ** 63 - 1)
        width, height = conn._align16(width), conn._align16(height)
        p = params or {}
        hires = p.get("hires") or {}
        usdu = p.get("usdu") or {}
        dets = p.get("detailers") or {}
        sam_cfg = p.get("sam") or {}
        base_cfg = float(p.get("base_cfg", 4.0))
        base_steps = int(p.get("base_steps", 30))
        scale = float(hires.get("scale", 2.0) or 2.0)
        # 放大后的目标尺寸同样对齐 16 的倍数（scale 非整数时也要保证，否则下游会出奇数 latent）
        out_w, out_h = conn._align16(int(width) * scale), conn._align16(int(height) * scale)

        g = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": self.unet(conn), "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": self.clip(conn),
                             "type": clip_type or self.clip_types[0]}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": self.vae(conn)}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
            "6": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": int(width), "height": int(height), "batch_size": 1}},
        }

        # ---- LoRA 链（叠加在 UNET 之后）----
        model_src = ["1", 0]
        for i, lora in enumerate(self.loras(conn), start=200):
            g[str(i)] = {"class_type": "LoraLoaderModelOnly",
                         "inputs": {"lora_name": str(lora["name"]),
                                    "strength_model": float(lora.get("strength", 0.8)),
                                    "model": model_src}}
            model_src = [str(i), 0]
        shift = getattr(conn.config, "sampler_shift", None)
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
                             "cfg": base_cfg, "sampler_name": conn.config.sampler_name,
                             "scheduler": conn.config.sampler_scheduler, "denoise": 1.0}}
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
                    "sampler_name": conn.config.sampler_name,
                    "scheduler": conn.config.sampler_scheduler,
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
            _node["inputs"] = conn.conform_inputs(_node["class_type"], _node["inputs"])
        return g
