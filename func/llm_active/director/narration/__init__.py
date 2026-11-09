# -*- coding: utf-8 -*-
# func/llm_active/director/narration/__init__.py
# 导演侧 narration 统一从主实现导入，避免再维护一份逐字复制件。

from .narration_core import NarrationCore

__all__ = ["NarrationCore"]
