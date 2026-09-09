# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/comfy_port.py
from func.toolbox.flux_painter.comfy_connector.base import TBComfyBase


class TBComfyPort(TBComfyBase):
    """外部模式：把提示词传给用户自建的 ComfyUI 服务并取回图片（不做进程管理）"""

    def __init__(self, config):
        super().__init__(config)
        self._warned = False

    def ensure_ready(self):
        """探测外部服务是否可达，返回 (ok, 说明)"""
        if self.health():
            return True, f"外部 ComfyUI 在线: {self.base_url()}"
        if not self._warned:
            self._warned = True
            self.log.warning(f"[flux_painter] 外部 ComfyUI 不可达: {self.base_url()}")
        return False, f"外部 ComfyUI 不可达: {self.base_url()}（请先启动它，模型需含 anima_baseV10 系列）"
