# -*- coding: utf-8 -*-
# func/catpaws/port/deepseek.py
from func.catpaws.port.base import CWCatPawsPort, CWPortError


class CWCatPawsDeepSeekPort(CWCatPawsPort):
    """catpaws 的 DeepSeek 端口"""

    provider = "deepseek"
    default_base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"
