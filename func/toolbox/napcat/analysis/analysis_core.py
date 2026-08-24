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

    # ==================== 主入口 ====================
    def decide_and_run(self, text: str, username: str, qq_context: Dict,
                       short_memory: Optional[List[dict]] = None) -> bool:
        """分析 QQ 消息，命中工具则执行并返回 True；否则返回 False"""
        if not text or not text.strip():
            return False

        llm = self._llm()
        if not llm or not llm.client:
            self.log.error("[NapcatAnalysis] LLM 不可用")
            return False

        system = TBoxGetPrompt().get_tool_prompt(username, text) or ""
        system = (
            f"{system}\n\n"
            f"【工具调用】请判断用户这条 QQ 消息是否需要查询天气、查看新闻、新建待办或即兴哼唱：\n"
            f"- 询问天气/气温/是否下雨/要不要带伞 → 调用 query_weather；\n"
            f"- 询问新闻/热点/最近发生了什么/有什么大事 → 调用 read_news；\n"
            f"- 明确要新建/记录待办或提醒事项（如提醒我几点做什么）→ 调用 add_backlog；\n"
            f"- 想让角色即兴哼唱一小段歌（如 哼两句、唱一句）→ 调用 impromptu_sing；\n"
            f"- 其它闲聊、普通话题 → 不调用任何工具。"
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

        self.log.info(f"[NapcatAnalysis] 命中工具 {[tc.function.name for tc in tool_calls]}: {text[:20]}")
        handled = False
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                self.log.exception(f"[NapcatAnalysis] 解析工具参数失败: {name}")
                args = {}

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
            else:
                self.log.warning(f"[NapcatAnalysis] 未知工具 {name}")
        return handled

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
        return tools

    # ==================== LLM（复用 napcat 现有配置 func/llm） ====================
    @staticmethod
    def _llm():
        from func.llm.config import LLMConfig
        cfg = LLMConfig()
        if cfg.local_llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
