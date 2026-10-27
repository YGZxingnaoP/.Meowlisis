from cw.port.base import CWPort, CWPortError


class CWMeowLLMPort(CWPort):
    """MeowLLM 端口（本地子服务，OpenAI 兼容，多几个请求字段）"""

    provider = "meowllm"
    default_base_url = "http://127.0.0.1:18100/meowllm/v1"
    default_model = "meowllm-local"

    def anonymous(self):
        return True

    def build_params(self, messages, tools=None, tool_choice="auto", model=None,
                     temperature=None, max_tokens=None):
        params = super().build_params(messages, tools, tool_choice, model, temperature, max_tokens)
        params["top_p"] = float(self.options.get("top_p") or 0.9)
        block = {}
        level = str(self.options.get("thinking_level") or "").strip()
        if level:
            block["thinking_level"] = level
        params["extra_body"] = {
            "top_k": int(self.options.get("top_k") or 40),
            "repeat_penalty": float(self.options.get("repeat_penalty") or 1.05),
            "meowllm": block,
        }
        return params
