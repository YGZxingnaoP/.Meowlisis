# -*- coding: utf-8 -*-
import json

from func.log.default_log import DefaultLog
from func.toolbox.flux_painter.config import TBFluxPainterConfig

class TBRoleResolver:
    """点名角色解析：characters.json 单一真源。"""

    _DOC = None

    def __init__(self, config=None):
        """记录配置与日志。"""
        self.log = DefaultLog().getLogger()
        self.config = config or TBFluxPainterConfig()

    def _path(self):
        """characters.json 路径（跟 prompt_reference 目录走）。"""
        import os
        base = str(getattr(self.config, "prompt_reference_dir", "") or "").strip()
        if not base:
            base = ".vendor/.ComfyNode/prompt_reference"
        return os.path.join(base, "characters.json")

    def _load(self):
        """惰性载入并按「中文名 / 别名 / 英文名」建索引。"""
        if TBRoleResolver._DOC is not None:
            return TBRoleResolver._DOC
        try:
            doc = json.load(open(self._path(), encoding="utf-8"))
        except Exception:
            self.log.warning("[flux_painter] characters.json 读取失败: %s" % self._path())
            doc = {"characters": []}
        index = {}
        for item in doc.get("characters") or []:
            if not isinstance(item, dict) or not item.get("name_en"):
                continue
            for key in [item.get("name"), item.get("name_en")] + list(item.get("aliases") or []):
                k = str(key or "").strip().lower()
                if k and k not in index:
                    index[k] = item
        TBRoleResolver._DOC = (doc, index)
        return TBRoleResolver._DOC

    def resolve(self, character, allow_net=False):
        """查一个角色：返回条目 dict（含 name_en / series / tag）或 None。"""
        key = str(character or "").strip().lower()
        if not key:
            return None
        _doc, index = self._load()
        item = index.get(key)
        if item is None:
            for k, v in index.items():
                if k and k in key:
                    item = v
                    break
        if item is None:
            return None
        card = dict(item)
        card["known"] = True
        return card

    def resolve_from_text(self, text, allow_net=False):
        """从一句需求里找最长命中的角色名/别名。"""
        raw = str(text or "")
        if not raw:
            return None
        low = raw.lower()
        _doc, index = self._load()
        best_key = ""
        for k in index.keys():
            if k and k in low and len(k) > len(best_key):
                best_key = k
        return self.resolve(best_key) if best_key else None

    def card_text(self, card, limit=420):
        """把条目拼成给提示词模型的参考文本（只有 tag，没有外观描述）。"""
        if not card:
            return ""
        parts = ["角色：%s（%s）" % (card.get("name"), card.get("name_en"))]
        if card.get("series"):
            parts.append("作品 tag：%s" % card["series"])
        if card.get("tag"):
            parts.append("角色 tag：%s" % card["tag"])
        return "\n".join(parts)[:limit]
