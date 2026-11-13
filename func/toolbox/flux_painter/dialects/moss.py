# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/dialects/moss.py
# MOSS-Image（OpenMOSS 5B DiT）工作流方言
#
# 与 anima 的差别（这是两个完全不同的架构，节点不通用）：
#   - latent：EmptyFlux2LatentImage（不是 EmptyLatentImage）
#   - 文本编码器：Qwen3.5-9B，CLIPLoader type 必须是 moss_image
#   - VAE：flux2-vae（FLUX.2 系解码器）
#   - 采样：ModelSamplingAuraFlow(shift 5, sampling=flow) + Euler / sgm_uniform
#   - 两档不是"放大/细化"，而是蒸馏档位：
#       fast = 8 步 DMD LoRA（cfg 1，负向词不参与）
#       pro  = 50 步原版 SFT（cfg 3）+ SkipLayerGuidanceDiTSimple 跳层 22
#   参考图生图仍走 base.with_init_image（两张图都用 KSampler=7 / VAE=3 的约定）

import random

MOSS_UNET = "moss_image_sft_bf16.safetensors"
# 官方打包 4bit 量化版（8GB 显存推荐）；显存充足可换 qwen3.5_9b_bf16 / int8_convrot
MOSS_CLIP = "qwen3.5_9b_w4a8_gptq.safetensors"
MOSS_VAE = "flux2-vae.safetensors"
MOSS_DMD_LORA = "MOSS-Image-SFT-8-steps-dmd.safetensors"

# MOSS 只有一种文本编码器类型
MOSS_CLIP_TYPES = ("moss_image",)

# 两档都是核心节点，无第三方依赖（pro 只需 core 的 SLG 节点）
MOSS_PRO_NODES = ("EmptyFlux2LatentImage", "ModelSamplingAuraFlow")

# 官方推荐负面词（50 步 cfg 3 时才生效；DMD 档 cfg=1 负向不参与）
MOSS_DEFAULT_NEGATIVE = "nsfw, worst quality, bad anatomy, watermark, jpeg artifact"
MOSS_DEFAULT_QUALITY = "best quality, highres"


