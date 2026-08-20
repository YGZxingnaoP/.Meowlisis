# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/group_info.py
# 群性质概括：统计 AI 发言条数，定时拉取历史并概括群话题/群性质，保存到 .NapCat/group_info/群聊名.json

import os
import json
import random
import threading
from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig


@singleton
class TBGroupInfo:
    """群性质概括模块：AI 每发 N 条消息触发一次，概括群话题/性质并落盘"""

    TOOL_NAME = "update_group_info"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self.dir = os.path.join(".NapCat", "group_info")
        # 群名 -> AI 已发送条数（内存计数）
        self._sent_count: Dict[str, int] = {}
        self._lock = threading.Lock()

    # ==================== 计数 ====================
    def on_ai_sent(self, group_id: str, group_name: str):
        """AI 在群里发送一条消息后调用，达到阈值则异步触发概括"""
        key = self._key(group_id, group_name)
        with self._lock:
            self._sent_count[key] = self._sent_count.get(key, 0) + 1
            count = self._sent_count[key]
        if count >= self.config.group_info_interval:
            with self._lock:
                self._sent_count[key] = 0
            threading.Thread(target=self.update, args=(group_id, group_name), daemon=True).start()

    @staticmethod
    def _key(group_id: str, group_name: str) -> str:
        return f"{group_name or '群'}_{group_id}"

    # ==================== 读取 / 保存 ====================
    def _path(self, group_name: str) -> str:
        safe = self._safe_name(group_name)
        return os.path.join(self.dir, f"{safe}.json")

    @staticmethod
    def _safe_name(name: str) -> str:
        import re
        return re.sub(r'[\\/:*?"<>|\r\n\t]', '_', str(name or "群聊")).strip() or "群聊"

    def load(self, group_name: str) -> dict:
        """读取群性质概括 json（缺失或损坏返回空 dict）"""
        path = self._path(group_name)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception(f"读取群性质失败: {path}")
            return {}

    def _save(self, group_name: str, data: dict):
        """保存群性质概括 json"""
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self._path(group_name), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception(f"保存群性质失败: {group_name}")

    # ==================== 提示词构建 ====================
    def build_prompt(self, group_name: str) -> str:
        """把群性质概括 json 转为 markdown 提示词（作为群聊档案替换用户档案）"""
        data = self.load(group_name)
        if not data:
            return ""
        lines = [f"# 现在你在群【{group_name}】里聊天"]
        lines.append(f"- 群名称：{data.get('group_name', group_name)}")
        topic = str(data.get("group_topic", "") or "").strip()
        if topic:
            lines.append(f"- 群聊天话题：{topic}")
        character = str(data.get("group_character", "") or "").strip()
        if character:
            lines.append(f"- 群聊性质：{character}")
        active = data.get("most_active_user") or []
        if isinstance(active, str):
            active = [active]
        if active:
            lines.append(f"- 群内活跃成员：{'、'.join(str(x) for x in active)}")
        return "\n".join(lines)

    # ==================== 概括更新 ====================
    def update(self, group_id: str, group_name: str):
        """拉取历史并概括群话题/群性质，写入 json"""
        try:
            from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
            from func.toolbox.napcat.groupchat.get_group_message import TBGetGroupMessage
            record = TBGetGroupRecord()
            gm = TBGetGroupMessage()
            recent = int(self.config.group_info_recent or 50)
            sample_range = int(self.config.group_info_sample_range or 200)
            total = recent + sample_range
            history = record.fetch_raw(group_id, total)
            if not history:
                self.log.warning(f"[群性质] 群 {group_name} 无历史，跳过概括")
                return
            # 最近 recent 条作为上下文
            context_lines = []
            for m in history[-recent:]:
                sender = m.get("sender") or {}
                sender_id = str(m.get("user_id") or sender.get("user_id") or "")
                username = str(sender.get("card") or sender.get("nickname") or sender_id or "未知").strip()
                texts = gm._parse_segments(m.get("message"))
                if texts:
                    context_lines.append(f"【{username}】:{'，'.join(texts)}")
            # recent 条之外的 sample_range 条内，抽取 15% 有效文本
            if recent > 0:
                pool = history[-(recent + sample_range):-recent]
            else:
                pool = history[:sample_range]
            valid = []
            for m in pool:
                sender = m.get("sender") or {}
                sender_id = str(m.get("user_id") or sender.get("user_id") or "")
                username = str(sender.get("card") or sender.get("nickname") or sender_id or "未知").strip()
                texts = gm._parse_segments(m.get("message"))
                if texts:
                    valid.append(f"【{username}】:{'，'.join(texts)}")
            sample_n = max(1, round(len(valid) * 0.15)) if valid else 0
            sampled = random.sample(valid, min(sample_n, len(valid))) if valid else []

            result = self._summarize(group_name, context_lines, sampled)
            if not result:
                return
            if result.get("should_update") is False:
                self.log.info(f"[群性质] AI 决定暂不更新群 {group_name} 的性质")
                return
            result.setdefault("group_name", group_name)
            self._save(group_name, result)
            self.log.info(f"[群性质] 已更新群 {group_name} 的性质: topic={result.get('group_topic', '')[:30]}")
        except Exception:
            self.log.exception(f"群性质概括异常: {group_name}")

    def _summarize(self, group_name: str, context_lines: List[str], sampled: List[str]) -> Optional[dict]:
        """调用 LLM（深度思考 + tool call）概括群话题/性质"""
        llm = self._llm()
        if llm is None or not llm.client:
            self.log.error("[群性质] LLM 不可用")
            return None
        persona = self._persona()
        sample_text = "\n".join(sampled) if sampled else "（无额外采样消息）"
        context_text = "\n".join(context_lines) if context_lines else "（无上下文）"
        messages = [
            {"role": "system", "content": (
                f"{persona}\n\n"
                f"你需要根据群聊记录，概括这个群的聊天话题与群聊性质。"
                f"开启深度思考，调用 update_group_info 工具输出结果。"
            )},
            {"role": "user", "content": (
                f"群名称：{group_name}\n\n"
                f"【最近聊天记录】\n{context_text}\n\n"
                f"【更早的随机采样消息】\n{sample_text}\n\n"
                f"请概括群聊天话题、群聊性质、以及三至五个发言多且有效的活跃成员。"
            )},
        ]
        resp = llm.chat(messages, tools=self.build_tools(), tool_choice=self.build_tool_choice(), enable_thinking=True)
        if not resp or not resp.choices:
            return None
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == self.TOOL_NAME:
                    args = json.loads(tc.function.arguments or "{}")
                    return args
        except Exception:
            self.log.exception("解析群性质工具调用失败")
        return None

    def _persona(self) -> str:
        """获取决策用角色人设提示词（前置词+角色卡+价值观+后置词，不含用户记忆/日期/摘要）"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            return TBoxGetPrompt().get_tool_prompt(None, "") or ""
        except Exception:
            return ""

    def _llm(self):
        """用 toolbox 独立 LLM 端口（深度思考）"""
        try:
            from func.toolbox.config import TBoxConfig
            cfg = TBoxConfig()
            if cfg.llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                return TBoxAliyunLLM(cfg)
            from func.toolbox.port.deepseek import TBoxDeepSeekLLM
            return TBoxDeepSeekLLM(cfg)
        except Exception:
            self.log.exception("初始化群性质 LLM 失败")
            return None

    # ==================== tool schema ====================
    def build_tools(self) -> List[dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "输出群聊性质概括结果，可决策是否需要更新保存",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "group_name": {"type": "string", "description": "群名称"},
                        "group_topic": {"type": "string", "description": "群聊天话题（由 AI 自己概括，不同于主程序 topic）"},
                        "group_character": {"type": "string", "description": "两三句话概括群聊性质和聊天内容"},
                        "most_active_user": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "群聊三至五个发言多且有效的人",
                        },
                        "should_update": {"type": "boolean", "description": "是否需要更新保存本次概括"},
                    },
                    "required": ["group_name", "group_topic", "group_character", "most_active_user", "should_update"],
                },
            },
        }]

    def build_tool_choice(self) -> dict:
        return {"type": "function", "function": {"name": self.TOOL_NAME}}
