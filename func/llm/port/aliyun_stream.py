import json
from typing import List, Dict, Generator, Optional
import importlib.util

# 尝试导入 dashscope，用于判断是否可用
dashscope_available = importlib.util.find_spec("dashscope") is not None
if dashscope_available:
    import dashscope
    from dashscope import Generation, MultiModalConversation
else:
    dashscope = None
    Generation = None

from openai import OpenAI
from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig


class AliyunStreamLLM:
    """阿里云百炼流式调用（支持 OpenAI 兼容接口和官方 DashScope SDK）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        config = defaultConfig().get_config()
        aliyun_cfg = config.get('llm', {}).get('aliyun', {})
        self.api_key = aliyun_cfg.get('api_key', '')
        self.base_url = aliyun_cfg.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.model = aliyun_cfg.get('model', 'qwen-plus')
        self.temperature = aliyun_cfg.get('temperature', 0.7)
        self.max_tokens = aliyun_cfg.get('max_tokens', 1024)
        self.top_p = aliyun_cfg.get('top_p', 0.9)
        # 是否使用 DashScope SDK（默认为 False，如果为 True 且 dashscope 可用则使用）
        self.use_dashscope = aliyun_cfg.get('use_dashscope', False)

        if not self.api_key:
            self.log.error("阿里云百炼 API Key 未配置")
            self.client = None
            return

        # 初始化 OpenAI 兼容客户端（始终初始化，作为备选）
        try:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            self.log.info(f"阿里云百炼 OpenAI 兼容客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化阿里云百炼 OpenAI 兼容客户端失败: {e}")
            self.client = None

        # 初始化 DashScope（如果启用）
        if self.use_dashscope:
            if not dashscope_available:
                self.log.error("配置使用 DashScope，但 dashscope 库未安装，请执行: pip install dashscope")
                self.use_dashscope = False
            else:
                # 设置基础 URL（官方推荐，确保使用最新服务端点）
                dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"
                # 注意：不再全局设置 api_key，改为在调用时显式传入
                self.log.info("DashScope SDK 初始化成功，基础 URL 已设置")

    def generate_stream(self, messages: List[Dict[str, str]], options: Optional[Dict] = None) -> Generator[str, None, None]:
        """流式生成，根据配置选择后端"""
        if self.use_dashscope and dashscope_available:
            yield from self._generate_stream_dashscope(messages, options)
        else:
            yield from self._generate_stream_openai(messages, options)

    def _generate_stream_openai(self, messages: List[Dict[str, str]], options: Optional[Dict] = None) -> Generator[str, None, None]:
        """使用 OpenAI 兼容接口流式生成"""
        if not self.client:
            self.log.error("阿里云百炼 OpenAI 客户端不可用")
            yield ""
            return

        params = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": options.get("temperature", self.temperature) if options else self.temperature,
            "max_tokens": options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
            "top_p": options.get("top_p", self.top_p) if options else self.top_p,
            "stream_options": {"include_usage": True}
        }
        if options and "enable_thinking" in options:
            params["extra_body"] = {
                "parameters": {
                    "enable_thinking": options["enable_thinking"]
                }
            }

        try:
            response = self.client.chat.completions.create(**params)
            # 打印请求参数（调试用，可关闭）
            safe_params = params.copy()
            safe_params.pop('api_key', None)
            #self.log.info(f"OpenAI 请求参数: {json.dumps(safe_params, ensure_ascii=False)}")

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                #if hasattr(chunk, 'usage') and chunk.usage:
                    #self.log.info(f"本次调用用量: {chunk.usage}")
        except Exception as e:
            self.log.error(f"阿里云百炼流式调用异常: {e}")
            yield ""

    def _generate_stream_dashscope(self, messages: List[Dict[str, str]], options: Optional[Dict] = None) -> Generator[str, None, None]:
        enable_thinking = options.get("enable_thinking", True) if options else True
        try:
            # 关键修改：将 Generation.call 改为 MultiModalConversation.call
            # 同时调整参数名称：去除 result_format，多模态接口默认返回 message 格式
            response = MultiModalConversation.call(
                model=self.model,
                messages=messages,  # 注意：多模态接口的 messages 格式有特定要求（见下文）
                stream=True,
                temperature=options.get("temperature", self.temperature) if options else self.temperature,
                max_tokens=options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
                top_p=options.get("top_p", self.top_p) if options else self.top_p,
                api_key=self.api_key,
                parameters={
                    "enable_thinking": enable_thinking
                }
            )
            # 后续的流式处理逻辑也需要调整，因为多模态接口返回的 chunk 结构不同
            has_content = False
            for chunk in response:
                self.log.info(f"DashScope chunk: {chunk}")
                # 多模态流式输出的内容提取方式（需要根据实际返回结构调整）
                if hasattr(chunk, 'output') and chunk.output and hasattr(chunk.output, 'choices'):
                    choices = chunk.output.choices
                    if choices and len(choices) > 0:
                        message = choices[0].message
                        # 多模态的 content 可能是一个列表，需要遍历提取 text
                        if message and message.content:
                            content_list = message.content
                            if isinstance(content_list, list):
                                for item in content_list:
                                    if item.get('text'):
                                        has_content = True
                                        yield item['text']
                            elif isinstance(content_list, str):
                                has_content = True
                                yield content_list
                if hasattr(chunk, 'usage') and chunk.usage:
                    self.log.info(f"DashScope 用量: {chunk.usage}")

            if not has_content:
                self.log.warning("DashScope 流式返回无内容，生成空字符串")
                yield ""

        except Exception as e:
            self.log.error(f"DashScope 流式调用异常: {e}", exc_info=True)
            yield ""

    def generate(self, messages: List[Dict[str, str]], options: Optional[Dict] = None) -> str:
        """非流式生成，根据配置选择后端"""
        if self.use_dashscope and dashscope_available:
            return self._generate_dashscope(messages, options)
        else:
            return self._generate_openai(messages, options)

    def _generate_openai(self, messages: List[Dict[str, str]], options: Optional[Dict] = None) -> str:
        """使用 OpenAI 兼容接口非流式生成"""
        if not self.client:
            return ""
        params = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": options.get("temperature", self.temperature) if options else self.temperature,
            "max_tokens": options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
            "top_p": options.get("top_p", self.top_p) if options else self.top_p,
        }
        if options and "enable_thinking" in options:
            params["extra_body"] = {
                "parameters": {
                    "enable_thinking": options["enable_thinking"]
                }
            }

        try:
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content
        except Exception as e:
            self.log.error(f"阿里云百炼非流式调用异常: {e}")
            return ""

    def _generate_dashscope(self, messages: List[Dict[str, str]], options: Optional[Dict] = None) -> str:
        """使用 DashScope SDK 非流式生成"""
        enable_thinking = options.get("enable_thinking", True) if options else True
        try:
            response = Generation.call(
                model=self.model,
                messages=messages,
                stream=False,
                result_format='message',
                temperature=options.get("temperature", self.temperature) if options else self.temperature,
                max_tokens=options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
                top_p=options.get("top_p", self.top_p) if options else self.top_p,
                api_key=self.api_key,  # 关键修改：显式传入 API Key
                parameters={
                    "enable_thinking": enable_thinking
                }
            )
            return response.output.choices[0].message.content
        except Exception as e:
            self.log.error(f"DashScope 非流式调用异常: {e}")
            return ""