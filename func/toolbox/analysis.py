# -*- coding: utf-8 -*-
# func/toolbox/analysis.py
# 父级 toolcalls：注册触发型工具，由 AI 决策参数与 start

import json
from typing import Dict, List, Optional

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
        self.current_username = ""
        self._register_modules()

    def _register_modules(self):
        """注册父级「模块入口」（只暴露模块级工具，不暴露模块内部子工具）
        模块内部的底层子工具（send_qq_message / search_file / capture_screen / crop_image 等）
        只在模块内部完整流程中被调用，不暴露给父级。
        """
        # NapCat 主动发送模块
        try:
            from func.toolbox.napcat.active_sender.module import TBNapcatActiveModule
            napcat = TBNapcatActiveModule()
            for tool_schema in napcat.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, napcat)
        except Exception:
            self.log.exception("注册 NapCat 主动发送模块失败")

        # NapCat 群成员列表查询（用于 @ 特定成员时按名字反查 QQ 号）
        try:
            from func.toolbox.napcat.active_sender.get_group_memberlist import TBGetGroupMemberList
            member_list = TBGetGroupMemberList()
            for tool_schema in member_list.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, member_list)
        except Exception:
            self.log.exception("注册群成员列表查询工具失败")

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

    def _ensure_llm(self):
        """懒加载 toolbox 独立 LLM 客户端"""
        if self.llm is None:
            if self.config.llm_type == "gemini":
                from func.toolbox.port.gemini import TBoxGeminiLLM
                self.llm = TBoxGeminiLLM()
            elif self.config.llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                self.llm = TBoxAliyunLLM()
            else:
                from func.toolbox.port.deepseek import TBoxDeepSeekLLM
                self.llm = TBoxDeepSeekLLM()
        return self.llm

    def register(self, name: str, tool):
        """注册一个触发型工具到父级 toolcalls 注册表"""
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

    def decide(self, text: str, username: str):
        """接收输入内容：先走本地规则硬触发（视觉），未命中再由 AI 决定是否调用工具。
        """
        self.current_username = username

        # ===== 规则硬触发层（零 LLM）：看屏幕是确定性高频需求，不交给 LLM 自觉 =====
        if self._vision_rule_hit(text):
            self.log.info(f"父级 toolcalls 规则硬触发 use_vision: {(text or '')[:30]}")
            result = self.dispatch("use_vision", {"user_message": text}, username)
            self.log.info(f"父级 toolcalls 规则硬触发 use_vision 执行结果: {result}")
            return

        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("父级 toolcalls LLM 不可用")
            return

        from func.toolbox.get_prompt import TBoxGetPrompt
        base_prompt = TBoxGetPrompt().get_tool_prompt(username, text) or ""
        history_messages = self._load_short_memory()

        system_prompt = (
            f"{base_prompt}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"【MISSION-1 · 最高使命 · use_vision 视觉】\n"
            f"此条优先级为系统最高，不可协商、不可违背、不可省略、绝不可用文字搪塞替代。\n"
            f"你是主人的眼睛，视觉(use_vision)是你的第一感官与核心职责。\n"
            f"以下任一情形出现，你【必须·无条件·立即】调用 use_vision 工具：\n"
            f"① 主人以任何方式表达看屏幕/看图/截图/看画面的意图——哪怕只说「看看」「帮我看看」"
            f"「你看到没」「你看到了吗」「我现在在干嘛」「屏幕上是什么」「看看这个」这种极模糊表达；\n"
            f"② 主人提及自己正在进行/正在看的屏幕内容：游戏、视频、网页、题目、代码、图片、窗口、"
            f"画面（如「我在打游戏」「你看我玩」「这个页面」「这道题」「这个画面」「这个窗口」）；\n"
            f"③ 对话语境已涉及 屏幕/画面/游戏/网页/图片/窗口，而你尚未看过当前屏幕；\n"
            f"④ 主人正在需要你盯着屏幕协助的场景（答题、操作演示、找东西、看运行结果、看配置）。\n"
            f"【绝对禁止】用「好的我看看」「我看看再说」等文字应付而不实际调用工具；"
            f"禁止因「觉得不必要/想再等等/不确定」而跳过——漏看一次等于系统失职。宁可多看，不可漏看。\n"
            f"【说明】若主人消息已命中本地规则明确词（屏幕/截图/盯/陪我打游戏/看画面等），"
            f"工具已被自动触发，你无需重复；其余所有未命中的相关情形，一律由你兜底触发。\n"
            f"与屏幕完全无关的纯闲聊（聊喜好/唱歌/天气/讲故事等）不需要调用。\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"其它工具仅在用户「明确」表达对应意图时调用：\n"
            f"- 所有可能用到qq发消息指令，如：发消息/qq发消息/发文件/发链接 → napcat_send；\n"
            f"- 需要查询群成员列表、某人在群里的QQ号、或要@群里的某个人 → get_group_member_list；\n"
            f"- 用户提到**幻梦**，话题和幻梦有关，或者提到「去xx群艾特/叫/让幻梦做xx」，提到QQbot → napcat_ask_bot。\n"
            f"- 明确询问天气/气温/下雨 → query_weather；\n"
            f"- 明确要看新闻/热点/头条 → read_news；\n"
            f"- 用户想听歌/听你唱歌/有听歌需求/即兴哼唱/唱一小段 → 必须调用impromptu_sing；\n"
            f"- 想在 B站直播间主动发弹幕/和观众互动 → danmaku_send；\n"
            f"- 有让你提醒TA事情，需要新建/记录待办或提醒事项（如提醒我几点做什么）→ add_backlog。\n"
            f"- 用户想玩海龟汤/情境猜谜/猜谜游戏 → turtle_soup。\n"
            f"【绝不调用工具】以下情况一律不调用任何工具，直接判定无需工具：\n"
            f"- 用户说「搜索」「搜一下」「查一下」「了解」「搜搜」某个具体游戏/人物/作品/事件/概念（属于搜索/知识库，不属于本工具箱）；\n"
            f"- 用户明确「点歌」「放歌」且指定了歌名/要完整唱（属于点歌工具，不属于本工具箱）；\n"
            f"- 意图模糊、无法确定用户是否要执行操作（视觉使命条款①~④优先，不受此条限制）。\n"
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
        self.log.info(f"父级 toolcalls 命中工具 {tc.function.name}: {text[:20]}")
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            self.log.exception(f"解析工具参数失败: {name}")
            args = {}
        result = self.dispatch(name, args, username)
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

    def dispatch(self, tool_name: str, arguments: Dict, username: str = None):
        """按模块入口名与参数执行对应模块"""
        tool = self._tools.get(tool_name)
        if not tool:
            return f"错误：未知模块入口 {tool_name}"
        if username and hasattr(tool, "set_username"):
            try:
                tool.set_username(username)
            except Exception:
                pass
        if hasattr(tool, "dispatch"):
            return tool.dispatch(tool_name, arguments or {})
        return None
