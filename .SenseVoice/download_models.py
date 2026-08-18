#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
模型下载脚本 - 将 SenseVoice 和声纹模型下载到 localmodels 目录
使用 modelscope 库下载
"""

import os
import sys
from pathlib import Path

# 获取项目根目录（脚本所在目录）
PROJECT_ROOT = Path(__file__).parent.absolute()
MODEL_DIR = PROJECT_ROOT / "localmodels"

# 需要下载的模型列表
MODELS = [
    {
        "name": "SenseVoiceSmall",
        "model_id": "iic/SenseVoiceSmall",
        "revision": "master"
    },
    {
        "name": "speech_campplus_sv_zh-cn_16k-common",
        "model_id": "damo/speech_campplus_sv_zh-cn_16k-common",
        "revision": "master"
    }
]

def install_modelscope_if_needed():
    """尝试安装 modelscope（如果嵌入式环境有 pip）"""
    try:
        import modelscope
        print("modelscope 已安装")
    except ImportError:
        print("正在安装 modelscope...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "modelscope", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"])
        print("modelscope 安装完成")

def download_model(model_id, target_dir, revision="master"):
    """使用 modelscope 下载模型"""
    from modelscope.hub.snapshot_download import snapshot_download
    
    target_path = MODEL_DIR / target_dir
    if target_path.exists():
        print(f"模型 {target_dir} 已存在，跳过下载")
        return
    
    print(f"正在下载 {model_id} -> {target_path} ...")
    snapshot_download(
        model_id,
        cache_dir=str(MODEL_DIR),
        revision=revision,
        local_dir=str(target_path),
    )
    print(f"下载完成: {target_path}")

def main():
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"模型存放目录: {MODEL_DIR}")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    # 尝试安装 modelscope
    install_modelscope_if_needed()
    
    # 下载各个模型
    for model in MODELS:
        download_model(
            model_id=model["model_id"],
            target_dir=model["name"],
            revision=model.get("revision", "master")
        )
    
    print("所有模型下载完成！")
    print(f"请检查目录: {MODEL_DIR}")

if __name__ == "__main__":
    main()