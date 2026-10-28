# -*- coding: utf-8 -*-
# func/toolbox/analysis.py
# 父级 toolcalls：注册触发型工具，由 AI 决策参数与 start

import json
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig


class TBoxAnalysis:
    """父级 toolcalls 分析类：维护模块入口注册表，AI 决策选择并开启模块"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.llm = None
        self._tools = {}
        # 当前用户名（decide 时注入，供模块使用）
        self.current_meowid = ""
        self._register_modules()

    def _register_modules(self):
        """注册父级「动作入口」（只暴露模块级入口，不暴露 QQ 链路内部子工具）

        父级决策是单轮链路（只执行第一个工具调用、结果不回灌），因此只允许注册
        「一次调用即完成」的动作入口；取好友/群/群成员列表这类只读工具属于 QQ 链路
        内部子工具，只在模块内部触发，一律不注册到父级。
        """
        # NapCat 主动发送（父级 QQ 入口之一：发消息）
        # 主动发送关闭时不暴露入口，避免模型调用一个必然失败的模块。
        try:
            from func.toolbox.napcat.config import TBNapCatConfig
            if TBNapCatConfig().active_send_enabled:
                from func.toolbox.napcat.active_sender.module import TBNapcatActiveModule
                napcat = TBNapcatActiveModule()
                for tool_schema in napcat.build_tools():
                    name = tool_schema.get("function", {}).get("name")
                    if name:
                        self.register(name, napcat)
            else:
                self.log.info("主动发送未启用，父级不暴露 napcat_send")
        except Exception:
            self.log.exception("注册 NapCat 主动发送模块失败")

        # 视觉模块触发
        try:
            from func.toolbox.meowvision.vision_core import TBVisionCore
            vision = TBVisionCore()
            for tool_schema in vision.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, vision)
        except Exception:
            self.log.exception("注册视觉模块失败")

        # 天气查询模块
        try:
            from func.toolbox.weather.weather_core import TBWeatherCore
            weather = TBWeatherCore()
            for tool_schema in weather.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, weather)
        except Exception:
            self.log.exception("注册天气查询模块失败")

        # 新闻查询模块
        try:
            from func.toolbox.news.news_core import TBNewsCore
            news = TBNewsCore()
            for tool_schema in news.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, news)
        except Exception:
            self.log.exception("注册新闻查询模块失败")

        # 弹幕主动发送模块
        try:
            from func.toolbox.danmaku.active_sender.active_sender import TBDanmakuActive
            danmaku_active = TBDanmakuActive()
            for tool_schema in danmaku_active.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, danmaku_active)
        except Exception:
            self.log.exception("注册弹幕主动发送模块失败")

        # 新建待办模块
        try:
            from func.toolbox.add_backlog.add_tool import TBAddBacklogTool
            add_backlog = TBAddBacklogTool()
            for tool_schema in add_backlog.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, add_backlog)
        except Exception:
            self.log.exception("注册新建待办模块失败")

        # 即兴哼唱模块
        try:
            from func.toolbox.meowsongs.meowsongs_core import TBMeowSongsCore
            meowsongs = TBMeowSongsCore()
            for tool_schema in meowsongs.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, meowsongs)
        except Exception:
            self.log.exception("注册即兴哼唱模块失败")

        # 听歌识曲接龙模块
        try:
            from func.toolbox.meowsongs.pass_the_baton.pass_the_baton import TBPassTheBaton
            pass_the_baton = TBPassTheBaton()
            for tool_schema in pass_the_baton.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, pass_the_baton)
        except Exception:
            self.log.exception("注册听歌识曲接龙模块失败")

        # 海龟汤模块
        try:
            from func.toolbox.turtle_soup.turtle_soup_core import TBTurtleSoupCore
            turtle_soup = TBTurtleSoupCore()
            for tool_schema in turtle_soup.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, turtle_soup)
        except Exception:
            self.log.exception("注册海龟汤模块失败")

        # Flux 绘画模块（AI 文生图：flux_paint）
        try:
            from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
            painter = TBFluxPainterCore()
            for tool_schema in painter.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, painter)
        except Exception:
            self.log.exception("注册 Flux 绘画模块失败")

        # 群机器人指令入口（如幻梦）
        try:
            from func.toolbox.napcat.groupchat.ask_group_bot_entry import TBAskGroupBotEntry
            bot_entry = TBAskGroupBotEntry()
            for tool_schema in bot_entry.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, bot_entry)
        except Exception:
            self.log.exception("注册群机器人指令入口失败")

        try:
            from func.toolbox.plugins.manager import PluginManager
            PluginManager().register_into(self)
        except Exception:
            self.log.exception("注册插件模块失败")

    def _ensure_llm(self):
        """懒加载 toolbox 独立 LLM 客户端"""
        if self.llm is None:
            if self.config.llm_type == "meowllm":
                from func.toolbox.port.meowllm import TBoxMeowLLM
                self.llm = TBoxMeowLLM()
            elif self.config.llm_type == "gemini":
                from func.toolbox.port.gemini import TBoxGeminiLLM
                self.llm = TBoxGeminiLLM()
            elif self.config.llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                self.llm = TBoxAliyunLLM()
            else:
                from func.toolbox.port.deepseek import TBoxDeepSeekLLM
                self.llm = TBoxDeepSeekLLM()
        return self.llm

    # QQ 链路内部子工具名：出现即说明有人把子工具注册到了父级，会导致父级出现
    # 「取列表」与「发消息」同级、串联必然失败，直接拒绝。
    SUBTOOL_BLOCKLIST = (
        "get_friend_list", "get_group_list", "get_group_member_list",
        "get_group_member_info", "search_file", "check_link",
    )

    def register(self, name: str, tool):
        """注册一个动作入口到父级 toolcalls 注册表（子工具一律拒绝）"""
        if name in self.SUBTOOL_BLOCKLIST or str(name).startswith("send_qq_"):
            self.log.error(f"[父级工具] 拒绝注册子工具 {name}："
                           f"只读/底层发送只允许在 QQ 链路内部触发")
            return
        self._tools[name] = tool

    def build_tools(self) -> List[Dict]:
        """构建父级模块入口的工具定义（只暴露模块级入口，不暴露模块内部子工具）"""
        schemas = []
        seen_tools = set()
        for tool in self._tools.values():
            if id(tool) in seen_tools:
                continue
            seen_tools.add(id(tool))
            if hasattr(tool, "build_tools"):
                schemas.extend(tool.build_tools())
        return schemas

    def pre_route_plan(self, text: str, meowid: str):
        self.current_meowid = meowid
        try:
            from func.toolbox.plugins.manager import PluginManager
            pm = PluginManager()
            if pm.route_text(text, meowid):
                self.log.info(f"插件会话拦截: {(text or '')[:30]}")
                return ("", {})
            hit = pm.match_keyword(text)
            if hit:
                return hit
        except Exception:
            self.log.exception("插件会话/关键词处理失败")
        if self._vision_rule_hit(text):
            return ("use_vision", {"user_message": text})
        if self._paint_rule_hit(text):
            return ("flux_paint", {"request": text, "topic": "规则硬触发绘画"})
        return None

    def pre_route(self, text: str, meowid: str) -> bool:
        plan = self.pre_route_plan(text, meowid)
        if plan is None:
            return False
        name, arguments = plan
        if not name:
            return True
        context = {"meowid": meowid, "text": text,
                   "short_memory": self._load_short_memory(), "system_prompt": ""}
        result = self.dispatch(name, arguments, meowid, context)
        self.log.info(f"父级 toolcalls 规则硬触发 {name}: {(text or '')[:30]} -> {result}")
        return True

    def decide(self, text: str, meowid: str):
        """接收输入内容：先走本地规则硬触发（视觉），未命中再由 AI 决定是否调用工具。
        """
        self.current_meowid = meowid
        if self.pre_route(text, meowid):
            return

        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("父级 toolcalls LLM 不可用")
            return

        from func.toolbox.get_prompt import TBoxGetPrompt
        base_prompt = TBoxGetPrompt().get_tool_prompt(meowid, text) or ""
        history_messages = self._load_short_memory()
        # 显式上下文：身份编号 + 短记忆 + 角色提示词，供 flux_painter 等工具通过 set_context 接收
        dispatch_context = {"meowid": meowid, "text": text,
                            "short_memory": history_messages,
                            "system_prompt": base_prompt}

        try:
            from func.toolbox.plugins.manager import PluginManager
            plugin_hint = PluginManager().prompt_hint()
        except Exception:
            plugin_hint = ""

        from func.pipeline.system_prompt import SystemPromptBridge
        system_prompt = (
            f"{base_prompt}\n\n"
            f"{SystemPromptBridge().get_tool_hint_prompt(plugin_hint)}"
        )
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history_messages)
        messages.append({"role": "user", "content": text})

        resp = llm.chat(messages, tools=self.build_tools(), tool_choice="auto")
        if not resp or not resp.choices:
            self.log.warning("父级 toolcalls 无响应")
            return

        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            self.log.info("父级 toolcalls 未调用工具，静默")
            return

        # 只取第一个工具，避免一次多工具并发冲突
        tc = tool_calls[0]
        self.handle_tool_calls(
            [{"name": tc.function.name, "arguments": tc.function.arguments}],
            meowid, text, dispatch_context)

    def handle_tool_calls(self, calls: List[Dict], meowid: str, text: str = "",
                          context: Dict = None):
        """接收 LLM 分析出的工具调用并执行对应模块（快速回复直接选择工具时由桥接调用）。

        calls：归一化后的工具调用列表 [{"name": 工具名, "arguments": 参数(原始字符串或 dict)}]
        context：可选的显式上下文，缺省时自行构建（短记忆 + 角色提示词）
        """
        if not calls:
            return
        self.current_meowid = meowid
        name = str(calls[0].get("name") or "")
        if not name:
            return
        arguments = calls[0].get("arguments")
        if isinstance(arguments, str) or arguments is None:
            try:
                args = json.loads(arguments or "{}")
            except Exception:
                self.log.exception(f"解析工具参数失败: {name}")
                args = {}
        else:
            args = arguments
        if context is None:
            context = {"meowid": meowid, "text": text,
                       "short_memory": self._load_short_memory(), "system_prompt": ""}
            try:
                from func.toolbox.get_prompt import TBoxGetPrompt
                context["system_prompt"] = TBoxGetPrompt().get_tool_prompt(meowid, text) or ""
            except Exception:
                pass
        self.log.info(f"父级 toolcalls 命中工具 {name}: {(text or '')[:20]}")
        result = self.dispatch(name, args, meowid, context)
        self.log.info(f"父级工具 {name} 执行结果: {result}")

    # ==================== 规则硬触发层 ====================
    # 视觉规则触发词表：命中即强制看屏幕（确定性高频需求，不依赖 LLM 自觉）
    VISION_RULE_WORDS = (
        "看屏幕", "看一下屏幕", "看看屏幕", "看下屏幕", "看一眼屏幕", "看着屏幕",
        "看画面", "看一下画面", "看看画面", "看下画面", "看图片", "看我在做什么",
        "看看我在", "看我玩", "看我打", "陪我打游戏", "陪我看", "盯屏幕",
        "盯着屏幕", "盯着看", "盯住", "长期观察", "定期汇报", "截个图", "截图",
        "屏幕上", "屏幕里", "屏幕", "帮我看看屏幕", "你看到了吗", "你看屏幕",
        "现在看屏幕", "看下我", "use_vision",
    )

    def _vision_rule_hit(self, text: str) -> bool:
        """本地规则硬触发判断：用户文本命中视觉意图词即返回 True（零 LLM）"""
        t = (text or "").strip()
        if not t:
            return False
        return any(w in t for w in self.VISION_RULE_WORDS)

    # 绘画规则触发词表：命中即强制开画（确定性高频需求，与视觉同理不依赖 LLM 自觉）
    PAINT_RULE_WORDS = (
        # 带量词/动词的明确点单（画X）
        "画一幅", "画一张", "画个", "画张", "画一个", "画一只", "画一条", "画一棵",
        "画一朵", "画朵", "画一座", "画一栋", "画一下", "画一画",
        "画点", "画张图", "画幅画", "画张画", "画张涩图", "画张瑟图",
        # 高频口语（画图/画画/重画）
        "画图", "画画", "重画", "再画", "重新画", "画个图", "去画", "画画看",
        # 使役请求
        "帮我画", "给我画", "替我画", "给咱画", "给我来张", "帮我出张", "帮我整张",
        "想让你画", "你画个", "给我整张",
        # 要图/来图
        "来张", "来幅", "来一张", "来一幅", "来点图", "来张图", "来张涩图", "来张色图",
        "要一张", "要张图", "想要一张", "想要张图", "想要张", "要张涩图",
        # 生成/出图/涩图直呼
        "生成一张图", "生成张图", "生成图片", "文生图", "出张图", "出图",
        "涩图", "瑟图", "色图", "整张图",
    )

    def _paint_rule_hit(self, text: str) -> bool:
        """本地规则硬触发判断：用户文本命中绘画意图词即返回 True（零 LLM）"""
        t = (text or "").strip()
        if not t:
            return False
        return any(w in t for w in self.PAINT_RULE_WORDS)

    def _load_short_memory(self, limit: int = 6) -> List[Dict]:
        """加载最近短期记忆（供工具分析理解上下文），返回 OpenAI messages 列表"""
        try:
            from func.pipeline.short_memory import ShortMemory
            records = ShortMemory().load()
            # 去掉 type 后只剩 role/content，取最近 limit 条
            return [{"role": m["role"], "content": m["content"]} for m in records[-limit:]]
        except Exception:
            self.log.exception("工具分析加载短期记忆失败")
            return []

    def dispatch(self, tool_name: str, arguments: Dict, meowid: str = None,
                 context: Dict = None):
        """按模块入口名与参数执行对应模块。

        context：显式上下文 {meowid, text, short_memory, system_prompt}，
        meowid 是被调用者的**内部编号**（身份标准），昵称只用于展示；
        供需要「短记忆 + 角色提示词」的工具（如 flux_painter）通过 set_context 接收；
        未实现 set_context 的既有工具完全不受影响（向后兼容）。
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return f"错误：未知模块入口 {tool_name}"
        if meowid and hasattr(tool, "set_meowid"):
            try:
                tool.set_meowid(meowid)
            except Exception:
                pass
        if context and hasattr(tool, "set_context"):
            try:
                tool.set_context(context)
            except Exception:
                self.log.exception(f"注入上下文失败: {tool_name}")
        if hasattr(tool, "dispatch"):
            return tool.dispatch(tool_name, arguments or {})
        return None
