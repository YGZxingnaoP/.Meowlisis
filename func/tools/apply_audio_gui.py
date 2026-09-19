# -*- coding: utf-8 -*-
# func/tools/apply_audio_gui.py
# 音频采集面板补充项：给「基本设置-音频采集」加上重采样质量与原生采样率开关

import os
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUI_BASIC_JS = os.path.join(BASE_DIR, "gui", "js", "config", "basic.js")

# 锚点：音频采集面板最后一项（分块大小）
ANCHOR = "            this._num('分块大小(ms)', 'audio.chunk_size_ms', 300, 50, 500, 10);"

BLOCK = """            this._num('分块大小(ms)', 'audio.chunk_size_ms', 300, 50, 500, 10) +
            this._section('采集与重采样') +
            this._check('优先按目标采样率打开设备（免重采样）', 'audio.prefer_native_rate', false,
                '设备支持时跳过重采样；若人声变调请关闭') +
            this._select('重采样质量', 'audio.resample_converter', [
                { value: 'sinc_best', label: 'sinc_best（最高质量）' },
                { value: 'sinc_medium', label: 'sinc_medium（推荐）' },
                { value: 'sinc_fastest', label: 'sinc_fastest（最省 CPU）' },
                { value: 'linear', label: 'linear' },
                { value: 'zero_order_hold', label: 'zero_order_hold' },
            ], 'sinc_medium', '仅当设备采样率不等于上方采样率时生效');"""


def _backup(path: str):
    """写入前备份原文件（带时间戳）"""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(path, "r", encoding="utf-8") as f:
        data = f.read()
    with open(f"{path}.bak_{stamp}", "w", encoding="utf-8") as f:
        f.write(data)


def patch_gui() -> list:
    """给音频面板补充重采样相关输入项，返回改动描述"""
    if not os.path.isfile(GUI_BASIC_JS):
        return [f"找不到 {GUI_BASIC_JS}"]
    with open(GUI_BASIC_JS, "r", encoding="utf-8") as f:
        text = f.read()
    if "resample_converter" in text:
        return ["已存在，跳过"]
    if ANCHOR not in text:
        return ["未匹配到锚点，跳过（basic.js 结构可能已变）"]
    text = text.replace(ANCHOR, BLOCK, 1)
    _backup(GUI_BASIC_JS)
    with open(GUI_BASIC_JS, "w", encoding="utf-8") as f:
        f.write(text)
    return ["音频面板新增「优先按目标采样率打开设备」与「重采样质量」"]


def main():
    """执行补丁并打印结果"""
    print("[basic.js]", patch_gui())


if __name__ == "__main__":
    main()
