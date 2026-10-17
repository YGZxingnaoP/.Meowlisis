# -*- coding: utf-8 -*-
"""MeowLLM 异常族。所有异常都带 code 与 http_status，可直接映射成响应体里的 meowllm.error。"""

from typing import Any


class MeowLLMError(Exception):
    """所有 MeowLLM 异常的基类。"""

    code: str = "meowllm.error"
    http_status: int = 500

    def __init__(self, message: str = "", *, detail: Any = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.detail = detail

    def to_dict(self) -> dict:
        out: dict = {"code": self.code, "message": self.message}
        if self.detail is not None:
            out["detail"] = self.detail
        return out


class MeowLLMConfigError(MeowLLMError):
    """配置非法（缺字段、越界、引擎不在白名单……）。"""

    code = "meowllm.config_invalid"
    http_status = 500


class MeowLLMSafetyError(MeowLLMError):
    """安全闸门拦截，例如本机试图加载 >1B 模型。"""

    code = "meowllm.safety_blocked"
    http_status = 503


class MeowLLMEngineError(MeowLLMError):
    """引擎加载 / 推理失败。"""

    code = "meowllm.engine_error"
    http_status = 503


class MeowLLMContractError(MeowLLMError):
    """请求不符合契约。"""

    code = "meowllm.contract_invalid"
    http_status = 400
