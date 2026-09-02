# -*- coding: utf-8 -*-
# func/catbrain/CatValues/load_values.py
# 价值观加载：读取 character/info/values/latest.json 并转 markdown

import os
import json

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig


class MeowLoadValues:
    """价值观加载类：读取 latest.json 并构建 markdown 提示词（全部翻译为中文标签）"""

    # 字段 → 中文标签映射（0204 为主人的话，绝对禁止修改）
    FIELD_LABELS = {
        "0204": "主人的话",
        "universalism": "普世价值",
        "benevolence": "仁爱",
        "power": "权力",
        "achievement": "成就",
        "tradition": "传统",
        "self_direction": "自我导向",
        "stimulation": "刺激",
    }

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.path = os.path.join("character", "info", "values", "latest.json")

    def load(self) -> dict:
        """读取价值观数据，缺失时返回空 dict"""
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception("读取价值观失败")
            return {}

    def build(self) -> str:
        """构建价值观 markdown 提示词（跳过空值，中文标签，标题为「ai_name铭记在心」）"""
        data = self.load()
        if not data:
            return ""
        lines = [f"# {AppConfig().ai_name}铭记在心"]
        for key, label in self.FIELD_LABELS.items():
            value = str(data.get(key, "") or "").strip()
            if not value:
                continue
            lines.append(f"- {label}：{value}")
        return self._ensure_markdown("\n".join(lines))

    @staticmethod
    def _ensure_markdown(text: str) -> str:
        """检查并确保输出为 markdown 语法（缺标题或列表符时微调补全）"""
        if not text:
            return ""
        lines = text.split("\n")
        if not lines[0].startswith("#"):
            lines.insert(0, "# 价值观")
        fixed = []
        for line in lines[1:]:
            if line.strip() and not line.startswith(("#", "-", "*", ">", "|")):
                line = "- " + line
            fixed.append(line)
        return "\n".join([lines[0]] + fixed)
