# -*- coding: utf-8 -*-
# func/llm_active/director/act.py
# 导演主动动作：只触发父级模块入口，把 instruction 交给子链路决策执行

import threading
import time

from func.log.default_log import DefaultLog
from func.llm_active.director.config import AutoDirectorConfig
from func.pipeline.llm_toolbox import LLMToolboxBridge


class DirectorAct:
    """父级动作执行器（导演专用）：白名单 / 冷却 / 去重 / 后台执行 / 结果回写计划"""

    def __init__(self, core):
        self.log = DefaultLog().getLogger()
        self.core = core
        self.toolbox = LLMToolboxBridge()
        self.cfg = AutoDirectorConfig()
        self._lock = threading.Lock()
        self._recent = {}
        self._inflight = set()
        self._catalog = []
        self._catalog_at = 0.0

    # ==================== 目录 ====================
    def catalog(self):
        """可用父级入口（白名单过滤）；空表示这次不挂动作工具"""
        if not self.cfg.tool_enabled:
            return []
        now = time.time()
        with self._lock:
            if self._catalog and now - self._catalog_at < 60:
                return list(self._catalog)
        allowed = set(self.cfg.tool_whitelist)
        rows = [row for row in self.toolbox.entry_catalog()
                if str(row.get("name") or "") in allowed]
        with self._lock:
            self._catalog = rows
            self._catalog_at = now
        return list(rows)

    # ==================== 触发 ====================
    def execute(self, name: str, instruction: str, uid: str, user_text: str = "",
                why: str = "") -> bool:
        """执行一次父级动作；返回 False 表示被白名单/冷却/上限挡下"""
        if not self.cfg.tool_enabled:
            return False
        tool = str(name or "").strip()
        body = str(instruction or "").strip()
        if not tool or not body:
            return False
        if tool not in set(self.cfg.tool_whitelist):
            self.log.warning(f"[导演动作] 拒绝非白名单入口: {tool}")
            return False
        plan = self.core.current_plan()
        if not plan.get("active"):
            return False
        actions = list(plan.get("actions") or [])
        limit = int(self.cfg.tool_max_per_plan)
        if limit > 0 and len(actions) >= limit:
            self.log.info(f"[导演动作] 本场动作已达上限 {limit}，忽略 {tool}")
            return False
        now = time.time()
        key = (tool, body[:120])
        with self._lock:
            if now - float(self._recent.get(tool, 0)) < max(0.0, self.cfg.tool_cooldown):
                self.log.info(f"[导演动作] {tool} 冷却中，忽略")
                return False
            if key in self._inflight:
                return False
            self._inflight.add(key)
            self._recent[tool] = now
        threading.Thread(target=self._run, args=(tool, body, uid, user_text, why),
                         daemon=True, name="director-act").start()
        return True

    # ==================== 内部 ====================
    def _run(self, tool: str, instruction: str, uid: str, user_text: str, why: str):
        key = (tool, instruction[:120])
        try:
            args = self._arguments(tool, instruction)
            self.log.info(f"[导演动作] 触发 {tool}: {instruction[:60]}")
            result = self.toolbox.dispatch_entry(tool, args, uid, user_text or instruction)
            self.core.note_action(tool, instruction, result, why)
            self.log.info(f"[导演动作] {tool} 结果: {str(result)[:120]}")
        except Exception:
            self.log.exception(f"[导演动作] 执行失败: {tool}")
        finally:
            with self._lock:
                self._inflight.discard(key)

    @staticmethod
    def _arguments(tool: str, instruction: str) -> dict:
        if tool == "flux_paint":
            return {"request": instruction, "topic": "导演主动"}
        if tool == "use_vision":
            return {"user_message": instruction}
        return {"request": instruction}

    def cancel(self):
        """导演结束：清掉冷却/在途标记（后台线程跑到一半不强行杀）"""
        with self._lock:
            self._recent.clear()
            self._inflight.clear()
