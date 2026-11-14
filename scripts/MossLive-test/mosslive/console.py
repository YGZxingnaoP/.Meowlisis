# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive/console.py
# 终端输出与事件记录：彩色不需要，时间戳 + 分类前缀即可；
# 每条服务端事件同时写入 sessions/ 下的 JSONL，方便回看协议细节。

import datetime
import json
import sys
import threading
from pathlib import Path


_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}


def _safe_stdout():
    """Windows 控制台默认可能是 GBK，尽量切到 UTF-8，失败则忽略"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class Console:
    """控制台 + JSONL 转录"""

    def __init__(self, level="INFO", sessions_dir=None, save_events=True,
                 verbose_events=False, show_partial=False):
        _safe_stdout()
        self.level = _LEVELS.get(str(level).upper(), 20)
        self.save_events = bool(save_events)
        self.verbose_events = bool(verbose_events)
        self.show_partial = bool(show_partial)
        self.sessions_dir = Path(sessions_dir) if sessions_dir else None
        self._lock = threading.Lock()
        self._file = None
        self._path = None
        self.session_id = ""
        self._started_at = datetime.datetime.now()

    # ---------- 转录文件 ----------

    def start_session(self, session_id: str = ""):
        """创建本次会话的 JSONL 文件（失败时退化为纯控制台）"""
        if self._file:
            return
        self.session_id = session_id or ""
        if not self.save_events or not self.sessions_dir:
            return
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            stamp = self._started_at.strftime("%Y%m%d_%H%M%S")
            suffix = (session_id or "pending")[:12]
            safe = "".join(c for c in suffix if c.isalnum() or c in "-_") or "session"
            self._path = self.sessions_dir / f"{stamp}_{safe}.jsonl"
            self._file = open(self._path, "w", encoding="utf-8")
            self.info(f"事件记录: {self._path}")
        except Exception as e:
            self.warn(f"无法创建事件记录文件，仅输出到终端: {e}")
            self._file = None

    def close(self):
        with self._lock:
            if self._file:
                try:
                    self._file.flush()
                    self._file.close()
                except Exception:
                    pass
                self._file = None

    # ---------- 内部 ----------

    def _ts(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _print(self, tag: str, msg: str):
        with self._lock:
            print(f"[{self._ts()}] {tag} {msg}", flush=True)

    def _write_jsonl(self, obj: dict):
        if not self._file:
            return
        with self._lock:
            try:
                self._file.write(json.dumps(obj, ensure_ascii=False) + "\n")
                self._file.flush()
            except Exception:
                pass

    # ---------- 分级输出 ----------

    def debug(self, msg: str):
        if self.level <= 10:
            self._print("·", msg)

    def info(self, msg: str):
        if self.level <= 20:
            self._print("·", msg)

    def warn(self, msg: str):
        if self.level <= 30:
            self._print("!", msg)

    def error(self, msg: str):
        if self.level <= 40:
            self._print("×", msg)

    # ---------- 对话与事件 ----------

    def user_text(self, text: str, final: bool = True):
        prefix = "用户" if final else "用户~"
        self._print(">", f"{prefix}: {text}")

    def assistant_text(self, text: str, final: bool = True):
        prefix = "喵呜" if final else "喵呜~"
        self._print("<", f"{prefix}: {text}")

    def tool_call(self, name: str, args):
        self._print("T", f"工具调用 {name} {json.dumps(args, ensure_ascii=False)}")

    def tool_result(self, name: str, result: str):
        flat = result.replace("\n", " ")
        if len(flat) > 240:
            flat = flat[:240] + "…"
        self._print("T", f"工具结果 {name}: {flat}")

    def event(self, action: str, data):
        """记录并（可选）打印服务端事件"""
        if self.save_events:
            self._write_jsonl({
                "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
                "kind": "event",
                "action": action,
                "data": data,
            })
        if self.verbose_events:
            flat = json.dumps(data, ensure_ascii=False)
            if len(flat) > 400:
                flat = flat[:400] + "…"
            self._print("E", f"{action} {flat}")

    def note(self, msg: str):
        """写入转录但不打印（给工具/媒体状态用）"""
        self._write_jsonl({
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "kind": "note",
            "text": msg,
        })
