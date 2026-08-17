# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/get_userrecord.py
# 用户消息轮次记录：.temp/用户名_record.txt，首行为轮次计数

import os
import re
import threading

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowGetUserRecord:
    """用户记录类：按用户记录对话（含上下文），首行计数该用户发送的消息数"""

    # 首行轮次计数格式（仅统计该用户发送的消息数）
    COUNT_PREFIX = "#rounds:"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.temp_dir = ".temp"
        self._lock = threading.Lock()

    @staticmethod
    def _safe_name(username: str) -> str:
        """清洗用户名为安全文件名（去除路径分隔等非法字符，空值回退为“空格”）"""
        if not username:
            return "空格"
        name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', str(username))
        return name.strip() or "空格"

    def _path(self, username: str) -> str:
        """返回指定用户名的记录文件路径"""
        return os.path.join(self.temp_dir, f"{self._safe_name(username)}_record.txt")

    def record_message(self, username: str, line: str, is_user: bool):
        """记录一条消息：用户消息计数+1，达到配置轮数返回 True（触发更新）"""
        os.makedirs(self.temp_dir, exist_ok=True)
        path = self._path(username)
        with self._lock:
            lines = self._read_lines(path)
            count, body_start = self._parse_count(lines)
            if is_user:
                count += 1
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.COUNT_PREFIX + str(count) + "\n")
                    f.writelines(lines[body_start:])
                    f.write(line + "\n")
            except Exception:
                self.log.exception(f"用户记录写入失败: {path}")
                return False
            return is_user and count >= self.config.user_update_rounds

    def init_record(self, username: str, line: str):
        """新用户首条消息初始化记录（计数为1，供猜测建档后延续计数）"""
        os.makedirs(self.temp_dir, exist_ok=True)
        path = self._path(username)
        with self._lock:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.COUNT_PREFIX + "1\n")
                    f.write(line + "\n")
            except Exception:
                self.log.exception(f"用户记录初始化失败: {path}")

    def take_content(self, username: str):
        """取出记录正文与计数并清空（返回(正文, 计数)，无内容时返回空）"""
        path = self._path(username)
        with self._lock:
            lines = self._read_lines(path)
            count, body_start = self._parse_count(lines)
            content = "".join(lines[body_start:])
            if content.strip():
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(self.COUNT_PREFIX + "0\n")
                except Exception:
                    self.log.exception(f"清空用户记录失败: {path}")
                    return "", 0
            return content, count

    def restore_content(self, username: str, content: str, count: int):
        """更新失败时把正文写回记录，避免丢数据"""
        path = self._path(username)
        with self._lock:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.COUNT_PREFIX + str(count) + "\n")
                    f.write(content)
            except Exception:
                self.log.exception(f"用户记录写回失败: {path}")

    def _read_lines(self, path: str) -> list:
        """读取记录文件全部行（不存在时返回空列表）"""
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.readlines()
        except Exception:
            self.log.exception(f"读取用户记录失败: {path}")
            return []

    def _parse_count(self, lines: list):
        """解析首行轮次计数，返回(计数值, 正文起始行索引)"""
        if lines and lines[0].startswith(self.COUNT_PREFIX):
            try:
                return int(lines[0][len(self.COUNT_PREFIX):].strip()), 1
            except ValueError:
                pass
        return 0, 0
