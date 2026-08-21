# -*- coding: utf-8 -*-
# func/database/search/search_task.py
# 搜索任务工具：AI 设置多个搜索任务（task_id / search_keys / web_url=站点标识）

import json

from func.database.config import CatLearnConfig


class CatLearnSearchTask:
    """搜索任务工具定义与解析

    - web_url 仅为站点标识（mcmod / moegirl / gamesgg / zhihu ...），由 config.sites 提供；
    - search_keys 为【单个】精准搜索词，禁止逗号分隔；想搜多个词就生成多个 task。
    """

    TOOL_NAME = "set_search_tasks"

    def __init__(self):
        self.config = CatLearnConfig()

    def build_tool(self) -> dict:
        """构建搜索任务工具定义（web_url 用 enum 限定站点标识，并注入适用场景）"""
        site_keys = self.config.site_keys()
        # 拼接站点适用场景说明，供 AI 选择与话题最匹配的站点
        site_desc_lines = []
        for key in site_keys:
            cfg = self.config.site_config(key)
            label = cfg.get('label', key)
            desc = cfg.get('description', '')
            if desc:
                site_desc_lines.append(f"- {key}（{label}）：{desc}")
            else:
                site_desc_lines.append(f"- {key}（{label}）")
        site_desc = "\n".join(site_desc_lines) if site_desc_lines else "（无可用站点）"

        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "根据聊天记录中值得学习、值得搜索的有意义内容，设置多个搜索任务。"
                    "每个任务只针对一个精准搜索词，想搜多个词就生成多个 task。"
                    "search_keys 必须是【单个】专有名词/名称（如 暮色森林、异环、原神），"
                    "禁止用逗号分隔多个词，禁止输出过于宽泛的概念（如 游戏、战争、家庭）。"
                    "web_url 只能从给定站点标识中选择，选择与话题最匹配的站点。\n"
                    f"可选站点及适用场景：\n{site_desc}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "task_id": {"type": "integer", "description": "任务编号，从1开始递增"},
                                    "search_keys": {
                                        "type": "string",
                                        "description": "单个精准搜索词，如 暮色森林、异环、原神（禁止逗号分隔）",
                                    },
                                    "web_url": {
                                        "type": "string",
                                        "enum": site_keys,
                                        "description": "站点标识，选择与话题最匹配的站点",
                                    },
                                },
                                "required": ["task_id", "search_keys", "web_url"],
                            },
                        },
                    },
                    "required": ["tasks"],
                },
            },
        }

    @staticmethod
    def parse(resp) -> list:
        """从 LLM 响应解析搜索任务列表，返回 [{"task_id","search_keys","web_url"}, ...]"""
        if not resp or not getattr(resp, "choices", None):
            return []
        tasks = []
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name != CatLearnSearchTask.TOOL_NAME:
                    continue
                args = json.loads(tc.function.arguments or "{}")
                for t in (args.get("tasks") or []):
                    if not isinstance(t, dict):
                        continue
                    keys = str(t.get("search_keys", "") or "").strip()
                    # 去掉可能误带的逗号分隔，只取第一个精准词
                    if "，" in keys or "," in keys:
                        keys = keys.replace("，", ",").split(",")[0].strip()
                    task = {
                        "task_id": t.get("task_id"),
                        "search_keys": keys,
                        "web_url": str(t.get("web_url", "") or "").strip(),
                    }
                    if task["search_keys"] and task["web_url"]:
                        tasks.append(task)
        except Exception:
            pass
        return tasks
