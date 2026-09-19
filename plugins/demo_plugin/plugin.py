# -*- coding: utf-8 -*-
"""演示插件：本项目插件框架「全部标准接口」的调用示例。

==================== 目录与加载 ====================
plugins/<插件id>/
    plugin.py     必填：导出 PLUGIN（或 Plugin 类）
    schema.py     可选：PLUGIN 元信息 + FIELDS（GUI 配置项）
    config.yml    自动生成：插件独立配置（按 schema 默认值补全）
    card.png      可选：GUI 卡片图

加载流程（func/toolbox/plugins/manager.py）：
    discover() 发现目录 → load(pid) 导入 plugin.py → ensure_config() 补全配置
    → PluginContext(pid, log, cfg) → plugin.setup(ctx) → registry.add(plugin, ctx)

注册后的两条链路：
    触发型工具：能被主 LLM 当 function 调用（build_schema），也支持关键词硬触发、
               会话拦截、QQ 链路
    接口型工具：不进 LLM，供项目内部按名调用

==================== 注意 ====================
本插件默认关闭（default_enabled = False），不会参与线上运行；
要看效果把 plugins/demo_plugin/config.yml 里 enabled 改成 true（仅调试用）。
"""

from func.toolbox.plugins.sdk import ToolboxPlugin, TriggerTool, InterfaceTool


# ============================================================================
# 一、触发型工具（TriggerTool）—— 完整接口
# ============================================================================
class DemoHelloTool(TriggerTool):
    # ---------- 元信息：会组成 OpenAI function schema 交给主 LLM ----------
    name = "demo_hello"                    # 工具名（必须全局唯一）
    description = (
        "演示插件工具：仅在用户明确说「演示插件打招呼/让演示插件问好」时调用，"
        "其它任何情况一律不调用。"
    )
    parameters = {                          # JSON Schema properties
        "name": {"type": "string", "description": "要问候的名字，可省略"},
        "loud": {"type": "boolean", "description": "是否大声问候，默认 false"},
    }
    required = []                           # 必填参数名列表

    # ---------- 两种「非 LLM」触发通道 ----------
    prompt_hint = "- 用户说「演示插件打招呼」→ 调用 demo_hello。"   # 追加到意图分析提示词
    trigger_words = ("演示插件打招呼", "让演示插件问好")             # 关键词硬触发（命中即调用，不经 LLM）

    # ---------- 语音 / 弹幕链路 ----------
    def handle(self, arguments, ctx):
        """arguments=LLM 或 match_keyword 给的参数；返回值会写进日志「执行结果」"""
        args = arguments or {}
        who = args.get("name") or "主人"
        loud = "！！" if args.get("loud") else "～"
        text = f"你好呀，{who}{loud}这是来自演示插件的问候。"
        ctx.tts().send_stream(text, source="toolbox_demo")     # 出声；source 用于隔离来源
        return text

    # ---------- QQ 链路（不实现则默认回退到 handle） ----------
    def handle_qq(self, arguments, qq_context, ctx):
        """qq_context 形如 {message_type, user_id, target_id, group_id, group_name, ...}"""
        who = (arguments or {}).get("name") or "主人"
        text = f"你好呀，{who}～这是来自演示插件的问候。"
        target = str(qq_context.get("target_id") or qq_context.get("user_id") or "")
        if str(qq_context.get("message_type", "")) == "group":
            ctx.napcat().send_group_text(target, text)
        else:
            ctx.napcat().send_private_text(target, text)
        return text

    # ---------- 会话拦截（语音/弹幕输入进 LLM 之前先过这里） ----------
    def route_text(self, text, username=""):
        """返回 True = 本工具已接管该输入，不再走后续 LLM 分析/回复链路。

        适合做「播报中打断」「窗口内续读」这类有状态的会话。
        原则：除明确指令外不要接管，否则会吞掉用户的正常对话。
        """
        return False

    # ---------- 框架会自动注入的上下文（也可自己用） ----------
    def set_username(self, username):
        """框架在每次调用前注入当前说话人（默认实现已存到 self.username）"""
        super().set_username(username)

    def set_context(self, context):
        """框架注入显式上下文 {username, text, short_memory, system_prompt}"""
        super().set_context(context)


# ============================================================================
# 二、插件状态（标准接口）：让框架其它模块为你让位
# ============================================================================
class DemoStateTool(TriggerTool):
    name = "demo_state"
    description = "演示插件状态接口：进入/更新/退出插件状态（仅调试用）。"
    parameters = {
        "mode": {"type": "string", "enum": ["enter", "update", "exit", "query"],
                 "description": "enter=进入状态，update=临时放开语音闲聊，exit=退出，query=查询"},
    }
    required = ["mode"]

    def handle(self, arguments, ctx):
        """ctx.state() 返回本插件的状态句柄：enter() / update(**caps) / exit() / is_active()

        能力位来自 Plugin.state_decl()，插件不用 import 框架内部单例；
        enter/exit 幂等，可在任意异常路径重复调用。
        """
        from func.pipeline.plugins_state import (CAPS, CAP_DANMAKU, CAP_VOICE_CHAT,
                                                CAP_ACTIVE_REPLY, PluginsStateBridge)
        mode = str((arguments or {}).get("mode") or "query")
        handle = ctx.state()
        bridge = PluginsStateBridge()

        if mode == "enter":
            handle.enter()                                   # 用 state_decl 的声明
        elif mode == "update":
            handle.update(**{CAP_VOICE_CHAT: True})           # 运行中临时调整某一位
        elif mode == "exit":
            handle.exit()
        # 框架侧查询（谁都可以问）
        return (f"active={handle.is_active()} "
                f"danmaku={bridge.allow(CAP_DANMAKU)} "
                f"voice_chat={bridge.allow(CAP_VOICE_CHAT)} "
                f"active_reply={bridge.allow(CAP_ACTIVE_REPLY)} "
                f"owner(danmaku)={bridge.owner(CAP_DANMAKU)!r} "
                f"snapshot={bridge.snapshot()}")


