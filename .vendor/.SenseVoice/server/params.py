# -*- coding: utf-8 -*-
# server/params.py - 命令行参数解析

import argparse
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_parser():
    """构造命令行参数解析器"""
    p = argparse.ArgumentParser()
    p.add_argument("--host", type=str, default="0.0.0.0")
    p.add_argument("--port", type=int, default=10095)
    p.add_argument("--model_dir", type=str,
                   default=os.path.join(PROJECT_ROOT, "localmodels", "SenseVoiceSmall"))
    p.add_argument("--device", type=str, default="cuda")
    p.add_argument("--ngpu", type=int, default=1)
    p.add_argument("--ncpu", type=int, default=4)
    p.add_argument("--sv_model", type=str,
                   default=os.path.join(PROJECT_ROOT, "localmodels", "speech_campplus_sv_zh-cn_16k-common"))
    p.add_argument("--speaker_db_path", type=str,
                   default=os.path.join(PROJECT_ROOT, "voicetexture", "speaker_db.json"))
    p.add_argument("--sv_threshold", type=float, default=0.2)
    p.add_argument("--speaker_db_reload_sec", type=int, default=5)
    p.add_argument("--worker_threads", type=int, default=4)
    p.add_argument("--concurrent_asr", type=int, default=4)
    p.add_argument("--concurrent_sv", type=int, default=2)
    p.add_argument("--latency_log", type=str, default=None, help="延迟观测事件文件路径（可选）")
    return p
