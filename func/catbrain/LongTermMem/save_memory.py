# -*- coding: utf-8 -*-
# func/catbrain/LongTermMem/save_memory.py
# 长期记忆存储：统一落盘入口

import os
import datetime

from func.log.default_log import DefaultLog


class MeowSaveMemory:
    """长期记忆存储类：按日期将内容追加到 character/memory/xxxx-xx-xx.txt

    说明：本文件是长期记忆的唯一存储出口。当前仅实现 LLM 对话存储（save_line），
    日后唱歌模块、故事模块等其它模块的存储逻辑完全不同，但都应在本文件内新增对应
    方法（性质：各自独立落盘、互不影响），保持存储职责统一。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.memory_dir = os.path.join("character", "memory")

    def save_line(self, line: str):
        """存储单行 LLM 对话记录（性质：追加写、按天分文件）"""
        try:
            os.makedirs(self.memory_dir, exist_ok=True)
            day = datetime.date.today().strftime("%Y-%m-%d")
            path = os.path.join(self.memory_dir, f"{day}.txt")
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            self.log.exception("长期记忆写入失败")

    def save_image_line(self, text: str) -> str:
        """存储图片描述（补丁）：用户名标识为「图片」，content 仅【图片】前缀 + 描述。

        返回生成的完整行，供调用方同步缓存到摘要（.temp/record.txt）。
        """
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = str(text or "").replace("\r", " ").replace("\n", " ")
        line = f"[{now}][图片]: 【图片】{content}"
        self.save_line(line)
        return line
