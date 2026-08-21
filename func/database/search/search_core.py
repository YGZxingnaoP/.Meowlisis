# -*- coding: utf-8 -*-
# func/database/search/search_core.py
# 搜索学习编排：LLM 深度思考决策搜索任务 → 单 task Agent 挑选结果 → 分发结果

import os
import json
import time
from threading import Thread
from concurrent.futures import ThreadPoolExecutor, as_completed

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.search.port import get_search_llm
from func.database.search.search_task import CatLearnSearchTask
from func.database.search.crawler import CatLearnCrawler
from func.database.search.agent import CatLearnAgent


@singleton
class CatLearnSearch:
    """搜索学习编排（单例）

    两条触发路径：
    1. trigger="record"：alluser_record 滚动后，把聊天记录发给 LLM 深度思考决策，
       搜索结果入库（learning）。
    2. trigger="keyword"：用户消息命中"搜索"关键词，立刻搜索，
       结果摘要（search_understand，一次性），不进库。

    每个 task 独立跑 CatLearnAgent 多轮循环，AI 决策挑选最终结果；
    落盘的是 AI 选中结果的原文，不是 AI 改写/总结文字。
    """

    TRIGGER_RECORD = "record"
    TRIGGER_KEYWORD = "keyword"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.task_tool = CatLearnSearchTask()
        self.crawler = CatLearnCrawler()
        self.agent = CatLearnAgent()

    # ==================== 异步入口 ====================
    def start_search(self, text: str, username: str, trigger: str):
        """异步发起搜索决策（不阻塞消息链路）"""
        if not text or not text.strip():
            return
        Thread(target=self._safe_search, args=(text, username, trigger), daemon=True).start()

    def _safe_search(self, text: str, username: str, trigger: str):
        try:
            self.decide_and_search(text, username, trigger)
        except Exception:
            self.log.exception("搜索决策异常")

    # ==================== 核心：决策 + Agent 挑选 + 分发 ====================
    def decide_and_search(self, text: str, username: str, trigger: str) -> bool:
        """LLM 深度思考决定搜索任务，每个 task 走 Agent 挑选结果并分发。返回是否产生搜索任务"""
        tasks = self._decide_tasks(text)
        if not tasks:
            self.log.info(f"[搜索] {trigger} 触发，AI 未设置搜索任务（无值得学习内容）")
            return False

        batch_id = self.crawler.new_batch_id()
        self.crawler.write_batch_meta(batch_id, trigger, username, tasks)
        self.log.info(f"[搜索] {trigger} 触发，批次 {batch_id} 共 {len(tasks)} 个任务")

        self._run_tasks(batch_id, tasks)

        # 分发结果
        if trigger == self.TRIGGER_KEYWORD:
            from func.database.search.search_understand import CatLearnSearchUnderstand
            CatLearnSearchUnderstand().summarize_batch(batch_id, username)
        else:
            from func.database.store.learning import CatLearnLearning
            CatLearnLearning().on_search_done(batch_id)
        return True

    # ==================== 任务执行：同站串行、异站并行 ====================
    def _run_tasks(self, batch_id: str, tasks: list):
        """按站点分组：同站串行（限速），异站并行；每个 task 跑 Agent 并落盘"""
        groups = {}
        for t in tasks:
            site = str(t.get("web_url", "") or "")
            groups.setdefault(site, []).append(t)

        with ThreadPoolExecutor(max_workers=max(1, len(groups))) as pool:
            futures = {
                pool.submit(self._run_group, batch_id, site, group): site
                for site, group in groups.items()
            }
            for fut in as_completed(futures):
                site = futures[fut]
                try:
                    fut.result()
                except Exception:
                    self.log.exception(f"站点 {site} Agent 执行组异常")

    def _run_group(self, batch_id: str, site: str, tasks: list):
        """同站串行队列：逐 task 跑 Agent 并落盘"""
        for task in tasks:
            try:
                self._run_one_task(batch_id, task)
            except Exception:
                self.log.exception(f"task 执行失败: site={site} task={task}")
            # 同站限速
            time.sleep(1.0)

    def _run_one_task(self, batch_id: str, task: dict):
        """单个 task：跑 Agent → 落盘 web_result/{batch_id}/{task_id}/"""
        result = self.agent.run(task)

        task_id = str(task.get("task_id", "0"))
        task_dir = os.path.join(self.crawler.web_result_dir, str(batch_id), task_id)
        os.makedirs(task_dir, exist_ok=True)

        meta = {
            "task_id": result.get("task_id", task_id),
            "search_keys": result.get("search_keys", ""),
            "site": result.get("site", ""),
            "status": result.get("status", "empty"),
            "rounds": result.get("rounds", 0),
            "hit_limit": result.get("hit_limit", False),
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": result.get("selected", []),
        }
        with open(os.path.join(task_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        with open(os.path.join(task_dir, "content.txt"), "w", encoding="utf-8") as f:
            f.write(result.get("content", "") or "")

    def _decide_tasks(self, text: str) -> list:
        """LLM 深度思考，决定是否调用 search_task 工具设置任务"""
        llm = get_search_llm()
        if llm is None or not llm.client:
            self.log.error("搜索模块 LLM 不可用，无法决策搜索任务")
            return []

        system_prompt = (
            "你负责从聊天记录中提取值得学习、值得搜索的有意义内容。"
            "日常对话、社交寒暄、无关闲聊直接忽略。"
            "只有当你确信能提取出针对性的专有名词/主题时，才调用工具设置搜索任务；"
            "每个任务只对应一个精准搜索词，想搜多个词就生成多个任务。"
            "如果内容全是日常闲聊、语法无法辨别、或只能得出宽泛概念（如游戏、战争、家庭），"
            "不要调用工具，直接结束。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        # 深度思考 + 不强制工具（让 AI 自行决定是否调用）
        resp = llm.chat(
            messages,
            tools=[self.task_tool.build_tool()],
            enable_thinking=True,
        )
        return CatLearnSearchTask.parse(resp)
