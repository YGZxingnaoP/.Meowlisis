# -*- coding: utf-8 -*-
import os
import re
import json
import time
import datetime
import threading
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.record.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.process.recall_index import get_index, warm_index
from func.catbrain.AbstractMem.port import force_tool_call
from func.catbrain.AbstractMem import joint_util
from func.catbrain.txt_reader.jieba_segment import MeowJiebaSegmentTool
from func.pipeline.short_memory import ShortMemory


class MeowLoadAbstractMemory:

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.jieba_tool = MeowJiebaSegmentTool()
        self.summary_tool = MeowSummaryTool()
        self.short_memory = ShortMemory()
        self.meow_dir = os.path.join("character", "abstract_memory")
        self.topic_path = os.path.join(".temp", "current_topic.json")
        self._saved_topic = None
        self._topic_cache = ""
        self._topic_cache_time = 0.0
        self._llm = None
        self._lock = threading.Lock()

    def _ensure_llm(self):
        if self._llm is None:
            if self.config.abstract_llm_type == "meowllm":
                from func.catbrain.AbstractMem.port.meowllm import MeowAbstractMeowLLM
                self._llm = MeowAbstractMeowLLM()
            elif self.config.abstract_llm_type == "gemini":
                from func.catbrain.AbstractMem.port.gemini import MeowAbstractGeminiLLM
                self._llm = MeowAbstractGeminiLLM()
            elif self.config.abstract_llm_type == "aliyun":
                from func.catbrain.AbstractMem.port.aliyun import MeowAbstractAliyunLLM
                self._llm = MeowAbstractAliyunLLM()
            else:
                from func.catbrain.AbstractMem.port.deepseek import MeowAbstractDeepSeekLLM
                self._llm = MeowAbstractDeepSeekLLM()
        return self._llm

    @staticmethod
    def _current_meow_path() -> str:
        yymm = datetime.datetime.now().strftime("%y%m")
        return os.path.join("character", "abstract_memory", f"meow-{yymm}.json")

    def load(self) -> List[Dict]:
        result = []
        seen = set()
        if not os.path.isdir(self.meow_dir):
            return result
        try:
            for fname in sorted(os.listdir(self.meow_dir)):
                if not (fname.startswith("meow-") and fname.endswith(".json")):
                    continue
                path = os.path.join(self.meow_dir, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if not isinstance(item, dict):
                                result.append(item)
                                continue
                            item_id = item.get("id")
                            if item_id:
                                if item_id in seen:
                                    continue
                                seen.add(item_id)
                            result.append(item)
                except Exception:
                    self.log.exception(f"读取 {fname} 失败")
        except Exception:
            self.log.exception("读取摘要目录失败")
        return result

    @staticmethod
    def _month_of(item: Dict) -> str:
        if isinstance(item, dict) and item.get("time"):
            m = re.match(r"^(\d{4})-(\d{2})", str(item["time"]))
            if m:
                return m.group(1)[2:] + m.group(2)
        return datetime.datetime.now().strftime("%y%m")

    def save(self, data: List[Dict]):
        os.makedirs(self.meow_dir, exist_ok=True)
        by_month: Dict[str, List[Dict]] = {}
        seen: set = set()
        for item in data:
            if not isinstance(item, dict):
                by_month.setdefault(datetime.datetime.now().strftime("%y%m"), []).append(item)
                continue
            item_id = item.get("id")
            if item_id:
                if item_id in seen:
                    continue
                seen.add(item_id)
            month = self._month_of(item)
            by_month.setdefault(month, []).append(item)
        with self._lock:
            for month, items in by_month.items():
                path = os.path.join(self.meow_dir, f"meow-{month}.json")
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(items, f, ensure_ascii=False, indent=2)
                except Exception:
                    self.log.exception(f"写入摘要文件失败: {path}")
        try:
            warm_index(self.meow_dir, data, self.jieba_tool)
        except Exception:
            self.log.exception("重建记忆索引失败")

    def _current_topic(self, data: List[Dict]) -> str:
        now = time.time()
        if self._topic_cache and (now - self._topic_cache_time) < self.config.topic_update_interval:
            self._save_topic(self._topic_cache)
            return self._topic_cache
        topic = self._decide_topic()
        if topic:
            self._topic_cache = topic
            self._topic_cache_time = now
            self._save_topic(topic)
            return topic
        if not data:
            return ""
        topics = data[-1].get("topics") or []
        fallback = topics[0] if topics else ""
        self._save_topic(fallback)
        return fallback

    def _save_topic(self, topic: str):
        if not topic or topic == self._saved_topic:
            return
        try:
            os.makedirs(os.path.dirname(self.topic_path), exist_ok=True)
            with open(self.topic_path, "w", encoding="utf-8") as f:
                json.dump({"topic": topic}, f, ensure_ascii=False)
            self._saved_topic = topic
        except Exception:
            self.log.exception("保存当前话题失败")

    def _decide_topic(self) -> str:
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            return ""
        records = self.short_memory.load()
        if not records:
            return ""
        lines = []
        for m in records[-20:]:
            role = "用户" if m.get("role") == "user" else "AI"
            lines.append(f"{role}：{m.get('content', '')}")
        content = "\n".join(lines)
        messages = [
            {"role": "system", "content": "根据以下最近对话内容，判断当前对话的话题。"},
            {"role": "user", "content": content},
        ]
        resp = force_tool_call(llm, messages, self.summary_tool.build_topic_tool(), "decide_topic")
        if not resp or not resp.choices:
            return ""
        msg = resp.choices[0].message
        for tc in (msg.tool_calls or []):
            if tc.function.name == "decide_topic":
                args = self.summary_tool.parse_arguments(tc.function.arguments)
                topic = str((args or {}).get("topic", "") or "").strip()
                if topic in self.summary_tool.TOPICS:
                    return topic
        return ""

    def decide_recall(self, message: str = "", uid: str = "") -> Dict:
        empty = {"need_recall": False, "months": [], "label": ""}
        if not self.config.abmem_recall_enabled:
            return empty
        text = str(message or "").strip()
        if not text:
            return empty
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            return empty
        try:
            limit = max(0, int(self.config.abmem_recall_months_limit))
        except (TypeError, ValueError):
            limit = 3
        limit_text = f"最多{limit}个" if limit > 0 else "不限数量"
        now = datetime.datetime.now()
        weekday = "星期" + "一二三四五六日"[now.weekday()]
        system_text = ("判断用户这句话是否在要求回忆过去的事。若是，给出对应的时间窗口月份列表"
                       f"（整年同月，格式 YYYY-MM，{limit_text}）；看不出时间窗口时 need_recall 必须为 false 且 months 留空。")
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": f"当前时间：{now.strftime('%Y-%m-%d %H:%M')} {weekday}\n用户消息：{text}"},
        ]
        resp = force_tool_call(llm, messages, self.summary_tool.build_recall_tool(),
                               self.summary_tool.RECALL_TOOL_NAME)
        if not resp or not resp.choices:
            return empty
        for tc in (resp.choices[0].message.tool_calls or []):
            if tc.function.name != self.summary_tool.RECALL_TOOL_NAME:
                continue
            args = self.summary_tool.parse_arguments(tc.function.arguments)
            if not isinstance(args, dict):
                continue
            months = self._normalize_months(args.get("months"), limit)
            need = bool(args.get("need_recall")) and bool(months)
            return {"need_recall": need, "months": months, "label": str(args.get("label") or "")}
        return empty

    @staticmethod
    def _normalize_months(months, limit) -> List[str]:
        result = []
        for m in (months or []):
            m = str(m or "").strip()
            if len(m) != 7 or m[4] != "-" or not (m[:4].isdigit() and m[5:].isdigit()):
                continue
            if m not in result:
                result.append(m)
            if limit > 0 and len(result) >= limit:
                break
        return result

    @staticmethod
    def _format_time(item: Dict) -> str:
        ts = str((item or {}).get("time") or "").strip()
        if not ts:
            return ""
        parts = ts.split("-")
        if len(parts) >= 5:
            return f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}"
        return ts

    @staticmethod
    def _event_key(item: Dict) -> str:
        return re.sub(r"\s+", "", str(item.get("event") or ""))

    @classmethod
    def _render(cls, item: Dict) -> str:
        meta = f"话题:{'、'.join(item.get('topics') or [])}"
        tags = "、".join(item.get("tags") or [])
        if tags:
            meta += f" | 标签:{tags}"
        joint = joint_util.text(item)
        if joint:
            meta += f" | 参与:{joint}"
        when = cls._format_time(item)
        if when:
            meta += f" | 时间:{when}"
        return f"- [{meta}] {item.get('event', '')}"

    def build_prompt(self, current_message: str = "", uid: str = "", limit: int = None,
                     topic_override: str = "", need_recall: bool = False, time_hint=None) -> str:
        data = self.load()
        if not data:
            return ""

        index = get_index(self.meow_dir, data, self.jieba_tool)
        cap = int(limit) if limit is not None else int(self.config.summary_top_limit or 0)
        gate_ratio = float(self.config.recall_gate_ratio)

        months = index.retro_months(current_message)
        if need_recall and isinstance(time_hint, dict):
            for month in (time_hint.get("months") or []):
                month = str(month or "").strip()
                if len(month) == 7 and month not in months:
                    months.append(month)

        topic = topic_override or self._current_topic(data)
        picked = index.recall(current_message, months, gate_ratio, topic=topic)
        if not picked:
            return ""

        lines = [f"# {AppConfig().ai_name}的记忆"]
        seen = set()
        used = 0
        for doc_id in picked:
            item = index.docs.get(doc_id)
            if not isinstance(item, dict):
                continue
            key = self._event_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(self._render(item))
            used += 1
            if cap > 0 and used >= cap:
                break
        if used == 0:
            return ""
        return self._ensure_markdown("\n".join(lines))

    @staticmethod
    def _ensure_markdown(text: str) -> str:
        if not text:
            return ""
        lines = text.split("\n")
        if not lines[0].startswith("#"):
            lines.insert(0, "# 记忆摘要")
        fixed = []
        for line in lines[1:]:
            if line.strip() and not line.startswith(("#", "-", "*", ">", "|")):
                line = "- " + line
            fixed.append(line)
        return "\n".join([lines[0]] + fixed)
