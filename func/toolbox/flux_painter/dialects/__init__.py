# -*- coding: utf-8 -*-

from func.toolbox.flux_painter.dialects.anima import AnimaDialect
from func.toolbox.flux_painter.dialects.moss import MossDialect

DIALECTS = {
    AnimaDialect.family: AnimaDialect(),
    MossDialect.family: MossDialect(),
}

_KEYS = (
    ("moss", "moss"),
    ("anima", "anima"),
    ("miaomiao", "anima"),
)

def family_of(unet_name: str) -> str:
    """按底模文件名推断家族；认不出时按 anima 处理（存量配置都是 anima）"""
    name = str(unet_name or "").lower()
    for key, family in _KEYS:
        if key in name:
            return family
    return "anima"

def resolve_family(unet_name: str, override: str = "auto") -> str:
    """最终家族：显式指定优先，否则按底模名推断"""
    want = str(override or "auto").strip().lower()
    if want in DIALECTS:
        return want
    return family_of(unet_name)

def get_dialect(family: str):
    """取方言实例（未知家族回退 anima）"""
    return DIALECTS.get(str(family or "").strip().lower()) or DIALECTS["anima"]
