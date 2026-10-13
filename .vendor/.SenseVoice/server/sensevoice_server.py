#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# server/sensevoice_server.py - 入口：解析参数 → 加载模型 → 启动服务

import asyncio

from params import build_parser
from models import load_asr, load_sv_model
from runtime import Runtime
from service import serve


def main():
    """加载模型并启动 WebSocket 识别服务"""
    args = build_parser().parse_args()
    ctx = Runtime(args)
    print("正在加载 SenseVoice 模型...")
    ctx.asr = load_asr(args)
    print("SenseVoice 模型加载完成")
    print("正在加载声纹模型...")
    ctx.sv_model = load_sv_model(args)
    print("声纹模型加载完成")
    try:
        asyncio.run(serve(ctx))
    finally:
        ctx.shutdown()


if __name__ == "__main__":
    main()
