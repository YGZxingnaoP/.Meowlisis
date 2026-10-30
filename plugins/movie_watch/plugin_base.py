# -*- coding: utf-8 -*-
"""插件本地基线（不 import 主项目任何代码）。

框架只要求：插件对象有 id / trigger_tools / state_decl / setup / teardown，
工具对象有 name / channels / build_schema / handle / route_text / handle_qq / trigger_words。
这些方法都是框架文档化的插件契约，这里用纯 Python 实现一遍，插件可独立拷走。
"""

CHANNEL_MAIN = "main"
CHANNEL_QQ = "qq"
CHANNELS = (CHANNEL_MAIN, CHANNEL_QQ)

# 能力位名称（与框架 PluginsStateBridge 的标准名称一致；这里只用字符串，不引用代码）
CAP_DANMAKU = "danmaku"
CAP_DANMAKU_GIFT = "danmaku_gift"
CAP_REMINDER = "reminder"
CAP_ACTIVE_REPLY = "active_reply"
CAP_TOOLBOX = "toolbox"
CAP_OTHER_TTS = "other_tts"
CAP_VOICE_CHAT = "voice_chat"


class TriggerTool:
    """触发型工具基线（框架按这些成员名做鸭子调用）"""

    name = ""
    description = ""
    parameters = {}
    required = []
    prompt_hint = ""
    trigger_words = ()
    channels = CHANNELS

    def build_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": dict(self.parameters or {}),
                    "required": list(self.required or []),
                },
            },
        }

    def handle(self, arguments, ctx):
        raise NotImplementedError

    def handle_qq(self, arguments, qq_context, ctx):
        raise NotImplementedError

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return False


class InterfaceTool:
    """接口型工具基线（不进 LLM，供内部按名调用）"""

    name = ""
    description = ""

    def call(self, ctx, **kwargs):
        raise NotImplementedError


class ToolboxPlugin:
    """插件基线"""

    id = ""
    title = ""
    version = "1.0.0"
    default_enabled = True

    def trigger_tools(self):
        return []

    def interface_tools(self):
        return []

    def prompt_hint(self):
        return ""

    def state_decl(self):
        return {}

    def setup(self, ctx):
        pass

    def teardown(self):
        pass
