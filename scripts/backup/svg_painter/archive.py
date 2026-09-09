# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/archive.py
# SVG 绘画存档：
# - 进行中的会话建在 .temp/svg_paint/<ts_主题>/（每笔版本 + meta.json + 思考记录）
# - 会话结束（用户喊停/收工）才整体归档进 character/svg_paints/<ts_主题>/
# - 提供跨 temp/character 两处检索"最近画作"供新一轮读档

import os
import re
import json
import shutil
import threading
from datetime import datetime

from func.log.default_log import DefaultLog


class TBSvgPainterArchive:
    """画作档案管理（临时态 + 完工归档）"""

    def __init__(self, backup_dir=None, temp_dir=None):
        self.log = DefaultLog().getLogger()
        # 完工归档目录（长期）
        self.backup_dir = backup_dir or os.path.join("character", "svg_paints")
        # 进行中临时会话目录（.temp）
        self.temp_dir = temp_dir or os.path.join(".temp", "svg_paint")
        self._lock = threading.RLock()   # 可重入锁：_write_meta 等内部会再取锁，避免嵌套自锁死锁
        for d in (self.backup_dir, self.temp_dir):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                self.log.exception(f"创建绘画目录失败: {d}")

    # ==================== 目录/命名 ====================
    @staticmethod
    def _safe_topic(topic: str) -> str:
        s = re.sub(r'[\\/:*?"<>|\s]+', "_", (topic or "")).strip("_")
        return (s or "untitled")[:40]

    def session_dir_name(self, topic: str) -> str:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{ts}_{self._safe_topic(topic)}"

    def _meta_path(self, session_dir: str) -> str:
        return os.path.join(session_dir, "meta.json")

    # ==================== 列表/读取 ====================
    def list_dirs(self, base: str):
        """返回某根目录下会话文件夹（新→旧）"""
        result = []
        try:
            names = sorted(os.listdir(base), reverse=True)
        except OSError:
            return result
        for name in names:
            full = os.path.join(base, name)
            if os.path.isdir(full) and os.path.exists(self._meta_path(full)):
                result.append(full)
        return result

    def latest_session_dirs(self):
        """temp + character 全部会话（新→旧，temp 进行中优先展示在最前）"""
        return self.list_dirs(self.temp_dir) + self.list_dirs(self.backup_dir)

    def read_meta(self, session_dir: str) -> dict:
        try:
            with open(self._meta_path(session_dir), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def read_final(self, session_dir: str) -> str:
        """读取会话最终 svg；无 final 则回退到最大版本号文件"""
        final = os.path.join(session_dir, "final.svg")
        if os.path.exists(final):
            try:
                with open(final, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return ""
        try:
            files = [x for x in os.listdir(session_dir) if re.match(r"^\d{4}_", x) and x.endswith(".svg")]
            files.sort(reverse=True)
            if files:
                with open(os.path.join(session_dir, files[0]), "r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            pass
        return ""

    def latest_any_final(self):
        """跨 temp/character 找最近一次画作的 final.svg 文本（无则空串），供"接着/修改旧画"读档"""
        for d in self.latest_session_dirs():
            svg = self.read_final(d)
            if svg:
                return svg
        return ""

    def latest_any_meta(self) -> dict:
        """跨 temp/character 找最近一次会话 meta（无则 {}）"""
        dirs = self.latest_session_dirs()
        if not dirs:
            return {}
        return self.read_meta(dirs[0]) or {}

    # ==================== 写入（临时会话） ====================
    def _write_meta(self, meta: dict):
        with self._lock:
            try:
                with open(self._meta_path(meta["session_dir"]), "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                self.log.exception("绘画 meta 写入失败")

    def create_temp_session(self, username: str, request: str, topic: str = "",
                            intent: str = "new", model: str = "") -> dict:
        """在 .temp 建会话：目录 + meta.json；返回 meta（同秒重名自动加后缀保证唯一）"""
        with self._lock:
            name = self.session_dir_name(topic)
            session_dir = os.path.join(self.temp_dir, name)
            i = 2
            while os.path.exists(session_dir):
                name = f"{self.session_dir_name(topic)}-{i}"
                session_dir = os.path.join(self.temp_dir, name)
                i += 1
            os.makedirs(session_dir, exist_ok=False)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta = {
            "session_dir": session_dir,
            "name": name,
            "created": now,
            "username": username or "",
            "request": request or "",
            "topic": topic or "",
            "intent": intent,
            "model": model or "",
            "status": "painting",
            "archived": False,
            "thinking": [],
            "tools": [],
            "versions": [],
            "final": "",
        }
        self._write_meta(meta)
        return meta

    def add_thinking(self, meta: dict, text: str):
        t = (text or "").strip()
        if not t:
            return
        meta.setdefault("thinking", []).append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "text": t,
        })
        self._write_meta(meta)

    def add_tool(self, meta: dict, name: str, args, result: str):
        meta.setdefault("tools", []).append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,
            "args": args if isinstance(args, (dict, list, str)) else str(args),
            "result": (result or "")[:2000],
        })
        self._write_meta(meta)

    def save_version(self, meta: dict, svg_text: str, note: str = "") -> str:
        """把当前完整 svg 存为 000N_<ts>.svg（写入 meta.session_dir），登记版本号"""
        index = len(meta.get("versions", [])) + 1
        ts = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3]
        fname = f"{index:04d}_{ts}.svg"
        path = os.path.join(meta["session_dir"], fname)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg_text)
        except Exception:
            self.log.exception("绘画版本保存失败")
            return ""
        meta.setdefault("versions", []).append({
            "index": index,
            "file": fname,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": note or "",
        })
        self._write_meta(meta)
        return path

    def finish_temp(self, meta: dict, final_svg: str, summary: str = ""):
        """收笔：在临时会话目录写 final.svg 并把 meta 置 finished（暂不归档，等会话结束）"""
        try:
            path = os.path.join(meta["session_dir"], "final.svg")
            with open(path, "w", encoding="utf-8") as f:
                f.write(final_svg)
        except Exception:
            self.log.exception("绘画 final.svg 写入失败")
        meta["final"] = "final.svg"
        meta["status"] = "finished"
        meta["summary"] = summary or ""
        meta["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write_meta(meta)

    # ==================== 完工归档（.temp → character） ====================
    def archive_session(self, meta: dict) -> str:
        """绘画会话结束：把整个临时目录搬进 character/svg_paints（返回归档目录，失败返回空串）"""
        src = meta.get("session_dir", "")
        if not src or not os.path.isdir(src):
            return ""
        try:
            # 未收笔（中断/直接结束）先补 final
            final = os.path.join(src, "final.svg")
            if not os.path.exists(final):
                files = [x for x in os.listdir(src) if re.match(r"^\d{4}_", x) and x.endswith(".svg")]
                files.sort(reverse=True)
                if files:
                    shutil.copy(os.path.join(src, files[0]), final)
            dest = os.path.join(self.backup_dir, meta.get("name") or self.session_dir_name(meta.get("topic")))
            if os.path.exists(dest):
                dest = os.path.join(self.backup_dir,
                                    f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{self._safe_topic(meta.get('topic'))}")
            shutil.move(src, dest)
            meta["session_dir"] = dest
            meta["archived"] = True
            meta["archived_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._write_meta(meta)
            self.log.info(f"[svg_painter] 画作已归档: {dest}")
            return dest
        except Exception:
            self.log.exception("[svg_painter] 画作归档失败")
            return ""

    def flush_finished_temp(self):
        """会话结束时调用：把 .temp 下所有「已收笔(finished) 且未归档」的临时会话全部搬进 character。
        绘画激活期每轮修改都会新建一个临时会话，收工时统一把中间轮次一并归档，避免残留 .temp。"""
        for d in self.list_dirs(self.temp_dir):
            meta = self.read_meta(d)
            if meta.get("status") == "finished" and not meta.get("archived"):
                meta["session_dir"] = d
                self.archive_session(meta)

    def prune(self, keep: int):
        """归档目录仅保留最近 keep 个会话（keep<=0 全保留）；临时目录不清理（由结束归档移走）"""
        if keep <= 0:
            return
        for d in self.list_dirs(self.backup_dir)[keep:]:
            try:
                shutil.rmtree(d, ignore_errors=True)
                self.log.info(f"[svg_painter] 清理旧画作: {os.path.basename(d)}")
            except Exception:
                self.log.exception("清理旧绘画会话失败")
