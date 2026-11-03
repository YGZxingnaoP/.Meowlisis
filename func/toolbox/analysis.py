# -*- coding: utf-8 -*-
# func/toolbox/analysis.py
# 父级 toolcalls：注册触发型工具，由 AI 决策参数与 start

import json
import re
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig
from func.toolbox.trigger_rules import CHOOSE, FORCED, matched


class TBoxAnalysis:
    """父级 toolcalls 分析类：维护模块入口注册表，AI 决策选择并开启模块"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.llm = None
        self._tools = {}
        # 触发规则缓存（由已注册模块的 TRIGGER_RULES 收集，注册时失效）
        self._rules = None
        self._rule_speak_tools = set()
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
        self._rules = None

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
        return self._match_trigger_rule(text)

    # ==================== 触发规则（通用执行器，不含具体工具逻辑） ====================
    # 硬触发/工具上下文里带的短期记忆条数：固定 30 条。
    # 工具提示词不加整段历史，避免把很早的对话灌进去污染当前工具上下文。
    TOOL_SHORT_MEMORY = 30
    def _collect_rules(self):
        """从已注册模块收集 TRIGGER_RULES（模块自己声明，父级只做匹配/执行）"""
        if self._rules is not None:
            return self._rules
        rules, speak_tools, seen = [], set(), set()
        for tool in self._tools.values():
            if id(tool) in seen:
                continue
            seen.add(id(tool))
            for rule in getattr(tool, "TRIGGER_RULES", ()) or ():
                if not isinstance(rule, dict) or not rule.get("words"):
                    continue
                rules.append(rule)
                if not rule.get("speak_result"):
                    continue
                if rule.get("mode") == CHOOSE:
                    speak_tools.update(rule.get("candidates") or ())
                else:
                    speak_tools.add(str(rule.get("tool") or ""))
        self._rules = rules
        self._rule_speak_tools = speak_tools
        return rules

    def _match_trigger_rule(self, text: str):
        """按模块声明的规则匹配：forced 直接返回入口；choose 先让角色选一个"""
        body = str(text or "").strip()
        if not body:
            return None
        for rule in self._collect_rules():
            if not matched(rule, body):
                continue
            if rule.get("mode") == FORCED:
                tool = str(rule.get("tool") or "")
                if tool not in self._tools:
                    continue
                build_args = rule.get("args")
                return tool, (build_args(body) if callable(build_args) else {})
            plan = self._resolve_choice(rule, body)
            if plan:
                return plan
            fallback = str(rule.get("fallback") or "")
            if fallback and fallback in self._tools:
                self.log.warning(f"触发选择没选出来，兜底 {fallback}（候选 {rule.get('candidates')}）")
                return fallback, {"request": body}
        return None

    def _resolve_choice(self, rule: dict, text: str):
        """choose 规则：让角色在候选入口里选一个（required → auto），参数走容错解析"""
        candidates = [n for n in (rule.get("candidates") or ()) if n in self._tools]
        if not candidates:
            return None
        schemas = []
        for name in candidates:
            try:
                for schema in self._tools[name].build_tools():
                    if schema.get("function", {}).get("name") == name:
                        schemas.append(schema)
            except Exception:
                self.log.exception(f"读取工具定义失败: {name}")
        if not schemas:
            return None
        system = str(rule.get("prompt") or "")
        hint = rule.get("hint")
        if callable(hint):
            try:
                hint = hint()
            except Exception:
                self.log.exception("触发规则的 hint 生成失败")
                hint = ""
        if hint:
            system = f"{system}\n{hint}" if system else str(hint)
        llm = self._ensure_llm()
        if llm is None or not getattr(llm, "client", None):
            return None
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": str(text or "")}]
        for tool_choice in ("required", "auto"):
            try:
                resp = llm.chat(messages, tools=schemas, tool_choice=tool_choice,
                                enable_thinking=False)
            except Exception:
                self.log.exception(f"触发选择失败（tool_choice={tool_choice}）")
                continue
            choices = getattr(resp, "choices", None) if resp else None
            message = getattr(choices[0], "message", None) if choices else None
            for call in (getattr(message, "tool_calls", None) or []):
                fn = getattr(call, "function", None)
                name = str(getattr(fn, "name", "") or "")
                if name not in candidates:
                    continue
                args = self._parse_arguments(getattr(fn, "arguments", ""))
                self.log.info(f"触发选择: {name} {str(args)[:120]}")
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
        self._collect_rules()          # 确保规则缓存就绪（speak_result 判定要用）
        refused = TBoxConsent().ask(name, text, meowid)
        if refused:
            self.log.info(f"父级 toolcalls 硬触发被角色拒绝 {name}: {(text or '')[:30]}")
            return refused
        if context is None:
            context = {"meowid": meowid, "text": text,
                       "short_memory": self._load_short_memory(self.TOOL_SHORT_MEMORY),
                       "system_prompt": ""}
        result = self.dispatch(name, arguments, meowid, context)
        self.log.info(f"父级 toolcalls 硬触发 {name} 结果: {str(result)[:200]}")
        if name in self._rule_speak_tools:
            self._speak_result(name, result, meowid)
        return result

    def _speak_result(self, name: str, result, meowid: str) -> str:
        """工具执行完，让角色用自己的话说一句结果（失败就不说，不写死台词）"""
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
        history_messages = self._load_short_memory(self.TOOL_SHORT_MEMORY)
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
                       "short_memory": self._load_short_memory(self.TOOL_SHORT_MEMORY),
                       "system_prompt": ""}
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

    # ==================== 短期记忆 ====================
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
