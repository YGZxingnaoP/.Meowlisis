# -*- coding: utf-8 -*-
"""后台 Agent 入口：旧的 planner 驱动循环已删除，统一走 tool_agent。"""

from .tool_agent import Agent

__all__ = ["Agent"]
