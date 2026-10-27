# -*- coding: utf-8 -*-
# func/catpaws/port/aliyun.py
from func.catpaws.port.base import CWCatPawsPort, CWPortError


class CWCatPawsAliyunPort(CWCatPawsPort):
    """catpaws 的 Qwen（阿里云）端口"""

    provider = "aliyun"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model = "qwen-plus"
