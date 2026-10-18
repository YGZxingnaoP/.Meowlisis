# -*- coding: utf-8 -*-
"""GPU / 显存采样（只读，永不抛异常）。

给实验台与配置页的"运行时面板"用：显存总量/已用、利用率、当前进程占用。

为什么不用 torch 直接算：`torch.cuda.mem_get_info()` 给的是**驱动层**的
free/total（含别的进程），才是用户想看的"显卡占用"；`memory_allocated()`
只是本进程的 PyTorch 缓存，两者都要有。
"""

from __future__ import annotations

import os
import threading

_LOCK = threading.Lock()
_STATE = {"init": False, "nvml": None, "name": ""}


def _init_nvml():
    """惰性初始化 NVML（pynvml），失败就永久放弃。"""
    with _LOCK:
        if _STATE["init"]:
            return _STATE["nvml"]
        _STATE["init"] = True
        try:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            _STATE["nvml"] = pynvml
        except Exception:  # noqa: BLE001 - 没装/没驱动都属正常
            _STATE["nvml"] = None
        return _STATE["nvml"]


def _bytes_to_mb(value) -> float | None:
    try:
        return round(float(value) / 1024 / 1024, 1)
    except Exception:  # noqa: BLE001
        return None


def sample(device_index: int | None = None) -> dict:
    """返回一块 GPU 状态；拿不到的部分给 None，绝不抛。"""
    body: dict = {
        "available": False,
        "index": device_index,
        "name": None,
        "memory_total_mb": None,
        "memory_used_mb": None,
        "memory_free_mb": None,
        "utilization_pct": None,
        "process_allocated_mb": None,
        "process_reserved_mb": None,
        "pid": os.getpid(),
    }

    # ---- 1) torch：进程自己占了多少 + 驱动层 free/total
    try:
        import torch

        if torch.cuda.is_available():
            body["available"] = True
            if device_index is None:
                device_index = torch.cuda.current_device()
                body["index"] = device_index
            try:
                props = torch.cuda.get_device_properties(device_index)
                body["name"] = getattr(props, "name", None)
                body["memory_total_mb"] = _bytes_to_mb(
                    getattr(props, "total_memory", 0))
            except Exception:  # noqa: BLE001
                pass
            try:
                free, total = torch.cuda.mem_get_info(device_index)
                body["memory_total_mb"] = _bytes_to_mb(total)
                body["memory_free_mb"] = _bytes_to_mb(free)
                body["memory_used_mb"] = _bytes_to_mb(total - free)
            except Exception:  # noqa: BLE001
                pass
            try:
                body["process_allocated_mb"] = _bytes_to_mb(
                    torch.cuda.memory_allocated(device_index))
                body["process_reserved_mb"] = _bytes_to_mb(
                    torch.cuda.memory_reserved(device_index))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass

    # ---- 2) NVML：利用率 + 设备名（torch 没给时兜底）
    pynvml = _init_nvml()
    if pynvml is not None:
        try:
            idx = int(device_index or 0)
            handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
            if not body["name"]:
                name = pynvml.nvmlDeviceGetName(handle)
                body["name"] = name.decode() if isinstance(name, bytes) else str(name)
            rates = pynvml.nvmlDeviceGetUtilizationRates(handle)
            body["utilization_pct"] = int(rates.gpu)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            if body["memory_total_mb"] is None:
                body["memory_total_mb"] = _bytes_to_mb(mem.total)
                body["memory_used_mb"] = _bytes_to_mb(mem.used)
                body["memory_free_mb"] = _bytes_to_mb(mem.free)
            body["available"] = True
        except Exception:  # noqa: BLE001
            pass

    # ---- 3) nvidia-smi 兜底：没装 pynvml 时用它拿利用率
    #     （AutoDL 镜像里通常有驱动自带的 nvidia-smi，但没有 pynvml）
    if body["utilization_pct"] is None:
        try:
            import subprocess

            out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,memory.total,name",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3)
            line = (out.stdout or "").strip().splitlines()
            if line:
                parts = [p.strip() for p in line[0].split(",")]
                if len(parts) >= 4:
                    body["utilization_pct"] = int(float(parts[0]))
                    if body["memory_used_mb"] is None:
                        body["memory_used_mb"] = float(parts[1])
                        body["memory_total_mb"] = float(parts[2])
                        body["memory_free_mb"] = round(
                            float(parts[2]) - float(parts[1]), 1)
                    if not body["name"]:
                        body["name"] = parts[3]
                    body["available"] = True
        except Exception:  # noqa: BLE001
            pass

    return body
