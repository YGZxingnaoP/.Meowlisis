from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.review.config import MeowMemoryReviewConfig


class MeowMemoryReviewLLM:
    def __init__(self):
        """按配置创建记忆审查客户端，未单独配置时复用摘要后端"""
        self.log = DefaultLog().getLogger()
        self.config = MeowMemoryReviewConfig()
        self.cat = MeowCatBrainConfig()
        self._inner = self._create()
        self.client = self._inner.client if self._inner else None

    def _create(self):
        """按类型创建内层客户端并按需覆盖密钥与模型"""
        llm_type = self.config.llm_type or self.cat.abstract_llm_type
        if llm_type == "meowllm":
            from func.catbrain.AbstractMem.port.meowllm import MeowAbstractMeowLLM
            llm = MeowAbstractMeowLLM()
        elif llm_type == "gemini":
            from func.catbrain.AbstractMem.port.gemini import MeowAbstractGeminiLLM
            llm = MeowAbstractGeminiLLM()
        elif llm_type == "aliyun":
            from func.catbrain.AbstractMem.port.aliyun import MeowAbstractAliyunLLM
            llm = MeowAbstractAliyunLLM()
        else:
            from func.catbrain.AbstractMem.port.deepseek import MeowAbstractDeepSeekLLM
            llm = MeowAbstractDeepSeekLLM()
        if self.config.api_key:
            llm.api_key = self.config.api_key
            llm.base_url = self.config.base_url or llm.base_url
            llm.model = self.config.model or llm.model
            llm.max_tokens = self.config.max_tokens
            try:
                from openai import OpenAI
                llm.client = OpenAI(api_key=llm.api_key, base_url=llm.base_url)
            except Exception as e:
                self.log.error(f"初始化记忆审查客户端失败: {e}")
                llm.client = None
        return llm

    def chat(self, messages, tools=None, tool_choice=None):
        """非流式对话，转发到内层客户端"""
        if not self._inner:
            return None
        return self._inner.chat(messages, tools=tools, tool_choice=tool_choice)
