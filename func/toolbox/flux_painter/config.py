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
        cfg = ConfigReader().get("flux_painter", {})

        self.enabled = bool(cfg.get("enabled", False))
        self.http_port = int(cfg.get("http_port", 8090))
        self.ws_port = int(cfg.get("ws_port", 8767))

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
        self.default_style = [str(x) for x in (cfg.get("default_style") or []) if str(x).strip()]

        # ===== ComfyUI（内置 internal / 外部 external） =====
        cf = cfg.get("comfy", {}) or {}
        self.comfy_mode = str(cf.get("mode", "internal"))
        self.comfy_host = str(cf.get("host", "127.0.0.1"))
        self.comfy_port = int(cf.get("port", 8188))
        self.comfy_node_dir = str(cf.get("comfy_node_dir", ".ComfyNode") or ".ComfyNode")
        self.comfy_output_dir = str(cf.get("output_dir", os.path.join(self.comfy_node_dir, "output")) or "")
        self.workflow_file = str(cf.get("workflow_file") or
                                os.path.join(self.comfy_node_dir, "node", "workflow.json"))
        self.prompt_reference_dir = str(cf.get("prompt_reference_dir") or
                                        os.path.join(self.comfy_node_dir, "prompt_reference"))
        self.artist_data = str(cf.get("artist_data") or os.path.join(self.comfy_node_dir, "artist", "data.js"))
        self.internal_python = str(cf.get("internal_python", "") or "")
        self.internal_main = str(cf.get("internal_main", "") or "")
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

        # ===== 审查模式 =====
        self.review_enabled = bool(cfg.get("review_enabled", False))

        # ===== 归档 / 记忆 / TTS =====
        self.temp_dir = str(cfg.get("temp_dir", os.path.join(".temp", "flux_paint")) or
                            os.path.join(".temp", "flux_paint"))
        self.backup_dir = str(cfg.get("backup_dir", os.path.join("character", "paints")) or
                              os.path.join("character", "paints"))
        self.keep_last_sessions = int(cfg.get("keep_last_sessions", 0))
        self.memory_enabled = bool(cfg.get("memory_enabled", True))
        self.memory_type = str(cfg.get("memory_type", "painting"))
        self.memory_rounds = int(cfg.get("memory_rounds", 10))
        self.tts_source = str(cfg.get("tts_source", "toolbox_painting"))

    def active_llm(self) -> dict:
        """当前生效绘画模型连接参数"""
        if self.llm_type == "aliyun":
            return {"llm_type": "aliyun", "api_key": self.aliyun_api_key,
                    "base_url": self.aliyun_base_url, "model": self.aliyun_model}
        return {"llm_type": "deepseek", "api_key": self.deepseek_api_key,
                "base_url": self.deepseek_base_url, "model": self.deepseek_model}

    def comfy_base(self) -> str:
        """内置/外部 ComfyUI 的 http 根地址"""
        return f"http://{self.comfy_host}:{self.comfy_port}"
