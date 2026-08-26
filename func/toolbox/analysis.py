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
            if self.config.llm_type == "aliyun":
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
        """接收输入内容，单次 toolcalls 由 AI 决定是否调用工具并执行。

        - 提供全部已注册工具，tool_choice=auto，让 AI 自行判断是否需要工具；
        - 调用了工具：逐个 dispatch 执行；
        - 未调用工具：静默（双通道下主 LLM 已回复，toolbox 不重复回复）。
        """
        self.current_username = username
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("父级 toolcalls LLM 不可用")
            return

        from func.toolbox.get_prompt import TBoxGetPrompt
        base_prompt = TBoxGetPrompt().get_tool_prompt(username, text) or ""
        history_messages = self._load_short_memory()

        system_prompt = (
            f"{base_prompt}\n\n"
            f"【工具调用】根据用户消息判断是否需要调用工具箱工具。\n"
            f"只有用户「明确」表达以下操作意图时，才调用对应工具：\n"
            f"- 所有可能用到qq发消息指令，如：发消息/qq发消息/发文件/发链接 → napcat_send；\n"
            f"- 用户提到**幻梦**，话题和幻梦有关，或者提到「去xx群艾特/叫/让幻梦做xx」，提到QQbot → napcat_ask_bot。\n"
            f"- 所有可能和看屏幕相关的指令，如：看屏幕/截图/看图片/看我在做什么 → use_vision；\n"
            f"- 明确询问天气/气温/下雨 → query_weather；\n"
            f"- 明确要看新闻/热点/头条 → read_news；\n"
            f"- 用户想听歌/听你唱歌/有听歌需求/即兴哼唱/唱一小段 → 必须调用impromptu_sing；\n"
            f"- 想在 B站直播间主动发弹幕/和观众互动 → danmaku_send；\n"
            f"- 有让你提醒TA事情，需要新建/记录待办或提醒事项（如提醒我几点做什么）→ add_backlog。\n"
            f"- 用户想玩海龟汤/情境猜谜/猜谜游戏 → turtle_soup。\n"
            f"【绝不调用工具】以下情况一律不调用任何工具，直接判定无需工具：\n"
            f"- 用户说「搜索」「搜一下」「查一下」「了解」「搜搜」某个具体游戏/人物/作品/事件/概念（属于搜索/知识库，不属于本工具箱）；\n"
            f"- 用户明确「点歌」「放歌」且指定了歌名/要完整唱（属于点歌工具，不属于本工具箱）；\n"
            f"- 普通闲聊、询问、讨论、表达情绪、分享观点；\n"
            f"- 意图模糊、无法确定用户是否要执行操作。\n"
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

        self.log.info(f"父级 toolcalls 命中工具 {[tc.function.name for tc in tool_calls]}: {text[:20]}")
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                self.log.exception(f"解析工具参数失败: {name}")
                args = {}
            result = self.dispatch(name, args, username)
            self.log.info(f"父级工具 {name} 执行结果: {result}")

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
