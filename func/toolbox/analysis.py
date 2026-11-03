# -*- coding: utf-8 -*-
# func/toolbox/analysis.py
# 父级 toolcalls：注册触发型工具，由 AI 决策参数与 start

import json
import re
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
            from func.toolbox.port import create_toolbox_llm
            self.llm = create_toolbox_llm(self.config)
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
        # 说「qq发消息」必然触发，但发消息 / @谁 / 指挥幻梦由角色自己选：
        # 不再无条件派 napcat_send（那样会吞掉 mention，也永远轮不到 napcat_ask_bot）
        if self._qq_send_rule_hit(text):
            plan = self._choose_qq_tool(text)
            if plan:
                return plan
            if "napcat_send" in self._tools:
                self.log.warning("QQ 工具选择没选出来，兜底 napcat_send（目标/内容交给模块内部解析）")
                return ("napcat_send", {"request": text})
        if self._vision_rule_hit(text):
            return ("use_vision", {"user_message": text})
        if self._paint_rule_hit(text):
            return ("flux_paint", {"request": text, "topic": "规则硬触发绘画"})
        return None

    # ==================== QQ 工具选择（必然触发 + 角色选择） ====================
    # 只认「qq发消息」「QQ发消息」，命中后由角色在下面两个工具里二选一
    QQ_SEND_RULE_WORDS = ("qq发消息", "QQ发消息")
    QQ_CHOICE_TOOLS = ("napcat_send", "napcat_ask_bot")
    QQ_CHOICE_PROMPT = (
        "你在替角色决定「用哪个工具」满足主人这句话，只做工具选择，不要写回复正文。\n"
        "- napcat_send：替主人发消息 / 文件 / 链接给好友或群；要 @ 谁就把名字填进 mention。\n"
        "- napcat_ask_bot：指挥群里的机器人（如幻梦）执行指令（今日老婆 / 打卡 / 运势…）。\n"
        "判断依据是真实目的：让群机器人做事就选 napcat_ask_bot，绝不要用 napcat_send 在群里发一句话代替；"
        "只是把内容发给某人/某群才选 napcat_send。必须调用其中一个工具。"
    )

    def _qq_send_rule_hit(self, text: str) -> bool:
        """本地规则硬触发判断：命中「qq发消息」即必然触发（但不在此处决定用哪个工具）"""
        t = (text or "").strip().lower()
        if not t:
            return False
        return any(w.lower() in t for w in self.QQ_SEND_RULE_WORDS)

    def _known_groups(self, limit: int = 12):
        """给工具选择用的真实群名（填 group_name 必须一字不差照抄，否则解析不到）"""
        try:
            from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList
            rows = TBGetGroupList().get() or []
        except Exception:
            self.log.exception("读取群列表失败（本次选择不带群名提示）")
            return []
        names = []
        for row in rows:
            name = str((row or {}).get("group_name") or "").strip()
            if name and name not in names:
                names.append(name)
        return names[:limit]

    def _qq_choice_schemas(self):
        """参与选择的两个父级入口 schema（只取已注册的）"""
        schemas = []
        for name in self.QQ_CHOICE_TOOLS:
            tool = self._tools.get(name)
            if tool is None:
                continue
            try:
                for schema in tool.build_tools():
                    if schema.get("function", {}).get("name") == name:
                        schemas.append(schema)
            except Exception:
                self.log.exception(f"读取工具定义失败: {name}")
        return schemas

    def _qq_choice_system(self) -> str:
        """选择提示词 + 真实群名（模型照抄群名，解析才不会失败）"""
        text = self.QQ_CHOICE_PROMPT
        groups = self._known_groups()
        if groups:
            text += ("\n可用的群（group_name / target 必须从下面一字不差照抄一个，"
                     "用户说的群名可能少了几个字）：" + "、".join(groups))
        return text

    def _choose_qq_tool(self, text: str):
        """让角色在 napcat_send / napcat_ask_bot 里选一个，返回 (name, arguments) 或 None。

        用 tool_choice="required" 强制选（模型不配合时退回 auto 再试一次），
        参数走容错解析，mention / command 不会被畸形 JSON 吞掉。
        """
        llm = self._ensure_llm()
        if llm is None or not getattr(llm, "client", None):
            return None
        schemas = self._qq_choice_schemas()
        if not schemas:
            return None
        messages = [
            {"role": "system", "content": self._qq_choice_system()},
            {"role": "user", "content": str(text or "")},
        ]
        for tool_choice in ("required", "auto"):
            try:
                resp = llm.chat(messages, tools=schemas, tool_choice=tool_choice,
                                enable_thinking=False)
            except Exception:
                self.log.exception(f"QQ 工具选择失败（tool_choice={tool_choice}）")
                continue
            choices = getattr(resp, "choices", None) if resp else None
            message = getattr(choices[0], "message", None) if choices else None
            for call in (getattr(message, "tool_calls", None) or []):
                fn = getattr(call, "function", None)
                name = str(getattr(fn, "name", "") or "")
                if name not in self.QQ_CHOICE_TOOLS:
                    continue
                args = self._parse_arguments(getattr(fn, "arguments", ""))
                self.log.info(f"QQ 工具选择: {name} {str(args)[:120]}")
                return name, args
        return None

    def pre_route(self, text: str, meowid: str) -> bool:
        plan = self.pre_route_plan(text, meowid)
        if plan is None:
            return False
        name, arguments = plan
        if not name:
            return True
        result = self.hard_trigger(name, arguments, meowid, text)
        self.log.info(f"父级 toolcalls 规则硬触发 {name}: {(text or '')[:30]} -> {result}")
        return True

    def hard_trigger(self, name: str, arguments: Dict, meowid: str, text: str = "",
                     context: Dict = None):
        """规则硬触发统一入口：登记工具触发态 → 角色裁决 → 放行才真的执行。

        角色有权拒绝（心情不好 / 正在生这个人的气）：拒绝台词由裁决器 TTS 播报，
        这里拿回台词就掐断本次工具，不派发、不启动。
        """
        from func.toolbox.consent import TBoxConsent
        refused = TBoxConsent().ask(name, text, meowid)
        if refused:
            self.log.info(f"父级 toolcalls 硬触发被角色拒绝 {name}: {(text or '')[:30]}")
            return refused
        if context is None:
            context = {"meowid": meowid, "text": text,
                       "short_memory": self._load_short_memory(), "system_prompt": ""}
        result = self.dispatch(name, arguments, meowid, context)
        self.log.info(f"父级 toolcalls 硬触发 {name} 结果: {str(result)[:200]}")
        self._speak_result(name, result, meowid)
        return result

    # 这些工具在 QQ 侧执行、自己不出声：硬触发跳过主回复后，要补一句角色台词
    SPEAK_RESULT_TOOLS = ("napcat_send", "napcat_ask_bot")

    def _speak_result(self, name: str, result, meowid: str) -> str:
        """工具执行完，让角色用自己的话说一句结果（失败就不说，不写死台词）"""
        if name not in self.SPEAK_RESULT_TOOLS:
            return ""
        text = str(result or "").strip()
        if not text:
            return ""
        ok = any(k in text for k in ("已向", "已发送", "发送成功", "等待它在群里回复"))
        what = "发QQ消息" if name == "napcat_send" else "叫群里的机器人"
        need = (f"你刚替主人办了「{what}」，{'已经办成' if ok else '没办成'}，结果是：{text[:80]}。"
                "用你自己的口气一句话告诉主人；别念技术细节、别复述消息内容。")
        try:
            from func.toolbox.character_voice import TBoxCharacterVoice
            line = TBoxCharacterVoice().line(need, meowid,
                                             history=self._load_short_memory(4),
                                             max_chars=24) or ""
        except Exception:
            self.log.exception("工具结果台词生成失败")
            line = ""
        if not line:
            self.log.warning(f"工具结果台词生成失败，本次不播报：{name}")
            return ""
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(line, source="toolbox")
        except Exception:
            self.log.exception("工具结果播报失败")
            return ""
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({"role": "assistant", "content": line,
                                "type": "toolbox_result"}, 0)
        except Exception:
            self.log.exception("工具结果台词写入短期记忆失败")
        self.log.info(f"工具结果台词（{name}）: {line}")
        return line

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
        args = self._parse_arguments(arguments)
        if not args and str(arguments or "").strip() not in ("", "{}", "None"):
            self.log.warning(f"工具参数解析为空，按空参数执行 {name}: {str(arguments)[:120]!r}")
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

    @staticmethod
    def _parse_arguments(raw):
        """解析工具参数：容忍模型多吐一段 JSON / 尾随文本

        小模型常见输出是 `{...}{...}` 或 `{...}` 后面再跟半句解释，直接 json.loads 会
        报 "Extra data" 把整包参数丢成 {}（mention / target / command 全没了）。
        """
        if isinstance(raw, dict):
            return raw
        body = str(raw or "").strip()
        if not body:
            return {}
        try:
            data = json.loads(body, strict=False)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        decoder = json.JSONDecoder(strict=False)
        candidates = [body]
        match = re.search(r"\{[\s\S]*\}", body)
        if match:
            candidates.append(match.group(0))
        for text in candidates:
            try:
                data, _end = decoder.raw_decode(text)
            except Exception:
                continue
            if isinstance(data, dict):
                return data
        return {}

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
