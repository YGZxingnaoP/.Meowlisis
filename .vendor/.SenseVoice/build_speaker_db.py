#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# .SenseVoice/build_speaker_db.py
# 声纹提取工具：遍历 voicetexture/*.wav 提取 CAM++ 声纹向量，写入 speaker_db.json
# 支持 --single 模式：仅提取单个 wav 并追加到声纹库

import os
import sys
import json
import glob
import argparse
import numpy as np


def _to_list(embedding):
    """将声纹 embedding（torch/numpy）转换为 list"""
    import torch
    if torch.is_tensor(embedding):
        embedding = embedding.cpu().numpy()
    embedding = np.asarray(embedding, dtype=np.float32)
    if embedding.ndim == 2 and embedding.shape[0] == 1:
        embedding = embedding[0]
    elif embedding.ndim > 2:
        embedding = embedding.flatten()
    return embedding.astype(np.float32).tolist()


def load_model(model_dir, device):
    """加载 CAM++ 声纹模型"""
    from funasr import AutoModel
    print("正在加载声纹模型...", flush=True)
    model = AutoModel(
        model=model_dir,
        device=device,
        ngpu=1,
        disable_pbar=True,
        disable_log=True,
        disable_update=True,
    )
    print("声纹模型加载完成", flush=True)
    return model


def extract_one(model, wav_path, name):
    """提取单个 wav 的声纹向量，失败返回 None"""
    print(f"提取声纹: {name}", flush=True)
    try:
        res = model.generate(input=wav_path, embedding=True)
        if res and len(res) > 0:
            embedding = res[0].get("spk_embedding")
            if embedding is not None:
                return _to_list(embedding)
        print(f"  提取失败（无 embedding）: {name}", flush=True)
    except Exception as e:
        print(f"  提取异常: {name} - {e}", flush=True)
    return None


def main():
    parser = argparse.ArgumentParser(description="声纹提取工具")
    parser.add_argument("--model_dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "localmodels", "speech_campplus_sv_zh-cn_16k-common"))
    parser.add_argument("--voices_dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "voicetexture"))
    parser.add_argument("--output", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "voicetexture", "speaker_db.json"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--single_name", default=None, help="单文件模式：用户名")
    parser.add_argument("--single_wav", default=None, help="单文件模式：wav 路径")
    args = parser.parse_args()

    device = args.device
    import torch
    if device == "cuda" and not torch.cuda.is_available():
        print("CUDA 不可用，回退到 CPU", flush=True)
        device = "cpu"

    model = load_model(args.model_dir, device)

    # 读取已有声纹库
    db = {}
    if os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                db = json.load(f)
                if not isinstance(db, dict):
                    db = {}
        except Exception:
            db = {}

    if args.single_name and args.single_wav:
        # 单文件模式：追加/覆盖指定用户
        vec = extract_one(model, args.single_wav, args.single_name)
        if vec is not None:
            db[args.single_name] = vec
            print(f"  完成: {args.single_name}", flush=True)
        else:
            print(f"  失败: {args.single_name}", flush=True)
            sys.exit(1)
    else:
        # 全量模式：遍历 voices_dir/*.wav
        wav_files = sorted(glob.glob(os.path.join(args.voices_dir, "*.wav")))
        if not wav_files:
            print("未找到 wav 文件", flush=True)
            sys.exit(0)
        total = len(wav_files)
        for i, wav_path in enumerate(wav_files, 1):
            name = os.path.splitext(os.path.basename(wav_path))[0]
            print(f"[{i}/{total}]", flush=True)
            vec = extract_one(model, wav_path, name)
            if vec is not None:
                db[name] = vec
                print(f"  完成: {name}", flush=True)

    # 写入声纹库
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"声纹库已写入: {args.output}", flush=True)


if __name__ == "__main__":
    main()
