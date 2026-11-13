# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/config.py
import os
import re

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBFluxPainterConfig:
    """统一管理 config.yml 的 flux_painter 节点（画布/LLM/ComfyUI/审查/记忆/TTS/采样）"""

    def __init__(self):
        """初始化。"""
        cfg = ConfigReader().get("flux_painter", {})

        self.enabled = bool(cfg.get("enabled", False))
        self.http_port = int(cfg.get("http_port", 8090))
        self.ws_port = int(cfg.get("ws_port", 8767))

        # ===== 底模（UNET）=====
        # GUI「绘画底模」下拉写入 flux_painter.unet_model，工作流方言按它自动判定
        # （moss_* → MOSS 方言；anima/miaomiao → Anima 方言）。原版 anima baseV10 已移除。
        self.unet_model = str(cfg.get("unet_model") or "miaomiaoHarem_anima16.safetensors").strip()

        # ===== 工作流方言 =====
        # auto=按底模名推断（默认）；anima / moss 可强制指定
        self.model_family = str(cfg.get("model_family", "auto") or "auto").strip().lower()
        if self.model_family not in ("auto", "anima", "moss"):
            self.model_family = "auto"
        self.moss = self._load_moss(cfg.get("moss"))

        # ===== 画布两档（AI 调用时自选；后端换算到 ComfyUI 像素） =====
        raw = cfg.get("canvas_sizes") or [[1024, 1024], [1080, 1960]]
        self.canvas_sizes = []
        if isinstance(raw, str):
            raw = [x for x in re.split(r"[\s,，;；]+", raw) if x.strip()]
        for item in raw:
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    self.canvas_sizes.append((int(item[0]), int(item[1])))
                else:
                    m = re.match(r"(\d+)\s*[xX*]\s*(\d+)", str(item).strip())
                    if m:
                        self.canvas_sizes.append((int(m.group(1)), int(m.group(2))))
            except Exception:
                pass
        if not self.canvas_sizes:
            self.canvas_sizes = [(1024, 1024), (1080, 1960)]
        self.canvas_default = self.canvas_sizes[1] if len(self.canvas_sizes) > 1 else self.canvas_sizes[0]

        # ===== 提示词 LLM（沿用原绘画端口配置，thinking + function calling） =====
        self.llm_type = str(cfg.get("llm_type", "deepseek"))
        self.thinking_enabled = bool(cfg.get("thinking_enabled", True))
        # 破甲开关：向提示词 LLM 声明本地私有成年向创作边界（默认开，可关）
        self.adult_mode = bool(cfg.get("adult_mode", True))
        self.temperature = float(cfg.get("temperature", 0.8))
        self.max_tokens = int(cfg.get("max_tokens", 8192))
        ds = cfg.get("deepseek", {})
        self.deepseek_api_key = str(ds.get("api_key", "") or "")
        self.deepseek_base_url = str(ds.get("base_url", "https://api.deepseek.com/v1") or "")
        self.deepseek_model = str(ds.get("model", "deepseek-v4-flash") or "deepseek-v4-flash")
        al = cfg.get("aliyun", {})
        self.aliyun_api_key = str(al.get("api_key", "") or "")
        self.aliyun_base_url = str(al.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1") or "")
        self.aliyun_model = str(al.get("model", "qwen3.7-flash") or "qwen3.7-flash")

        # ===== 提示词固定件（质量前缀/负面/默认画风，脚本侧拼接） =====
        self.quality_prefix = str(cfg.get("quality_prefix") or "")
        self.negative_prompt = str(cfg.get("negative_prompt") or "")
        # 风格化触发词：命中则从 artists 名单随机抽 1 个画师（默认不挂任何画师 tag）
        raw_son = cfg.get("style_on_keywords")
        if isinstance(raw_son, (list, tuple)):
            self.style_on_keywords = [str(x).strip() for x in raw_son if str(x).strip()]
        else:
            self.style_on_keywords = [x.strip() for x in
                                      re.split(r"[\s,，;；|]+", str(raw_son or "")) if x.strip()]
        if not self.style_on_keywords:
            self.style_on_keywords = ["风格化", "换个风格", "换风格", "换个画风", "换画风", "来点风格",
                                      "加点风格", "加风格", "强风格", "要风格", "风格强一点",
                                      "艺术风格", "个性化风格", "独特风格", "插画风", "有风格"]

        # ===== ComfyUI（内置 internal / 外部 external） =====
        cf = cfg.get("comfy", {}) or {}
        self.comfy_mode = str(cf.get("mode", "internal"))
        self.comfy_host = str(cf.get("host", "127.0.0.1"))
        self.comfy_port = int(cf.get("port", 8188))
        self.comfy_node_dir = str(cf.get("comfy_node_dir", ".vendor/.ComfyNode") or ".vendor/.ComfyNode")
        self.comfy_output_dir = str(cf.get("output_dir", os.path.join(self.comfy_node_dir, "output")) or "")
        self.workflow_file = str(cf.get("workflow_file") or
                                os.path.join(self.comfy_node_dir, "node", "workflow.json"))
        self.prompt_reference_dir = str(cf.get("prompt_reference_dir") or
                                        os.path.join(self.comfy_node_dir, "prompt_reference"))
        self.artist_data = str(cf.get("artist_data") or os.path.join(self.comfy_node_dir, "artist", "data.js"))
        self.internal_python = str(cf.get("internal_python", "") or "")
        self.internal_main = str(cf.get("internal_main", "") or "")
        # 引擎窗口模式：True=独立控制台弹窗运行（引擎日志在独立窗口，不占主程序终端）；
        # False=静默后台运行，日志落 logs/comfy_engine.log
        self.engine_window = bool(cf.get("engine_window", True))
        # 画板实时进度：订阅引擎 WebSocket 广播阶段/百分比/步进（关=退回粗粒度状态）
        self.progress_detail = bool(cfg.get("progress_detail", True))
        try:
            self.wait_timeout = max(60, int(cfg.get("wait_timeout", 5400)))
        except (TypeError, ValueError):
            self.wait_timeout = 5400
        # 画师站多源（画板前端“画师站”按钮跳转列表）
        self.artist_sources = []
        for item in (cf.get("artist_sources") or []):
            if isinstance(item, dict) and item.get("url"):
                self.artist_sources.append({"name": str(item.get("name") or item["url"]),
                                            "url": str(item["url"])})
        if not self.artist_sources:
            self.artist_sources = [
                {"name": "danbooru 画师词条", "url": "https://danbooru.donmai.us/artists/{id}"},
                {"name": "danbooru 作品参考", "url": "https://danbooru.donmai.us/posts?tags=artist:{name}"}]

        # ===== 采样参数 =====
        self.sampler_name = str(cfg.get("sampler_name", "er_sde"))
        self.sampler_scheduler = str(cfg.get("sampler_scheduler", "simple"))
        self.sampler_cfg = float(cfg.get("sampler_cfg", 5.0))
        self.sampler_steps = int(cfg.get("sampler_steps", 30))
        self.sampler_shift = float(cfg.get("sampler_shift", 3.0))

        # ===== 画质档位（前端开关）：fast=快速（现状单段采样）/ pro=清晰（04+05+06+07 全流程） =====
        self.quality_mode = str(cfg.get("quality_mode", "fast") or "fast").strip().lower()
        if self.quality_mode not in ("fast", "pro"):
            self.quality_mode = "fast"

        # ===== Pro 参数组（config.yml 缺项时用 pro 工作流原值兜底，保证开箱即用） =====
        pro = cfg.get("pro") if isinstance(cfg.get("pro"), dict) else {}

        def _merge(raw, defaults):
            """逐键覆盖：raw 中的已知键覆盖 defaults，未知键忽略"""
            out = dict(defaults)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in out:
                        out[k] = v
            return out

        # 07 局部细化默认值（照抄 pro：hand / face / eye 三段，链式执行）
        _det_defaults = {
            "hand": {"enabled": True, "detector": "bbox/hand_yolov8s.pt", "guide_size": 768,
                     "max_size": 1280, "steps": 14, "cfg": 3.0, "denoise": 0.28, "feather": 8,
                     "bbox_threshold": 0.35, "bbox_dilation": 16, "bbox_crop_factor": 2.5,
                     "noise_mask": True, "force_inpaint": False},
            "face": {"enabled": True, "detector": "bbox/face_yolov8m.pt", "guide_size": 768,
                     "max_size": 1280, "steps": 14, "cfg": 3.0, "denoise": 0.24, "feather": 8,
                     "bbox_threshold": 0.35, "bbox_dilation": 16, "bbox_crop_factor": 2.5,
                     "noise_mask": True, "force_inpaint": False},
            # eye（眼脸润色）：尺寸类参数与 face 段对齐（guide/max/crop/dilation/feather 同规格），
            # 仅保留更轻的 denoise/steps/cfg —— 避免 crop 尺寸未按 16 对齐产生奇数 latent
            "eye": {"enabled": True, "detector": "bbox/face_yolov8m.pt", "guide_size": 768,
                    "max_size": 1280, "steps": 12, "cfg": 2.8, "denoise": 0.18, "feather": 8,
                    "bbox_threshold": 0.35, "bbox_dilation": 16, "bbox_crop_factor": 2.5,
                    "noise_mask": True, "force_inpaint": False},
        }
        raw_det = pro.get("detailers") if isinstance(pro.get("detailers"), dict) else {}
        detailers = {}
        for _name, _dflt in _det_defaults.items():
            detailers[_name] = _merge(raw_det.get(_name), _dflt)

        self.pro = {
            "enabled": bool(pro.get("enabled", True)),
            # False = 回到 --disable-all-custom-nodes（插件整体禁用，自动降级快速档）
            "allow_custom_nodes": bool(pro.get("allow_custom_nodes", True)),
            # 04 基础采样（按 pro：cfg 4 / 30 步）
            "base_cfg": float(pro.get("base_cfg", 4.0)),
            "base_steps": int(pro.get("base_steps", 30)),
            # 05 高清预处理（4x 模型放大 → 缩放到画布×scale）
            "hires": _merge(pro.get("hires"), {
                "enabled": True,
                "upscale_model": "4x-AnimeSharp.pth",
                "scale": 2.0,
                "resize": "lanczos",
            }),
            # 06 分块高清（UltimateSDUpscaleNoUpscale）
            "usdu": _merge(pro.get("usdu"), {
                "enabled": True, "steps": 20, "cfg": 8.0, "sampler": "euler",
                "scheduler": "simple", "denoise": 0.15, "mode_type": "Linear",
                "tile_width": 512, "tile_height": 512, "mask_blur": 32,
                "tile_padding": 256, "seam_fix_mode": "None", "seam_fix_denoise": 1.0,
                "seam_fix_width": 64, "seam_fix_mask_blur": 8, "seam_fix_padding": 16,
                "force_uniform_tiles": True, "tiled_decode": False,
            }),
            # 07 局部细化（链式 hand→face→eye）
            "detailers": detailers,
            "sam_model": str(pro.get("sam_model", "sam_vit_b_01ec64.pth") or ""),
            "sam": _merge(pro.get("sam"), {
                "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
                "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False", "drop_size": 10, "cycle": 1,
                "noise_mask_feather": 20,
            }),
            # 局部提示词（手部区域）
            "pos_hand": str(pro.get("pos_hand", "hand") or "hand"),
            "neg_hand": str(pro.get("neg_hand") or
                            "worst quality, low quality, bad quality, bad hands, "
                            "deformed, 3 fingers, extra digits, 6 fingers"),
        }

        # ===== LoRA 链（叠加到 UNET，LoraLoaderModelOnly） =====
        # config.yml flux_painter.lora_chain: [{name, strength, enabled}, ...]；
        # enabled: false 表示 GUI 中关闭该 LoRA（不加载）；空列表 [] 即不加 LoRA
        raw_lora = cfg.get("lora_chain")
        if raw_lora is None:
            # 默认链：高分辨率美学增强 1.0 + 上下文细节增强 0.5
            raw_lora = [
                {"name": "anima-highres-aesthetic-boost.safetensors", "strength": 1.0, "enabled": True},
                {"name": "anima_context_detailer_base10.safetensors", "strength": 0.5, "enabled": True},
            ]
        self.lora_chain = []
        if isinstance(raw_lora, list):
            for item in raw_lora:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                # enabled 缺省视为开启；显式 false 时跳过（GUI 关闭的 LoRA 不加载）
                if not item.get("enabled", True):
                    continue
                self.lora_chain.append({
                    "name": str(item["name"]).strip(),
                    "strength": float(item.get("strength", 0.8)),
                    "enabled": True,
                })

        # ===== 审查模式 =====
        # review_enabled：总开关；review_mode：onnx=NudeNet 自动判定（与 QQ 群聊同一模型）/ manual=画板按钮人工
        self.review_enabled = bool(cfg.get("review_enabled", False))
        self.review_mode = str(cfg.get("review_mode", "onnx") or "onnx").strip().lower()
        if self.review_mode not in ("onnx", "manual"):
            self.review_mode = "onnx"

        # ===== 点名角色解析（词典 → danbooru tag → 缓存 → 萌娘百科） =====
        self.moegirl_lookup = bool(cfg.get("moegirl_lookup", True))
        # danbooru 先查角色 tag（生成模型认得角色，关键在 tag 写对）；失败自动跳过
        self.danbooru_lookup = bool(cfg.get("danbooru_lookup", True))
        self.danbooru_timeout = max(3, int(cfg.get("danbooru_timeout", 8) or 8))
        prd = self.prompt_reference_dir
        self.role_map_file = os.path.join(prd, "role_map.json")
        self.role_cache_file = os.path.join(prd, "role_cache.json")

        # ===== 群聊裸露审查（NudeNet onnx） =====
        nc = cfg.get("nsfw_check") or {}
        self.nsfw_enabled = bool(nc.get("enabled", False))
        self.nsfw_mode = str(nc.get("mode", "nudenet"))
        self.nsfw_threshold = float(nc.get("threshold", 0.45))
        self.nsfw_fail = str(nc.get("fail_action", "dm"))
        self.nsfw_model_path = str(nc.get("model_path",
                                          os.path.join(".vendor", ".ComfyNode", "nsfw", "nudenet.onnx")) or "")
        self.nsfw_model_url = str(nc.get("model_url",
                                         "https://huggingface.co/vladmandic/nudenet/resolve/main/nudenet.onnx") or "")

        # ===== 归档 / 记忆 / TTS =====
        self.temp_dir = str(cfg.get("temp_dir", os.path.join(".temp", "flux_paint")) or
                            os.path.join(".temp", "flux_paint"))
        self.backup_dir = str(cfg.get("backup_dir", os.path.join("character", "paints")) or
                              os.path.join("character", "paints"))
        self.keep_last_sessions = int(cfg.get("keep_last_sessions", 0))
        # ===== 改图判定（画完后 window 秒内的下一条完整 @/关键词消息） =====
        ef = cfg.get("edit_followup") or {}
        self.edit_followup_enabled = bool(ef.get("enabled", True))
        # 画完后的改图等待窗口（秒）：窗口内下一条 @/关键词消息参与改图判定
        self.edit_followup_window = float(ef.get("window", 120))
        self.edit_followup_max_tokens = int(ef.get("llm_max_tokens", 512))
        self.edit_followup_temperature = float(ef.get("llm_temperature", 0.3))
        self.memory_enabled = bool(cfg.get("memory_enabled", True))
        self.memory_type = str(cfg.get("memory_type", "painting"))
        self.memory_rounds = int(cfg.get("memory_rounds", 10))
        self.tts_source = str(cfg.get("tts_source", "toolbox_painting"))
        # ===== 图生图（参考图来源：QQ 附图 / 屏幕截图；采样与画布与文生图共用） =====
        ii = cfg.get("img2img") or {}
        self.img2img_enabled = bool(ii.get("enabled", True))
        try:
            self.img2img_denoise = min(0.95, max(0.05, float(ii.get("denoise", 0.75))))
        except (TypeError, ValueError):
            self.img2img_denoise = 0.75
        try:
            # 取景复查轮数：默认 3 轮够用，硬上限 5 轮
            self.img2img_focus_rounds = min(5, max(1, int(ii.get("focus_rounds", 3))))
        except (TypeError, ValueError):
            self.img2img_focus_rounds = 3
        try:
            self.img2img_screen_max_side = max(320, int(ii.get("screen_max_side", 1280)))
        except (TypeError, ValueError):
            self.img2img_screen_max_side = 1280
        self.ref_dir = os.path.join(self.temp_dir, "ref")

    def active_llm(self) -> dict:
        """当前生效绘画模型连接参数"""
        if self.llm_type == "aliyun":
            return {"llm_type": "aliyun", "api_key": self.aliyun_api_key,
                    "base_url": self.aliyun_base_url, "model": self.aliyun_model}
        return {"llm_type": "deepseek", "api_key": self.deepseek_api_key,
                "base_url": self.deepseek_base_url, "model": self.deepseek_model}

    # ==================== 工作流方言 ====================
    @property
    def family(self) -> str:
        """当前生效的底模家族（anima / moss）"""
        from func.toolbox.flux_painter.dialects import resolve_family
        return resolve_family(self.unet_model, self.model_family)

    @property
    def is_moss(self) -> bool:
        """当前是否 MOSS 家族。"""
        return self.family == "moss"

    @staticmethod
    def _load_moss(raw) -> dict:
        """MOSS 方言参数块：与 anima 完全独立，缺项按官方推荐值兜底

        数据来自 OpenMOSS 用户指南：shift 5 / Euler / 50 步 cfg 3 / 跳层 22；
        8 步档为社区 DMD 蒸馏 LoRA（cfg 1，负向词不参与）。
        """
        from func.toolbox.flux_painter.dialects.moss import (
            MOSS_CLIP, MOSS_DEFAULT_NEGATIVE, MOSS_DEFAULT_QUALITY, MOSS_DMD_LORA,
            MOSS_UNET, MOSS_VAE)
        m = raw if isinstance(raw, dict) else {}

        def _f(key, dflt):
            """取浮点配置（非法值回落默认）。"""
            try:
                return float(m.get(key, dflt))
            except (TypeError, ValueError):
                return float(dflt)

        def _parse_loras(items):
            """额外 LoRA 链：[{name, strength, enabled, trigger}]

            前端列表编辑器会写成一串 JSON（也可能被 YAML 存成真正的列表），两种都吃。
            """
            if isinstance(items, str):
                try:
                    import json as _json
                    items = _json.loads(items or "[]")
                except Exception:
                    items = []
            out = []
            for it in (items or []):
                if not isinstance(it, dict) or not str(it.get("name") or "").strip():
                    continue
                if not it.get("enabled", True):
                    continue
                out.append({
                    "name": str(it["name"]).strip(),
                    "strength": float(it.get("strength", 0.8) or 0.0),
                    "trigger": str(it.get("trigger") or "").strip(),
                })
            return out

        nsfw = m.get("nsfw") if isinstance(m.get("nsfw"), dict) else {}
        return {
            # 三件套
            "unet_model": str(m.get("unet_model") or MOSS_UNET).strip(),
            "clip_model": str(m.get("clip_model") or MOSS_CLIP).strip(),
            "vae_model": str(m.get("vae_model") or MOSS_VAE).strip(),
            # 文本编码器位置：8GB 显存建议 cpu（显存全留给 DiT）
            "clip_device": str(m.get("clip_device") or "default").strip().lower(),
            # 加速档（8 步 DMD）：DMD 是这一档的必选项，没有开关
            "dmd_lora": str(m.get("dmd_lora") or MOSS_DMD_LORA).strip(),
            "dmd_strength": _f("dmd_strength", 0.7),
            "dmd_steps": int(m.get("dmd_steps", 8) or 8),
            "dmd_cfg": _f("dmd_cfg", 1.0),
            # 原版档（50 步 + 跳层）
            "sft_steps": int(m.get("sft_steps", 50) or 50),
            "sft_cfg": _f("sft_cfg", 3.0),
            "slg_layers": str(m.get("slg_layers", "22") or ""),
            "slg_double_layers": str(m.get("slg_double_layers", "") or ""),
            "slg_start": _f("slg_start", 0.0),
            "slg_end": _f("slg_end", 1.0),
            # 采样
            "shift": _f("shift", 5.0),
            "sampling": str(m.get("sampling") or "flow").strip().lower(),
            "sampler_name": str(m.get("sampler_name") or "euler").strip(),
            "scheduler": str(m.get("scheduler") or "sgm_uniform").strip(),
            # 提示词形态：json=紧凑 JSON 布局（官方 layout）/ caption=自然语言长描述
            "prompt_mode": (str(m.get("prompt_mode") or "caption").strip().lower()
                            if str(m.get("prompt_mode") or "caption").strip().lower()
                            in ("json", "caption") else "caption"),
            "quality_prefix": str(m.get("quality_prefix") or MOSS_DEFAULT_QUALITY),
            "negative_prompt": str(m.get("negative_prompt") or MOSS_DEFAULT_NEGATIVE),
            # MOSS 专属审查（与组图共用的 NudeNet 分开配，阈值尺度不同）
            "nsfw": {
                "enabled": bool(nsfw.get("enabled", False)),
                "threshold": _f("threshold", 0.45),
                "fail_action": str(nsfw.get("fail_action") or "dm"),
            },
            # 图生图：DMD 8 步档可用步数少，denoise 太高会糊，默认 0.55
            "img2img_denoise": _f("img2img_denoise", 0.55),            # 官方编辑 LoRA（moss_image_edit_lora_rank_64_bf16）：有图时叠加，纯文生图不加载
            "edit_lora": str(m.get("edit_lora") or "").strip(),
            "edit_lora_strength": _f("edit_lora_strength", 0.9),
            # 额外 LoRA 链（前端列表编辑器直接给 name/strength/enabled/trigger）
            "loras": _parse_loras(m.get("loras")),
        }

    def moss_nsfw(self) -> dict:
        """MOSS 生效的裸露审查参数（未启用 MOSS 专属时回落到全局设置）"""
        m = self.moss.get("nsfw") or {}
        if m.get("enabled"):
            return m
        return {"enabled": self.nsfw_enabled, "threshold": self.nsfw_threshold,
                "fail_action": self.nsfw_fail}

    def active_negative(self) -> str:
        """当前家族生效的负面提示词（MOSS 用官方那行短负向）"""
        if self.is_moss:
            return str(self.moss.get("negative_prompt")
                       or self.moss.get("negative")
                       or "worst quality, bad anatomy, watermark, jpeg artifact")
        return self.negative_prompt

    def active_quality(self) -> str:
        """当前家族生效的质量前缀"""
        if self.is_moss:
            return str(self.moss.get("quality_prefix") or "")
        return self.quality_prefix

    def img2img_denoise_for(self, family=None) -> float:
        """图生图参考强度：MOSS 与 Anima 的步数体系不同，各用各的"""
        fam = str(family or self.family).lower()
        if fam == "moss":
            try:
                return min(0.95, max(0.05, float(self.moss.get("img2img_denoise", 0.55))))
            except (TypeError, ValueError):
                return 0.55
        return self.img2img_denoise


    def comfy_base(self) -> str:
        """内置/外部 ComfyUI 的 http 根地址"""
        return f"http://{self.comfy_host}:{self.comfy_port}"