class MossDialect:
    """MOSS 方言：fast=8步DMD / pro=50步SLG"""

    family = "moss"
    label = "MOSS-Image（SFT）"
    quality_modes = ("fast", "pro")
    quality_labels = {"fast": "8 步 DMD（快，cfg 1）", "pro": "50 步 SFT（慢，cfg 3 + 跳层）"}

    unet_default = MOSS_UNET
    clip_default = MOSS_CLIP
    vae_default = MOSS_VAE
    clip_types = MOSS_CLIP_TYPES
    pro_nodes = MOSS_PRO_NODES

    # 提示词形态：自然语言长 caption / 紧凑 JSON 布局（不是 danbooru tag 串）
    prompt_style = "moss_caption"

    # ==================== 取参数 ====================
    def _m(self, conn):
        """MOSS 配置块（config.yml flux_painter.moss）"""
        return getattr(conn.config, "moss", {}) or {}

    def unet(self, conn):
        """取当前家族的底图模型文件名。"""
        return (str(self._m(conn).get("unet_model") or "").strip()
                or str(getattr(conn.config, "unet_model", "") or "").strip()
                or self.unet_default)

    def clip(self, conn):
        """取当前家族的文本编码器文件名。"""
        return str(self._m(conn).get("clip_model") or "").strip() or self.clip_default

    def vae(self, conn):
        """取当前家族的 VAE 文件名。"""
        return str(self._m(conn).get("vae_model") or "").strip() or self.vae_default

    def clip_device(self, conn):
        """文本编码器加载位置：8GB 显存建议 cpu，把显存全留给 DiT"""
        dev = str(self._m(conn).get("clip_device") or "default").strip().lower()
        return "cpu" if dev == "cpu" else "default"

    def loras(self, conn):
        """MOSS 只用自己那条 DMD LoRA（anima 的 LoRA 不适用）"""
        m = self._m(conn)
        name = str(m.get("dmd_lora") or "").strip() or MOSS_DMD_LORA
        strength = float(m.get("dmd_strength", 0.7) or 0.7)
        return [{"name": name, "strength": strength}]

    # ==================== 织图 ====================
    def _core(self, conn, positive, negative, width, height, prefix, clip_type,
              steps, cfg, with_dmd, with_slg, seed):
        """按给定参数织 MOSS 主图（两档共用）。"""
        m = self._m(conn)
        sampler = str(m.get("sampler_name") or "euler")
        scheduler = str(m.get("scheduler") or "sgm_uniform")
        shift = float(m.get("shift", 5.0) or 5.0)
        sampling = str(m.get("sampling") or "flow")

        g = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": self.unet(conn), "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": self.clip(conn),
                             "type": clip_type or self.clip_types[0],
                             "device": self.clip_device(conn)}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": self.vae(conn)}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
            # MOSS 走 FLUX.2 系 latent（不是 EmptyLatentImage）
            "6": {"class_type": "EmptyFlux2LatentImage",
                  "inputs": {"width": int(width), "height": int(height), "batch_size": 1}},
        }

        # ---- 采样位移：shift 5 / flow（官方推荐）----
        model_src = ["1", 0]
        if shift:
            g["10"] = {"class_type": "ModelSamplingAuraFlow",
                       "inputs": {"model": model_src, "shift": float(shift),
                                  "sampling": sampling}}
            model_src = ["10", 0]

        # ---- 加速分支：DMD LoRA（8 步）----
        if with_dmd:
            for i, lora in enumerate(self.loras(conn), start=11):
                g[str(i)] = {"class_type": "LoraLoaderModelOnly",
                             "inputs": {"lora_name": str(lora["name"]),
                                        "strength_model": float(lora.get("strength", 0.7)),
                                        "model": model_src}}
                model_src = [str(i), 0]

        # ---- 额外 LoRA 链（风格/滑块件，如 age slider、2.5D 画风）：串在 DMD 之后 ----
        extra = list(m.get("loras") or [])
        if extra:
            existing = self._lora_names(conn)
            missing = getattr(conn, "_moss_missing_loras", None)
            if missing is None:
                missing = set()
                setattr(conn, "_moss_missing_loras", missing)
            start = 11 + len(self.loras(conn))
            for i, lora in enumerate(extra, start=start):
                name = str(lora.get("name") or "").strip()
                if not name:
                    continue
                if existing and name not in existing:
                    if name not in missing:
                        missing.add(name)
                        conn.log.info(
                            "[flux_painter] MOSS 额外 LoRA 未就位，已跳过: %s"
                            "（放进 models/loras 后自动生效）" % name)
                    continue
                g[str(i)] = {"class_type": "LoraLoaderModelOnly",
                             "inputs": {"lora_name": name,
                                        "strength_model": float(lora.get("strength", 0.8)),
                                        "model": model_src}}
                model_src = [str(i), 0]

        # ---- 质量分支：跳层引导（50 步原版用，只作用于 uncond 分支）----
        if with_slg:
            layers = str(m.get("slg_layers") or "22")
            g["13"] = {"class_type": "SkipLayerGuidanceDiTSimple",
                       "inputs": {"model": model_src,
                                  "double_layers": str(m.get("slg_double_layers") or ""),
                                  "single_layers": layers,
                                  "start_percent": float(m.get("slg_start", 0.0) or 0.0),
                                  "end_percent": float(m.get("slg_end", 1.0) or 1.0)}}
            model_src = ["13", 0]

        g["7"] = {"class_type": "KSampler",
                  "inputs": {"model": model_src, "positive": ["4", 0], "negative": ["5", 0],
                             "latent_image": ["6", 0], "seed": seed,
                             "steps": int(steps), "cfg": float(cfg),
                             "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0}}
        g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}}
        g["9"] = {"class_type": "SaveImage",
                  "inputs": {"images": ["8", 0], "filename_prefix": str(prefix)}}
        for _nid, _node in g.items():
            _node["inputs"] = conn.conform_inputs(_node["class_type"], _node["inputs"])
        return g

    def build_graph(self, conn, positive, negative, width, height, seed=None,
                    prefix="flux", clip_type=None, steps=None,
                    cfg=None, sampler=None, scheduler=None, model_sampling_shift=None):
        """快速档：8 步 + DMD LoRA(0.7) + cfg 1，与官方工作流「开关开启」完全一致。

        DMD 是这一档的**必选项**（没有开关）：官方就是 8 步 DMD、50 步才走非蒸馏。
        steps/cfg 仍允许调用方覆盖（续画/特殊参数）。
        """
        seed = seed if seed is not None else random.randint(0, 2 ** 63 - 1)
        width, height = conn._align16(width), conn._align16(height)
        m = self._m(conn)
        steps = steps if steps is not None else int(m.get("dmd_steps", 8) or 8)
        cfg = cfg if cfg is not None else float(m.get("dmd_cfg", 1.0) or 1.0)
        return self._core(conn, positive, negative, width, height, prefix, clip_type,
                          steps=steps, cfg=cfg, with_dmd=True, with_slg=False,
                          seed=seed)

    def build_pro_graph(self, conn, positive, negative, width, height, prefix="flux",
                        clip_type=None, seed=None, params=None):
        """清晰档：50 步原版 SFT + 跳层 22（不看 dmd 开关，强制走非蒸馏分支）"""
        seed = seed if seed is not None else random.randint(0, 2 ** 63 - 1)
        width, height = conn._align16(width), conn._align16(height)
        m = self._m(conn)
        return self._core(conn, positive, negative, width, height, prefix, clip_type,
                          steps=int(m.get("sft_steps", 50) or 50),
                          cfg=float(m.get("sft_cfg", 3.0) or 3.0),
                          with_dmd=False, with_slg=True, seed=seed)

    # ==================== 图生图附加处理 ====================
    # 官方编辑 LoRA：moss_image_edit_lora_rank_64_bf16（input 图 + 指令改图用）。
    # 仅在「带参考图」时叠加，纯文生图不加载，避免影响画质与速度。
    EDIT_LORA_NODE = "95"

    def after_img2img(self, conn, graph):
        """参考图接入后的收尾：收敛 denoise + 可选挂编辑 LoRA"""
        if not isinstance(graph, dict):
            return graph
        ks = graph.get("7")
        if not isinstance(ks, dict):
            return graph
        m = self._m(conn)
        # DMD 8 步档步数少：denoise 太高会糊，太低等于没改，夹到安全区间
        try:
            lo, hi = float(m.get("img2img_denoise_min", 0.35) or 0.35), \
                float(m.get("img2img_denoise_max", 0.8) or 0.8)
        except (TypeError, ValueError):
            lo, hi = 0.35, 0.8
        cur = float(ks["inputs"].get("denoise", 0.55) or 0.55)
        ks["inputs"]["denoise"] = min(hi, max(lo, cur))

        lora = str(m.get("edit_lora") or "").strip()
        if not lora:
            return graph
        if not self._lora_exists(conn, lora):
            conn.log.warning("[flux_painter] 编辑 LoRA 不存在，已跳过: %s（放进 models/loras 后自动生效）" % lora)
            return graph
        strength = float(m.get("edit_lora_strength", 0.9) or 0.9)
        model_ref = ks["inputs"].get("model")
        if not isinstance(model_ref, (list, tuple)):
            return graph
        graph[self.EDIT_LORA_NODE] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": lora, "strength_model": strength,
                       "model": [str(model_ref[0]), int(model_ref[1])]},
        }
        ks["inputs"]["model"] = [self.EDIT_LORA_NODE, 0]
        conn.log.info("[flux_painter] 图生图已挂编辑 LoRA: %s(%.2f)" % (lora, strength))
        return graph

    @staticmethod
    def _lora_names(conn):
        """引擎里可用的 LoRA 文件名集合（顺带过滤掉误下载的 HTML/过小文件）"""
        try:
            info = conn.object_info()
            lst = (((info.get("LoraLoaderModelOnly") or {}).get("input") or {})
                   .get("required") or {}).get("lora_name")
            if isinstance(lst, (list, tuple)) and lst:
                opts = lst[0]
                if isinstance(opts, (list, tuple)):
                    return {str(x) for x in opts}
        except Exception:
            pass
        try:
            import os
            base = os.path.join(getattr(conn.config, "comfy_node_dir", ".vendor/.ComfyNode"),
                                "models", "loras")
            if os.path.isdir(base):
                out = set()
                for n in os.listdir(base):
                    if not n.lower().endswith(".safetensors"):
                        continue
                    try:
                        # 正常 LoRA 至少几 MB；几百 KB 的基本是错误页
                        if os.path.getsize(os.path.join(base, n)) > (1 << 20):
                            out.add(n)
                    except OSError:
                        continue
                return out
        except Exception:
            pass
        return set()

    def trigger_words(self, conn):
        """额外 LoRA 自带的触发词（如 wangzhe/maliker）；文件没就位的不算"""
        out = []
        names = self._lora_names(conn)
        for lora in list(self._m(conn).get("loras") or []):
            t = str(lora.get("trigger") or "").strip()
            if not t or t in out:
                continue
            name = str(lora.get("name") or "")
            if names and name not in names:
                continue
            out.append(t)
        return out

    @staticmethod
    def _lora_exists(conn, name):
        """优先问引擎的 loras 列表；问不到就按目录名兜底"""
        try:
            info = conn.object_info()
            lst = (((info.get("LoraLoaderModelOnly") or {}).get("input") or {})
                   .get("required") or {}).get("lora_name")
            if isinstance(lst, (list, tuple)) and lst:
                opts = lst[0]
                if isinstance(opts, (list, tuple)):
                    return str(name) in [str(x) for x in opts]
        except Exception:
            pass
        try:
            import os
            p = os.path.join(getattr(conn.config, "comfy_node_dir", ".vendor/.ComfyNode"),
                             "models", "loras", str(name))
            return os.path.isfile(p)
        except Exception:
            return False
