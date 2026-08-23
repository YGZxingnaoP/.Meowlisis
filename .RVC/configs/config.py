# -*- coding: utf-8 -*-
# RVC 精简版 Config：仅保留推理所需的设备选择与分块参数
# 已移除 argparse / WebUI / 训练相关逻辑，供 cover_server.py 以库方式使用
import os
import re
import json
from multiprocessing import cpu_count
from pathlib import Path

import torch
import logging

from tools.cuda_graph import configure_cuda_graph

logger = logging.getLogger(__name__)


def get_device_dtype_sm(idx):
    """选择设备与精度（沿用 RVC/GPT-SoVITS 的 GPU 规则）"""
    cpu = torch.device("cpu")
    if not torch.cuda.is_available() or idx < 0 or idx >= torch.cuda.device_count():
        return cpu, torch.float32, 0.0, 0.0
    try:
        cuda = torch.device(f"cuda:{idx}")
        major, minor = torch.cuda.get_device_capability(idx)
        gpu_name = torch.cuda.get_device_name(idx)
        mem_bytes = torch.cuda.get_device_properties(idx).total_memory
    except Exception:
        return cpu, torch.float32, 0.0, 0.0

    mem_gb = mem_bytes / (1024 ** 3) + 0.4
    sm_version = major + minor / 10.0
    is_16_series = bool(re.search(r"16\d{2}", gpu_name)) and sm_version == 7.5
    if mem_gb < 4 or sm_version < 5.3:
        return cpu, torch.float32, 0.0, 0.0
    if sm_version == 6.1 or is_16_series:
        return cuda, torch.float32, sm_version, mem_gb
    if sm_version > 6.1:
        return cuda, torch.float16, sm_version, mem_gb
    return cpu, torch.float32, 0.0, 0.0


CUDA_AVAILABLE = torch.cuda.is_available()
GPU_COUNT = torch.cuda.device_count() if CUDA_AVAILABLE else 0
GPU_PROFILES = [get_device_dtype_sm(i) for i in range(GPU_COUNT)]


def _detect_directml():
    try:
        import torch_directml
        device = torch_directml.device(torch_directml.default_device())
        probe = torch.ones(1, dtype=torch.float32).to(device)
        _ = (probe + 1).cpu()
        return True, device
    except Exception:
        return False, None


DML_AVAILABLE, DML_DEVICE = _detect_directml()

if GPU_PROFILES:
    infer_device, infer_dtype, _, infer_gpu_mem = max(
        GPU_PROFILES, key=lambda p: (p[2], p[3])
    )
else:
    infer_device, infer_dtype, infer_gpu_mem = (
        torch.device("cpu"),
        torch.float32,
        0.0,
    )

if infer_device.type != "cuda":
    if DML_AVAILABLE:
        infer_device, infer_dtype, infer_gpu_mem = (
            DML_DEVICE,
            torch.float32,
            0.0,
        )
    else:
        infer_device, infer_dtype, infer_gpu_mem = (
            torch.device("cpu"),
            torch.float32,
            0.0,
        )

CUDA_GRAPH_AVAILABLE = configure_cuda_graph(infer_device)

CONFIGS_DIR = Path(__file__).resolve().parent
MODEL_CONFIG_FILES = (
    "v1/32k.json",
    "v1/40k.json",
    "v1/48k.json",
    "v2/48k.json",
    "v2/32k.json",
)


def singleton_variable(func):
    def wrapper(*args, **kwargs):
        if not wrapper.instance:
            wrapper.instance = func(*args, **kwargs)
        return wrapper.instance
    wrapper.instance = None
    return wrapper


@singleton_variable
class Config:
    def __init__(self):
        self.device = str(infer_device)
        self.dtype = infer_dtype
        self.is_half = infer_dtype == torch.float16
        self.cuda_graph = CUDA_GRAPH_AVAILABLE
        self.n_cpu = cpu_count()
        self.gpu_name = None
        self.gpu_mem = None
        self.json_config = self.load_config_json()
        self.x_pad, self.x_query, self.x_center, self.x_max = self.device_config()

    @staticmethod
    def load_config_json():
        from tools.file_io import read_text
        d = {}
        for config_file in MODEL_CONFIG_FILES:
            d[config_file] = json.loads(read_text(CONFIGS_DIR / config_file))
        return d

    def device_config(self):
        if infer_device.type == "cuda":
            i_device = infer_device.index
            self.gpu_name = torch.cuda.get_device_name(i_device)
            self.gpu_mem = int(infer_gpu_mem)
            logger.info(
                "Selected GPU %s (%s, SM %.1f, %.1f GiB)",
                i_device,
                self.gpu_name,
                torch.cuda.get_device_capability(i_device)[0]
                + torch.cuda.get_device_capability(i_device)[1] / 10.0,
                infer_gpu_mem,
            )
        else:
            logger.info("No supported Nvidia GPU found")
            self.device = "cpu"
            self.dtype = torch.float32
            self.is_half = False

        if self.is_half:
            x_pad, x_query, x_center, x_max = 3, 10, 60, 65
        else:
            x_pad, x_query, x_center, x_max = 1, 6, 38, 41

        if self.gpu_mem is not None and self.gpu_mem <= 4:
            x_pad, x_query, x_center, x_max = 1, 5, 30, 32

        if DML_AVAILABLE and infer_device.type != "cuda":
            logger.info("Use DirectML instead")
            import torch_directml
            self.device = torch_directml.device(torch_directml.default_device())
            self.dtype = torch.float32
            self.is_half = False

        logger.info(
            "Half-precision floating-point: %s, device: %s",
            self.is_half,
            self.device,
        )
        return x_pad, x_query, x_center, x_max
