# -*- coding: utf-8 -*-
# server/models.py - ASR 与声纹模型加载

from funasr import AutoModel


def load_asr(args):
    """加载 SenseVoice ASR 模型"""
    return AutoModel(
        model=args.model_dir,
        trust_remote_code=True,
        device=args.device,
        ngpu=args.ngpu,
        ncpu=args.ncpu,
        disable_pbar=True,
        disable_log=False,
        disable_update=True,
    )


def load_sv_model(args):
    """加载 CAM++ 声纹模型"""
    return AutoModel(
        model=args.sv_model,
        device=args.device,
        ngpu=args.ngpu,
        disable_pbar=True,
        disable_log=False,
        disable_update=True,
    )
