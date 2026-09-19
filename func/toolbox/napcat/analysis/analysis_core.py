# -*- coding: utf-8 -*-
# func/toolbox/napcat/analysis/analysis_core.py
# NapCat 意图分析：判断 QQ 消息是否需要调用触发型工具（weather / news）
# 逻辑：tool_choice 分析 → 不调工具返回 False（走原 napcat LLM 回复）→ 调工具走 toolbox 工具流程（结果发 QQ，不走 pipeline TTS）

import json
from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.get_prompt import TBoxGetPrompt


@singleton
class TBNapcatAnalysis:
    """NapCat 意图分析：独立于 toolbox 父级 analysis，仅在 QQ 私聊 / 群聊 @ 时使用

    - 复用 napcat 现有 LLM（func/llm 配置 + toolbox port）；
    - 只暴露 query_weather / read_news 两个被动查询工具；
    - decide_and_run 返回 True 表示已调工具并回复（上层跳过原 LLM 回复），
      False 表示未命中工具（上层继续走原 napcat LLM 回复）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()

    # 绘画规则触发词表：命中即强制开画（零 LLM，与 toolbox 父级 analysis 同款）
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
        """本地规则硬触发判断：QQ 消息命中绘画意图词即返回 True（零 LLM）"""
        t = (text or "").strip()
        if not t:
            return False
        return any(w in t for w in self.PAINT_RULE_WORDS)

    # ==================== 主入口 ====================
    def decide_and_run(self, text: str, username: str, qq_context: Dict,
                       short_memory: Optional[List[dict]] = None) -> bool:
        """分析 QQ 消息，命中工具则执行并返回 True；否则返回 False"""
        if not text or not text.strip():
            return False

        # ===== 规则硬触发层（零 LLM）：绘画点单是确定性高频需求，命中即直接开画 =====
        if self._paint_rule_hit(text):
            self.log.info(f"[NapcatAnalysis] 规则硬触发 flux_paint: {(text or '')[:30]}")
            self._run_flux_paint(text, username, qq_context, short_memory)
            return True

        llm = self._llm()
        if not llm or not llm.client:
            self.log.error("[NapcatAnalysis] LLM 不可用")
            return False

        system = TBoxGetPrompt().get_tool_prompt(username, text) or ""

        try:
            from func.toolbox.plugins.manager import PluginManager
            plugin_hint = PluginManager().prompt_hint()
        except Exception:
            plugin_hint = ""

        # QQ 特定场景：命中哼唱关键词时，注入强制调用引导（仅 prompt 引导，不用 tool_choice 强制）
        hum_force = ""
        if text and ("哼唱" in text or "唱首歌" in text):
            hum_force = (
                "\n\n【最高优先级指令·覆盖前述所有要求】"
                "用户这条消息明确包含「哼唱」或「唱首歌」关键词，属于明确的唱歌/哼唱需求。"
                "你必须调用 impromptu_sing 工具（request 参数填用户原话），"
            )

        system = (
            f"{system}\n\n"
            f"【工具调用】请判断用户这条 QQ 消息是否需要查询天气、查看新闻、新建待办或即兴哼唱：\n"
            f"- 询问天气/气温/是否下雨/要不要带伞 → 调用 query_weather；\n"
            f"- 询问新闻/热点/最近发生了什么/有什么大事 → 调用 read_news；\n"
            f"- 明确要新建/记录待办或提醒事项（如提醒我几点做什么）→ 调用 add_backlog；\n"
            f"- 想让角色唱歌，想听角色唱歌→ 调用 impromptu_sing；\n"
            f"- 明确想玩海龟汤/情境猜谜/猜谜游戏 → 调用 turtle_soup；\n"
            f"- 用户需要「画/画图/画画/画一幅/画个…/来张图/生成一张图/想要一张…的图/涩图」→ 调用 flux_paint（request 填用户原话）；\n"
            f"{plugin_hint}\n"
            f"- 其它闲聊、普通话题 → 不调用任何工具。"
            f"{hum_force}"
        )
        messages: List[dict] = [{"role": "system", "content": system}]
        for m in short_memory or []:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": str(m["content"])})
        messages.append({"role": "user", "content": text})

        tools = self._build_tools()
        resp = llm.chat(messages, tools=tools, tool_choice="auto")
        if not resp or not resp.choices:
            self.log.warning("[NapcatAnalysis] LLM 无有效响应，返回 False 走正常回复")
            return False

        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            self.log.info(f"[NapcatAnalysis] 未命中工具，走正常回复: {text[:20]}")
            return False

        # 只取第一个工具，避免一次多工具并发冲突
        tc = tool_calls[0]
        self.log.info(f"[NapcatAnalysis] 命中工具 {tc.function.name}: {text[:20]}")
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            self.log.exception(f"[NapcatAnalysis] 解析工具参数失败: {name}")
            args = {}

        handled = False
        if name == "query_weather":
            from func.toolbox.weather.weather_core import TBWeatherCore
            TBWeatherCore().set_username(username)
            result = TBWeatherCore().dispatch_qq(name, args, qq_context)
            if isinstance(result, tuple) and result and result[0] == "redeliver":
                self._redeliver(result[1], username, qq_context, short_memory)
            handled = True
        elif name == "read_news":
            from func.toolbox.news.news_core import TBNewsCore
            TBNewsCore().set_username(username)
            result = TBNewsCore().dispatch_qq(name, args, qq_context)
            if isinstance(result, tuple) and result and result[0] == "redeliver":
                self._redeliver(result[1], username, qq_context, short_memory)
            handled = True
        elif name == "add_backlog":
            from func.toolbox.add_backlog.add_tool import TBAddBacklogTool
            TBAddBacklogTool().set_username(username)
            result = TBAddBacklogTool().dispatch_qq(name, args, qq_context)
            if isinstance(result, tuple) and result and result[0] == "redeliver":
                self._redeliver(result[1], username, qq_context, short_memory)
            handled = True
        elif name == "impromptu_sing":
            from func.toolbox.meowsongs.meowsongs_core import TBMeowSongsCore
            TBMeowSongsCore().set_username(username)
            TBMeowSongsCore().dispatch_qq(name, args, qq_context)
            handled = True
        elif name == "turtle_soup":
            from func.toolbox.turtle_soup.turtle_soup_core import TBTurtleSoupCore
            TBTurtleSoupCore().set_username(username)
            TBTurtleSoupCore().dispatch_qq(name, args, qq_context)
            handled = True
        elif name == "flux_paint":
            self._run_flux_paint(str(args.get("request") or text), username,
                                 qq_context, short_memory)
            handled = True
        else:
            from func.toolbox.plugins.manager import PluginManager
            pm = PluginManager()
            if pm.has_trigger(name):
                pm.set_username(username)
                pm.set_context({"username": username, "text": text,
                                "short_memory": short_memory or []})
                pm.dispatch_qq(name, args, qq_context)
                handled = True
            else:
                self.log.warning(f"[NapcatAnalysis] 未知工具 {name}")
        return handled

    def _run_flux_paint(self, request: str, username: str, qq_context: Dict,
                        short_memory: Optional[List[dict]]):
        """Flux 绘画：QQ 一次性触发开局（无会话接管，出图即结束）"""
        try:
            from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
            core = TBFluxPainterCore()
            core.set_username(username)
            core.set_context({
                "username": username,
                "text": str(request or "") if isinstance(request, str) else "",
                "short_memory": short_memory,
                # 与 toolbox 父级一致：注入角色系统提示词（供绘画 LLM 上下文）
                "system_prompt": TBoxGetPrompt().get_tool_prompt(username, str(request or "")) or "",
            })
            result = core.dispatch_qq("flux_paint", {"request": request}, qq_context)
            self.log.info(f"[NapcatAnalysis] Flux 绘画 QQ 开局: {result}")
        except Exception:
            self.log.exception("Flux 绘画 QQ 开局失败")

    # ==================== 重新投递（另起话题） ====================
    def _redeliver(self, text: str, username: str, qq_context: Dict,
                   short_memory: Optional[List[dict]]):
        """用户另起话题：把新消息重新投递回正常 QQ 回复流程（新线程，避免嵌套阻塞）

        - 私聊：走 TBoxCore.receive_qq（重新意图分析 + 正常 LLM 回复）；
        - 群聊：走 TBoxCore.reply_group_at（重新意图分析 + 群聊 LLM 回复）。
        """
        if not text or not text.strip():
            return
        from threading import Thread

        def _run():
            try:
                from func.toolbox.toolbox_core import TBoxCore
                if str(qq_context.get("message_type", "")) == "group":
                    buf = {
                        "group_id": str(qq_context.get("target_id", "")),
                        "group_name": str(qq_context.get("group_name", "") or ""),
                        "user_id": str(qq_context.get("user_id", "")),
                        "username": username,
                        "self_id": str(qq_context.get("self_id", "")),
                        "texts": [text.strip()],
                    }
                    TBoxCore().reply_group_at(buf, text.strip())
                else:
                    user_id = str(qq_context.get("user_id", "") or qq_context.get("target_id", ""))
                    TBoxCore().receive_qq(username, user_id, text.strip(), short_memory)
            except Exception:
                self.log.exception("[NapcatAnalysis] 重新投递失败")

        Thread(target=_run, daemon=True).start()
        self.log.info(f"[NapcatAnalysis] 用户另起话题，重新投递: {text[:20]}")

    # ==================== 工具 schema ====================
    def _build_tools(self) -> List[dict]:
        """复用 weather / news / add_backlog 的工具 schema"""
        tools = []
        try:
            from func.toolbox.weather.weather_core import TBWeatherCore
            tools.extend(TBWeatherCore().build_tools())
        except Exception:
            self.log.exception("构建 weather 工具失败")
        try:
            from func.toolbox.news.news_core import TBNewsCore
            tools.extend(TBNewsCore().build_tools())
        except Exception:
            self.log.exception("构建 news 工具失败")
        try:
            from func.toolbox.add_backlog.config import TBAddBacklogConfig
            if TBAddBacklogConfig().qq_enabled:
                from func.toolbox.add_backlog.add_tool import TBAddBacklogTool
                tools.extend(TBAddBacklogTool().build_tools())
        except Exception:
            self.log.exception("构建 add_backlog 工具失败")
        try:
            from func.toolbox.meowsongs.meowsongs_core import TBMeowSongsCore
            tools.extend(TBMeowSongsCore().build_tools())
        except Exception:
            self.log.exception("构建 meowsongs 工具失败")
        try:
            from func.toolbox.turtle_soup.turtle_soup_core import TBTurtleSoupCore
            tools.extend(TBTurtleSoupCore().build_tools())
        except Exception:
            self.log.exception("构建 turtle_soup 工具失败")
        try:
            from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
            tools.extend(TBFluxPainterCore().build_tools())
        except Exception:
            self.log.exception("构建 flux_paint 工具失败")
        try:
            from func.toolbox.plugins.manager import PluginManager
            tools.extend(PluginManager().trigger_schemas())
        except Exception:
            self.log.exception("构建插件工具失败")
        return tools

    # ==================== LLM（复用 napcat 现有配置 func/llm） ====================
    @staticmethod
    def _llm():
        from func.llm.config import LLMConfig
        cfg = LLMConfig()
        if cfg.local_llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.local_llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
