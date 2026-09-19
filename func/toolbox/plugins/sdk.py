class PluginContext:
    def __init__(self, plugin_id, log, config):
        """插件上下文：承载插件运行时依赖"""
        self.id = plugin_id
        self.log = log
        self.config = config or {}

    def tts(self):
        """返回 TTS 语音桥接"""
        from func.pipeline.toolbox_tts import ToolboxTtsBridge
        return ToolboxTtsBridge()

    def llm(self):
        """返回 toolbox LLM 端口实例"""
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)

    def prompt(self):
        """返回角色提示词获取器"""
        from func.toolbox.get_prompt import TBoxGetPrompt
        return TBoxGetPrompt()

    def napcat(self):
        """返回 QQ 发送入口"""
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        return TBNapCatCore()

    def short_memory(self):
        """返回短期记忆桥接"""
        from func.pipeline.short_memory import ShortMemory
        return ShortMemory()

    def ltmem(self):
        """返回长期/用户记忆桥接"""
        from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
        return MeowLLMLtMemBridge()

    def excuse(self):
        """返回通用询问器"""
        from func.toolbox.excuse import TBExcuse
        return TBExcuse()

    def toolbox(self):
        """返回 toolbox 总入口"""
        from func.toolbox.toolbox_core import TBoxCore
        return TBoxCore()

    def ai_name(self):
        """返回 AI 名字"""
        from func.config.app_config import AppConfig
        return AppConfig().ai_name

    def state(self):
        """返回本插件状态句柄（标准接口）：enter() / update(**caps) / exit()

        能力位由插件自身的 state_decl() 声明，插件无需 import 框架内部单例。
        """
        from func.pipeline.plugins_state import PluginStateHandle
        decl = {}
        try:
            from func.toolbox.plugins.manager import PluginManager
            decl = PluginManager().state_decl(self.id)
        except Exception:
            self.log.exception("读取插件状态声明失败")
        return PluginStateHandle(self.id, decl, self.log)


class TriggerTool:
    name = ""
    description = ""
    parameters = {}
    required = []
    prompt_hint = ""
    trigger_words = ()
    username = ""
    context = {}

    def build_schema(self):
        """生成 OpenAI function schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": list(self.required),
                },
            },
        }

    def handle(self, arguments, ctx):
        """语音链路执行"""
        raise NotImplementedError

    def handle_qq(self, arguments, qq_context, ctx):
        """QQ 链路执行，默认回退语音实现"""
        return self.handle(arguments, ctx)

    def route_text(self, text, username=""):
        """语音/弹幕会话拦截，返回 True 表示已接管（默认不接管）"""
        return False

    def set_username(self, username):
        """注入当前用户名"""
        self.username = username or ""

    def set_context(self, context):
        """注入调用上下文"""
        self.context = context or {}


class InterfaceTool:
    name = ""
    description = ""

    def call(self, ctx, **kwargs):
        """按名调用执行"""
        raise NotImplementedError


class ToolboxPlugin:
    id = ""
    title = ""
    version = "1.0.0"
    default_enabled = True

    def trigger_tools(self):
        """返回触发型工具列表"""
        return []

    def interface_tools(self):
        """返回接口型工具列表"""
        return []

    def prompt_hint(self):
        """返回意图分析引导文案"""
        return ""

    def state_decl(self):
        """声明本插件「进入状态」时的能力占用（标准接口）；返回 {} 表示无状态。

        返回格式：
        {
          "title": "读书中",                     # 展示名（日志 / GUI）
          "caps": {CAP_DANMAKU: False, ...},     # 能力位，未列出的沿用默认 True
          "meta": {...},                         # 可选附加信息
        }
        """
        return {}

    def setup(self, ctx):
        """插件初始化"""
        pass

    def teardown(self):
        """插件卸载清理"""
        pass
