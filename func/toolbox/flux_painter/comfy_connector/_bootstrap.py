# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/_bootstrap.py
# 内置内核引导：复制最小运行集到 .ComfyNode/ComfyUI，
# models/output 用 junction 直接指向 .ComfyNode（免 extra_model_paths/输出参数），失败则回退 yaml。
import json
import os
import shutil
import subprocess
import time

SRC_DEFAULT = r"D:\ComfyUI\ComfyUI_windows_portable\ComfyUI"
EXCLUDE = {".git", ".github", ".ci", ".gitignore", "tests", "tests-unit", "models",
           "custom_nodes", "update", "output", "input", "temp", "user", "web",
           "manager_requirements.txt", "new_updater.py", "pyproject.toml",
           "README.md", "LICENSE", "CONTRIBUTING.md", "CODEOWNERS", "QUANTIZATION.md",
           "requirements.txt", "pytest.ini", ".flake8", "script_examples"}
EMPTY_DIRS = ["input", "temp", "user", "custom_nodes"]
MODEL_SUBS = ["diffusion_models", "text_encoders", "vae", "loras", "upscale_models"]
CFG_FILE = "comfyui_builtin.json"


def _cfg_path(config):
    """内置状态文件路径"""
    return os.path.join(config.comfy_node_dir, CFG_FILE)


def _load_cfg(config):
    """读内置状态，缺失返回 None"""
    try:
        with open(_cfg_path(config), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cfg(config, data):
    """写内置状态"""
    with open(_cfg_path(config), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _make_junction(link, target):
    """Windows 目录联接（无需管理员），成功返回 True"""
    try:
        if os.path.lexists(link):
            if os.path.islink(link) or os.path.isdir(link):
                return True
            os.rmdir(link)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def _write_extra_yaml(config):
    """回退方案：extra_model_paths.yaml（模型/输出指向 .ComfyNode）"""
    models = os.path.join(config.comfy_node_dir, "models")
    ep = os.path.join(config.comfy_node_dir, "extra_model_paths.yaml")
    with open(ep, "w", encoding="utf-8") as f:
        f.write("flux_painter:\n")
        f.write(f"    base_path: {models}\n")
        for s in MODEL_SUBS:
            f.write(f"    {s}: {s}\n")
    return ep


def _link_resources(config, dst):
    """用 junction 把 models/output 指到 .ComfyNode（同盘时最简），返回 True"""
    models_dir = os.path.join(config.comfy_node_dir, "models")
    os.makedirs(models_dir, exist_ok=True)
    ok = True
    for s in MODEL_SUBS:
        target = os.path.join(models_dir, s)
        os.makedirs(target, exist_ok=True)
        if not _make_junction(os.path.join(dst, "models", s), target):
            ok = False
    out = os.path.join(config.comfy_node_dir, "output")
    os.makedirs(out, exist_ok=True)
    out_link = os.path.join(dst, "output")
    if os.path.isdir(out_link) and not os.path.islink(out_link):
        shutil.rmtree(out_link, ignore_errors=True)
    if not _make_junction(out_link, out):
        ok = False
    return ok


def ensure_installed(config):
    """内置内核缺失则安装（幂等），补齐 junction 并写状态，返回 (ok, 说明)"""
    dst = os.path.join(config.comfy_node_dir, "ComfyUI")
    main_py = os.path.join(dst, "main.py")
    fresh = False
    if not os.path.isfile(main_py):
        src = SRC_DEFAULT
        if not os.path.isdir(src):
            return False, f"未找到源 ComfyUI: {src}（内置模式需在 D:\\ComfyUI 有便携版，或改用外部模式）"
        t0 = time.time()
        if os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
        os.makedirs(dst, exist_ok=True)

        def _ignore(d, names):
            return {n for n in names if n in EXCLUDE}

        shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)
        for d in EMPTY_DIRS:
            os.makedirs(os.path.join(dst, d), exist_ok=True)
        os.makedirs(os.path.join(dst, "models"), exist_ok=True)
        fresh = True
    junction_ok = _link_resources(config, dst)
    cfg = {"junction": junction_ok, "main": main_py,
           "extra_yaml": os.path.join(config.comfy_node_dir, "extra_model_paths.yaml")}
    if not junction_ok:
        _write_extra_yaml(config)
    _save_cfg(config, cfg)
    note = f"内置内核 {'已安装' if fresh else '已就绪'}（模型/输出 junction={'成功' if junction_ok else '回退extra'}）"
    return True, note
