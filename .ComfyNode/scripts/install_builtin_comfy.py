# -*- coding: utf-8 -*-
# .ComfyNode/scripts/install_builtin_comfy.py
# 内置 ComfyUI 精简内核引导（可脚本执行 / 可 import 调用）
import io, os, shutil, sys, time

SRC_DEFAULT = r"D:\ComfyUI\ComfyUI_windows_portable\ComfyUI"
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
EXCLUDE = {".git", ".github", ".ci", ".gitignore", "tests", "tests-unit", "models",
           "custom_nodes", "update", "output", "input", "temp", "user",
           "manager_requirements.txt", "new_updater.py", "pyproject.toml",
           "README.md", "LICENSE", "CONTRIBUTING.md", "CODEOWNERS", "QUANTIZATION.md",
           "requirements.txt", "pytest.ini", ".flake8", "script_examples"}
EMPTY_DIRS = ["input", "output", "temp", "user", "custom_nodes", "web"]


def _ignore(d, names):
    return {n for n in names if n in EXCLUDE}


def install(src=None, dst=None):
    """复制 ComfyUI 最小运行集到 .ComfyNode/ComfyUI 并生成 extra_model_paths.yaml，返回 (ok, 说明)"""
    src = src or SRC_DEFAULT
    dst = dst or os.path.join(ROOT, ".ComfyNode", "ComfyUI")
    if not os.path.isdir(src):
        return False, f"未找到源 ComfyUI: {src}"
    t0 = time.time()
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)
    for d in EMPTY_DIRS:
        os.makedirs(os.path.join(dst, d), exist_ok=True)
    for sub in ("diffusion_models", "text_encoders", "vae", "loras", "upscale_models"):
        os.makedirs(os.path.join(ROOT, ".ComfyNode", "models", sub), exist_ok=True)
    os.makedirs(os.path.join(ROOT, ".ComfyNode", "output"), exist_ok=True)
    ep = os.path.join(ROOT, ".ComfyNode", "extra_model_paths.yaml")
    with io.open(ep, "w", encoding="utf-8") as f:
        f.write("flux_painter:\n")
        f.write(f"    base_path: {os.path.join(ROOT, '.ComfyNode', 'models')}\n")
        f.write("    diffusion_models: diffusion_models\n")
        f.write("    text_encoders: text_encoders\n")
        f.write("    vae: vae\n")
        f.write("    loras: loras\n")
        f.write("    upscale_models: upscale_models\n")
    ok = os.path.exists(os.path.join(dst, "main.py")) and os.path.exists(os.path.join(dst, "server.py"))
    return ok, f"内置内核 {dst} 就绪({time.time()-t0:.1f}s)"


def main():
    ok, msg = install()
    print("[完成]" if ok else "[错误]", msg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
