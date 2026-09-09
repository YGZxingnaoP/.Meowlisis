# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/archive.py
import datetime
import json
import os
import re
import shutil

from func.log.default_log import DefaultLog


class TBPainterArchive:
    """画作归档：character/paints/<日期>_<标题>/ 存 image + meta.json"""

    def __init__(self, backup_dir):
        self.backup_dir = backup_dir
        self.log = DefaultLog().getLogger()

    @staticmethod
    def _safe(name, max_len=40):
        """标题清理为合法文件名片段"""
        s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", str(name or "画")).strip()
        s = re.sub(r"\s+", "_", s)[:max_len]
        return s or "画"

    def save(self, title, src_image, meta=None):
        """把出图复制进 <backup>/<日期时间>_<标题>/ 并写 meta.json，返回 (ok, folder, final_image)"""
        try:
            if not src_image or not os.path.isfile(src_image):
                return False, "", ""
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            folder = os.path.join(self.backup_dir, f"{stamp}_{self._safe(title)}")
            os.makedirs(folder, exist_ok=True)
            ext = os.path.splitext(src_image)[1].lower() or ".png"
            final_image = os.path.join(folder, "image" + ext)
            shutil.copy(src_image, final_image)
            info = dict(meta or {})
            info.update({"title": title, "saved_at": datetime.datetime.now().isoformat(timespec="seconds")})
            with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
            self.log.info(f"[flux_painter] 画作已归档: {folder}")
            return True, folder, final_image
        except Exception:
            self.log.exception("[flux_painter] 画作归档失败")
            return False, "", ""

    def prune(self, keep=0):
        """仅保留最近 keep 个归档目录（0=全部保留）"""
        if keep <= 0 or not os.path.isdir(self.backup_dir):
            return
        try:
            dirs = sorted([os.path.join(self.backup_dir, d) for d in os.listdir(self.backup_dir)
                           if os.path.isdir(os.path.join(self.backup_dir, d))], key=os.path.getmtime)
            for d in dirs[:-keep]:
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            self.log.exception("[flux_painter] 归档清理失败")
