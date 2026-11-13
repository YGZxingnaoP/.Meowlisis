# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/dialects/__init__.py
# 绘画工作流方言注册表：每个底模家族一份独立工作流实现，互不干扰
#
# 约定：方言类只负责「怎么织图」（节点、模型名、采样参数、显存相关的开关），
#       连接/提交/轮询/下载等传输逻辑一律留在 comfy_connector/base.py。

from func.toolbox.flux_painter.dialects.anima import AnimaDialect
from func.toolbox.flux_painter.dialects.moss import MossDialect

# 家族名 → 方言实例（实例无状态，可安全共享）
DIALECTS = {
    AnimaDialect.family: AnimaDialect(),
    MossDialect.family: MossDialect(),
}

# 底模文件名关键字 → 家族（顺序敏感：先匹配更具体的）
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
