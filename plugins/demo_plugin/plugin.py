from func.pipeline.plugins_state import (CAP_ACTIVE_REPLY, CAP_DANMAKU, CAP_VOICE_CHAT,
                                         PluginsStateBridge)
from func.toolbox.plugins.sdk import (CHANNEL_MAIN, CHANNEL_QQ, InterfaceTool, ToolboxPlugin,
                                      TriggerTool)


class DemoHelloTool(TriggerTool):
    name = "demo_hello"
    description = ("演示插件工具：仅在用户明确说「演示插件打招呼/让演示插件问好」时调用。"
                   "其它任何情况一律不调用。")
    parameters = {
        "name": {"type": "string", "description": "要问候的名字，可省略"},
        "loud": {"type": "boolean", "description": "是否大声问候，默认 false"},
    }
    required = []
    prompt_hint = "- 用户说「演示插件打招呼」→ 调用 demo_hello。"
    trigger_words = ("演示插件打招呼", "让演示插件问好")
    channels = (CHANNEL_MAIN, CHANNEL_QQ)

    def handle(self, arguments, ctx):
        args = arguments or {}
        who = args.get("name") or "主人"
        loud = "！！" if args.get("loud") else "～"
        text = f"你好呀，{who}{loud}这是来自演示插件的问候。"
        ctx.tts().send_stream(text, source="toolbox_demo")
        return text

    def handle_qq(self, arguments, qq_context, ctx):
        who = (arguments or {}).get("name") or "主人"
        text = f"你好呀，{who}～这是来自演示插件的问候。"
        target = str(qq_context.get("target_id") or qq_context.get("user_id") or "")
        if str(qq_context.get("message_type", "")) == "group":
            ctx.napcat().send_group_text(target, text)
        else:
            ctx.napcat().send_private_text(target, text)
        return text

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return False


class DemoStateTool(TriggerTool):
    name = "demo_state"
    description = "演示插件状态接口：进入/更新/退出插件状态（仅调试用）。"
    parameters = {
        "mode": {"type": "string", "enum": ["enter", "update", "exit", "query"],
                 "description": "enter=进入状态，update=临时放开语音闲聊，exit=退出，query=查询"},
    }
    required = ["mode"]

    def handle(self, arguments, ctx):
        mode = str((arguments or {}).get("mode") or "query")
        handle = ctx.state()
        bridge = PluginsStateBridge()
        if mode == "enter":
            handle.enter()
        elif mode == "update":
            handle.update(**{CAP_VOICE_CHAT: True})
        elif mode == "exit":
            handle.exit()
        return (f"active={handle.is_active()} "
                f"danmaku={bridge.allow(CAP_DANMAKU)} "
                f"voice_chat={bridge.allow(CAP_VOICE_CHAT)} "
                f"active_reply={bridge.allow(CAP_ACTIVE_REPLY)} "
                f"owner(danmaku)={bridge.owner(CAP_DANMAKU)!r} "
                f"snapshot={bridge.snapshot()}")


class DemoEchoTool(InterfaceTool):
    name = "demo_echo"
    description = "演示接口型工具：把传入文本原样返回并写入短期记忆。"

    def call(self, ctx, text="", remember=False, **kwargs):
        text = str(text or "")
        if remember and text:
            ctx.short_memory().save(
                {"role": "assistant", "content": f"【演示】{text}", "type": "demo_plugin"},
                10, trim_mode="items")
        ctx.log.info(f"[demo_echo] {text}")
        return text


class Plugin(ToolboxPlugin):
    id = "demo_plugin"
    title = "演示插件"
    version = "2.0.0"
    default_enabled = False

    def trigger_tools(self):
        return [DemoHelloTool(), DemoStateTool()]

    def interface_tools(self):
        return [DemoEchoTool()]

    def prompt_hint(self):
        return "- 演示插件：用户说「演示插件打招呼」时调用 demo_hello。"

    def state_decl(self):
        return {"title": "演示中",
                "caps": {CAP_DANMAKU: False, CAP_ACTIVE_REPLY: False}}

    def setup(self, ctx):
        self.ctx = ctx
        self.log = ctx.log
        self.config = ctx.config
        self.log.info(f"演示插件已初始化，配置项 {len(self.config)} 个")

    def teardown(self):
        self.ctx = None


PLUGIN = Plugin()
