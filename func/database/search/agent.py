# -*- coding: utf-8 -*-
# func/database/search/agent.py
# 搜索 Agent：单 task 多轮工具调用循环，AI 决策挑选最终搜索结果

import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig
from func.database.search.port import get_search_llm
from func.database.search.agent_tools import CatLearnAgentTools
from func.database.search.crawler import CatLearnCrawler


@singleton
class CatLearnAgent:
    """搜索 Agent（单例）

    每个搜索 task 独立运行一个多轮循环：
    - AI 调用 search_site 搜索 → visit_url 看正文 → select_result 挑选结果；
    - AI 不再调用工具时自然结束；
    - 达到 max_rounds 仍一直调工具则强制结束，收集已选结果。

    产出 = AI 选中结果的原文（不产出 AI 改写/总结文字）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.crawler = CatLearnCrawler()

    def run(self, task: dict) -> dict:
        """运行单 task 的 Agent 循环，返回落盘结果

        入参 task: {"task_id", "search_keys"(单词), "web_url"(站点)}
        返回: {"task_id", "search_keys", "site", "selected": [...], "content": str,
               "rounds": int, "hit_limit": bool, "status": "ok"/"empty"}
        """
        task_id = str(task.get("task_id", "0"))
        search_keys = str(task.get("search_keys", "") or "").strip()
        site = str(task.get("web_url", "") or "").strip()

        tools = CatLearnAgentTools(self.crawler)
        tools.reset()
        tools.set_site(site)

        llm = get_search_llm()
        if llm is None or not llm.client:
            self.log.error("搜索模块 LLM 不可用，Agent 无法运行")
            return self._empty(task_id, search_keys, site, 0, False, "llm_unavailable")

        system_prompt = (
            "你是知识搜索Agent。你的任务是围绕一个搜索主题，"
            "从指定站点找到【最有价值】的结果页面，并挑选出来。\n"
            "判断价值的标准（按优先级从高到低，且都必须与搜索词强相关）：\n"
            "  1) 定义/详情类：百科词条、游戏详情页、产品介绍页等【定义性、权威性】内容；\n"
            "  2) 评价类：与搜索词强相关的评测、攻略、深度评价；\n"
            "  3) 近期新闻类：与搜索词强相关的近期新闻/资讯消息。\n"
            "流程：\n"
            "1. 先用 search_site 搜索（用单个精准词）；\n"
            "2. 对可疑/可能准确的结果用 visit_url 查看正文，判断价值；\n"
            "3. 用 select_result 挑选值得保留的结果，可多次调用。\n"
            "规则：\n"
            "- 详情/定义 > 强相关评价 > 强相关近期新闻，同优先级内选最准确、最完整的；\n"
            "- 丢弃广告、无关页面、以及与搜索词弱相关或无关的内容；\n"
            "- 不要输出总结、分析或改写内容，只通过工具操作；\n"
            "- 当你认为已经挑够了、或没有更多值得保留的结果时，"
            "直接输出一句简短说明（如“选择完成”）结束，不要再调用工具。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"搜索主题：{search_keys}\n首选站点：{site}",
            },
        ]

        max_rounds = max(1, self.config.agent_max_rounds)
        rounds = 0
        hit_limit = False

        while rounds < max_rounds:
            resp = llm.chat(
                messages,
                tools=tools.build_tools(),
                enable_thinking=True,
            )
            tool_calls = self._extract_tool_calls(resp)
            if not tool_calls:
                # AI 不再调用工具 → 自然结束
                break

            rounds += 1
            # 追加 assistant 消息（含 tool_calls）
            assistant_msg = {"role": "assistant", "content": None, "tool_calls": tool_calls}
            messages.append(assistant_msg)

            # 执行每个工具，追加 tool 结果
            for tc in tool_calls:
                name = tc.get("function", {}).get("name", "")
                try:
                    args = json.loads(tc.get("function", {}).get("arguments", "{}") or "{}")
                except Exception:
                    args = {}
                result_text = tools.execute(name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": name,
                    "content": result_text,
                })

        # 达到上限且仍在调工具（没有自然结束）
        if rounds >= max_rounds and self._last_had_tool_calls(messages):
            hit_limit = True
            self.log.warning(f"[Agent] task {task_id} 达到 max_rounds={max_rounds}，强制结束")

        # 收集选中的结果
        selected = tools.collect_selected(fetch_content=True)
        if not selected:
            return self._empty(task_id, search_keys, site, rounds, hit_limit, "no_selection")

        content = "\n\n".join([
            f"【{s.get('title') or '结果'}】\n{s.get('content', '')}" for s in selected if s.get("content")
        ])
        if not content.strip():
            return self._empty(task_id, search_keys, site, rounds, hit_limit, "empty_content")

        return {
            "task_id": task_id,
            "search_keys": search_keys,
            "site": site,
            "selected": [{"title": s.get("title", ""), "url": s.get("url", ""),
                          "reason": s.get("reason", "")} for s in selected],
            "content": content,
            "rounds": rounds,
            "hit_limit": hit_limit,
            "status": "ok",
        }

    # ==================== 工具调用解析 ====================
    @staticmethod
    def _extract_tool_calls(resp) -> list:
        """从非流式响应提取 tool_calls（保持 id/type/function 结构）"""
        if not resp or not getattr(resp, "choices", None):
            return []
        try:
            msg = resp.choices[0].message
            tcs = getattr(msg, "tool_calls", None) or []
            out = []
            for tc in tcs:
                out.append({
                    "id": getattr(tc, "id", ""),
                    "type": getattr(tc, "type", "function"),
                    "function": {
                        "name": getattr(tc.function, "name", ""),
                        "arguments": getattr(tc.function, "arguments", "{}"),
                    },
                })
            return out
        except Exception:
            return []

    @staticmethod
    def _last_had_tool_calls(messages: list) -> bool:
        """判断最后一条 assistant 消息是否含 tool_calls（用于超限判断）"""
        for m in reversed(messages):
            if m.get("role") == "assistant":
                return bool(m.get("tool_calls"))
        return False

    # ==================== 空结果 ====================
    @staticmethod
    def _empty(task_id, search_keys, site, rounds, hit_limit, status) -> dict:
        return {
            "task_id": task_id,
            "search_keys": search_keys,
            "site": site,
            "selected": [],
            "content": "",
            "rounds": rounds,
            "hit_limit": hit_limit,
            "status": status,
        }
