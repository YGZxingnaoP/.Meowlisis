# -*- coding: utf-8 -*-
# func/catpaws/port/gemini.py
from func.catpaws.port.base import CWCatPawsPort, CWPortError


class CWCatPawsGeminiPort(CWCatPawsPort):
    """catpaws 的 Gemini 端口（OpenAI 兼容网关）"""

    provider = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    default_model = "gemini-3.6-flash"
