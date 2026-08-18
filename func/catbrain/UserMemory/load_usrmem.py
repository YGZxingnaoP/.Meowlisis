# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/load_usrmem.py
# 用户记忆加载：读取 character/info/users_info/用户名_latest.json 并转 markdown

import os
import re
import json

from func.log.default_log import DefaultLog


class MeowLoadUserMemory:
    """用户记忆加载类：按用户名读取信息档案并构建 markdown 提示词（跳过 unknown）"""

    # 字段 → 中文标签映射
    FIELD_LABELS = {
        "name": "用户名称",
        "gender": "用户性别",
        "character": "用户性格",
        "likes": "喜欢的东西",
        "preference": "喜欢的事情",
        "relation": "与角色的关系",
        "birthday": "生日",
        "favorite_songs": "喜欢的歌曲",
        "favorite_shows": "喜欢的影视作品",
        "favorite_foods": "喜欢的食物",
        "affinity": "好感度",
    }

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.dir = os.path.join("character", "info", "users_info")

    @staticmethod
    def _safe_name(username: str) -> str:
        """清洗用户名为安全文件名（去除路径分隔等非法字符，空值回退为“空格”）"""
        if not username:
            return "空格"
        name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', str(username)).strip()
        return name or "空格"

    def _user_path(self, username: str) -> str:
        """返回指定用户的档案文件路径（用户名_latest.json）"""
        return os.path.join(self.dir, f"{self._safe_name(username)}_latest.json")

    def exists(self, username: str) -> bool:
        """判断指定用户是否已有信息档案"""
        return bool(username) and os.path.exists(self._user_path(username))

    def load(self, username: str) -> dict:
        """按用户名读取信息档案（缺失或损坏时返回空 dict）"""
        path = self._user_path(username)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception(f"读取用户档案失败: {path}")
            return {}

    def build(self, username: str) -> str:
        """按用户名构建用户记忆 markdown 提示词（标题直接为用户名，跳过 unknown，好感度 0 保留）"""
        data = self.load(username)
        if not data:
            return ""
        lines = [f"# {username or '默认'}"]
        for key, label in self.FIELD_LABELS.items():
            raw = data.get(key, "")
            # 好感度为数值，0 是有效值需保留
            if key == "affinity":
                if raw in (None, ""):
                    continue
                lines.append(f"- {label}：{raw}")
                continue
            value = str(raw or "").strip()
            if not value or value.lower() == "unknown":
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
            lines.insert(0, "# 用户记忆")
        fixed = []
        for line in lines[1:]:
            if line.strip() and not line.startswith(("#", "-", "*", ">", "|")):
                line = "- " + line
            fixed.append(line)
        return "\n".join([lines[0]] + fixed)