# ============================================================================
# 三、接口型工具（InterfaceTool）—— 不进 LLM，供内部按名调用
# ============================================================================
class DemoEchoTool(InterfaceTool):
    name = "demo_echo"
    description = "演示接口型工具：把传入文本原样返回并写入短期记忆。"

    def call(self, ctx, text="", remember=False, **kwargs):
        """调用方式：PluginManager().call_interface("demo_echo", text="你好", remember=True)"""
        text = str(text or "")
        if remember and text:
            ctx.short_memory().save(
                {"role": "assistant", "content": f"【演示】{text}", "type": "demo_plugin"},
                10, trim_mode="items")
        ctx.log.info(f"[demo_echo] {text}")
        return text


# ============================================================================
# 四、PluginContext 全部接口速查（在工具里通过参数 ctx 拿到）
# ============================================================================
#
#   ctx.id                       插件 id
#   ctx.log                      logger（ctx.log.info / .exception）
#   ctx.config                   本插件 config.yml 的 dict
#
#   ctx.tts().send_stream(text, source="toolbox_xxx", emotion=None)   # 出声
#   ctx.tts().is_busy() / .interrupt()                                # 是否在播 / 打断
#   ctx.llm()                    toolbox LLM 端口：.chat(messages, tools=None) / .chat_stream(...)
#                                （可用性判断：getattr(ctx.llm(), "client", None)）
#   ctx.prompt().get_system_prompt(username, current_message)         # 完整角色提示词
#   ctx.prompt().get_tool_prompt(username, current_message)           # 工具分析用提示词
#   ctx.napcat().send_private_text(user_id, text) / .send_group_text(group_id, text)
#   ctx.napcat().send_group_file(group_id, path) / .call_action_sync(action, params)
#   ctx.short_memory().save({"role","content","type"}, max_rounds, trim_mode="rounds"|"items")
#   ctx.short_memory().load()                                         # [{"role","content"}]
#   ctx.ltmem().record_ai_message(username, ai_name, content)         # 长期/用户记忆
#   ctx.excuse().ask("问什么", username, timeout=25)                   # 阻塞追问，返回文本或 None
#   ctx.toolbox()                 toolbox 总入口：.receive(text, username) 可把文本送回分析链路
#   ctx.ai_name()                 AI 名字
#   ctx.state()                   插件状态句柄：enter() / update(**caps) / exit() / is_active()
#
#   异步任务模式（docwriter 的做法）：
#       handle() 里开 threading.Thread(daemon=True) 后台跑，
#       完成后用 ToolboxLLMBridge().send_to_llm(信号, username, source="toolbox")
#       把「完成信号」交回主链路 LLM 出话。


# ============================================================================
# 五、插件本体：生命周期与注册
# ============================================================================
class Plugin(ToolboxPlugin):
    id = "demo_plugin"              # 必须与目录名一致
    title = "演示插件"
    version = "1.0.0"
    default_enabled = False         # 无 config 时的默认开关

    def trigger_tools(self):
        """返回触发型工具实例列表（会注册到 LLM / 关键词 / 会话拦截 / QQ 四条链路）"""
        return [DemoHelloTool(), DemoStateTool()]

    def interface_tools(self):
        """返回接口型工具实例列表（只登记名称，供 call_interface 按名调用）"""
        return [DemoEchoTool()]

    def prompt_hint(self):
        """追加到主 LLM 的意图分析提示词（决定它什么时候调你的工具）"""
        return "- 演示插件：用户说「演示插件打招呼」时调用 demo_hello。"

    def state_decl(self):
        """声明「进入插件状态」时要占用/禁用的框架能力位（返回 {} = 无状态）

        能力位常量见 func/pipeline/plugins_state.py：
            CAP_DANMAKU / CAP_DANMAKU_GIFT / CAP_REMINDER / CAP_ACTIVE_REPLY
            CAP_TOOLBOX / CAP_OTHER_TTS / CAP_VOICE_CHAT
        未列出的沿用默认 True；多插件同时占用时逐位取「与」。
        """
        try:
            from func.pipeline.plugins_state import CAP_DANMAKU, CAP_ACTIVE_REPLY
            return {"title": "演示中",
                    "caps": {CAP_DANMAKU: False, CAP_ACTIVE_REPLY: False}}
        except Exception:
            return {}

    def setup(self, ctx):
        """插件加载时调用一次：保存 ctx、初始化内部资源"""
        self.ctx = ctx
        self.log = ctx.log
        self.config = ctx.config
        self.log.info(f"演示插件已初始化，配置项 {len(self.config)} 个")

    def teardown(self):
        """插件卸载时调用：停线程、关连接等清理"""
        pass


PLUGIN = Plugin()
