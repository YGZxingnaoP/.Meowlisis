# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/load_usrmem.py

import os
import re
import json

from func.log.default_log import DefaultLog


class MeowLoadUserMemory:
    """用户记忆加载类：按用户名读取信息档案并构建 markdown 提示词（跳过 unknown）"""

    # 字段 → 中文标签映射
    FIELD_LABELS = {
        "nickname": "用户名称",
        "gender": "用户性别",
        "character": "用户性格",
        "likes": "喜欢的东西",
        "preference": "喜欢的事情",
        "relation": "与角色的关系",
        "birthday": "生日",
        "favorite_songs": "喜欢的歌曲",
        "favorite_shows": "喜欢的影视作品",
        "favorite_foods": "喜欢的食物",
        "tags_preference": "喜欢的话题标签",
        "affinity": "好感度",
    }

    def __init__(self):
        self.log = DefaultLog().getLogger()

    @staticmethod
    def _safe_name(uid: str) -> str:
        """清洗用户名为安全文件名（去除路径分隔等非法字符，空值回退为“空格”）"""
        if not uid:
            return "空格"
        name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', str(uid)).strip()
        return name or "空格"

    def _user_path(self, uid: str) -> str:
        """返回指定用户的档案路径（有编号走 character/userinfo/{编号}/profile.json，未绑定照旧）"""
        from func.pipeline.id_signup import IdSignupBridge
        return IdSignupBridge().profile_path_of(uid)

    def exists(self, uid: str) -> bool:
        """判断指定用户是否已有信息档案（新老位置都算）"""
        return bool(uid) and bool(self.load(uid))

    def load(self, uid: str) -> dict:
        """按用户名读取信息档案：先读编号目录，读不到再回老目录（缺失或损坏时返回空 dict）"""
        from func.pipeline.id_signup import IdSignupBridge
        return IdSignupBridge().profile_of(uid)

    def build(self, uid: str) -> str:
        """按用户名构建用户记忆 markdown（标题说明当前说话人，首行显示用户名，跳过 unknown，好感度 0 保留）"""
        data = self.load(uid)
        if not data:
            return ""
        # 展示名：唯一规则（display_name），禁止 name/uid/"默认" 多层兜底
        from func.pipeline.id_signup import display_name
        name = display_name(uid)
        lines = [f"# 现在和你说话的是{name}"]
        lines.append(f"- 用户名称：{name}")
        for key, label in self.FIELD_LABELS.items():
            if key == "nickname":
                continue  # 用户名已在档案首行显示
            raw = data.get(key, "")
            # 好感度为数值，0 是有效值需保留
            if key == "affinity":
                if raw in (None, ""):
                    continue
                lines.append(f"- {label}：{raw}")
                continue
            # tags_preference 为标签列表，用顿号连接展示
            if isinstance(raw, list):
                value = "、".join(str(x).strip() for x in raw if str(x).strip())
            else:
                value = str(raw or "").strip()
            if not value or value.lower() == "unknown":
                continue
            lines.append(f"- {label}：{value}")
        # 生活动态：近期事件概括，leisure/空 展示为“很空闲”
        recent = str(data.get("recent_events", "") or "").strip()
        if not recent or recent.lower() == "leisure":
            recent = "很空闲"
        lines.append(f"## {name}的生活动态")
        lines.append(f"- {recent}")
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
