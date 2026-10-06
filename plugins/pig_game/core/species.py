# -*- coding: utf-8 -*-
"""养猪游戏：猪种注册表。

猪种 = **一个资源文件夹**（定义 + 材质在一起，不堆在别处）：

    assets/
      super_fat/
        species.json     ← 这个猪种的全部配置（JSON，直接改）
        image.png        ← 卡片横幅 + QQ 附图
        icon.png         ← 预留小图标
      flying/  fish/  gudu/
      _template/         ← 新猪种模板（_ 开头不加载）
      scene/             ← 场景图，没有 species.json，不会被当猪种

本模块只负责：扫描 assets/*/species.json → 装载 → 查询。
"""

import json
import os

SPECIES_FILE = "species.json"


class SpeciesBook:
    """猪种表：装载 / 查询 / 按名或别名解析。"""

    def __init__(self, assets_dir=None):
        self.assets_dir = assets_dir or ""
        self.items = []
        self.by_id = {}
        self.load()

    # ---------- 装载 ----------
    def load(self):
        """扫描 assets/*/species.json（按文件夹名排序），忽略 _ 开头的文件夹。"""
        items = []
        if self.assets_dir and os.path.isdir(self.assets_dir):
            for name in sorted(os.listdir(self.assets_dir)):
                if name.startswith("_") or name.startswith("."):
                    continue
                path = os.path.join(self.assets_dir, name, SPECIES_FILE)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        sp = json.load(f)
                except Exception:
                    continue
                if not isinstance(sp, dict):
                    continue
                sp.setdefault("id", name)          # 没写 id 就用文件夹名
                if sp.get("id"):
                    items.append(sp)
        self.items = items
        self.by_id = {str(s["id"]): s for s in self.items}

    # ---------- 查询 ----------
    def all(self):
        return self.items

    def get(self, sid):
        return self.by_id.get(str(sid or ""))

    def name(self, sid):
        s = self.by_id.get(str(sid or ""))
        return s["name"] if s else str(sid)

    def dir_of(self, sid):
        """该猪种的资源文件夹（绝对路径），没有返回 None。"""
        s = self.by_id.get(str(sid or ""))
        if s and self.assets_dir:
            p = os.path.join(self.assets_dir, str(s["id"]))
            if os.path.isdir(p):
                return p
        return None

    def asset(self, sid, key="image"):
        """显式覆盖路径（一般不需要写）；默认约定见 view/render.py。"""
        s = self.by_id.get(str(sid or "")) or {}
        return ((s.get("assets") or {}).get(key) or "").strip() or None

    def is_magic(self, sid):
        s = self.by_id.get(str(sid or ""))
        return bool(s and s.get("type") == "magic")

    def magic_ids(self):
        return [s["id"] for s in self.items if s.get("type") == "magic"]

    def stealable_ids(self):
        return [s["id"] for s in self.items if s.get("stealable")]

    def tradable_ids(self):
        return [s["id"] for s in self.items if s.get("tradable")]

    def resolve(self, text):
        """按名称 / 别名 / 包含关系解析猪种 id，找不到返回 None。"""
        t = str(text or "").strip()
        if not t:
            return None
        for s in self.items:
            if t == s["name"] or t == str(s["id"]):
                return str(s["id"])
        for s in self.items:
            for a in (s.get("aliases") or []):
                if t == str(a):
                    return str(s["id"])
        best = None
        for s in self.items:
            for nm in [s["name"], str(s["id"])] + list(s.get("aliases") or []):
                nm = str(nm)
                if nm and nm in t and (best is None or len(nm) > len(best[1])):
                    best = (str(s["id"]), nm)
        return best[0] if best else None
