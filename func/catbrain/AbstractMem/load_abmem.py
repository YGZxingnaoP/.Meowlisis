# -*- coding: utf-8 -*-
"""摘要记忆加载与提示词构建：按证据分>准确度>话题>标签>参与>重要度检索"""
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
from func.catbrain.AbstractMem.process.evidence import MeowEvidence
from func.catbrain.AbstractMem.port import force_tool_call
from func.catbrain.txt_reader.jieba_segment import MeowJiebaSegmentTool
from func.pipeline.short_memory import ShortMemory


class MeowLoadAbstractMemory:
    """摘要记忆读取类：读取 meow-*.json 并检索构建 markdown 提示词"""

    # 相关性：内容关键词命中数量达到该值即视为完全相关
    OVERLAP_SATURATION = 1.0
    # 相关性：内容/标签/话题/参与的权重
    REL_WEIGHTS = {"text": 0.5, "tags": 0.2, "topic": 0.2, "joint": 0.1}
    # 综合排序：相关性+新近度合计过半，避免历史证据分一票通吃
    RANK_WEIGHTS = {"strength": 0.20, "accuracy": 0.10, "relevance": 0.45,
                    "recency": 0.15, "importance": 0.10}
    # 内容关键词命中时忽略的高频词
    STOPWORDS = {"我", "你", "他", "她", "它", "我们", "你们", "他们", "的", "了", "是", "说",
                 "就", "都", "和", "跟", "有", "在", "也", "还", "又", "很", "太", "把", "被",
                 "这个", "那个", "什么", "怎么", "一起", "然后", "因为", "所以", "但是", "如果",
                 "主人", "喵呜", "喵利呜西斯", "今天", "现在", "一下", "觉得", "知道", "记得",
                 "之前", "之后", "以后", "以前", "时候", "事情", "好像", "还有", "一些", "一直",
                 "已经", "出来", "起来", "开始", "继续", "真的", "确实", "肯定", "到底", "反正"}
    # 注入时相关性保底判定的最低相关性
    RELEVANCE_THRESHOLD = 0.15

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.jieba_tool = MeowJiebaSegmentTool()
        self.summary_tool = MeowSummaryTool()
        self.evidence = MeowEvidence()
        self.short_memory = ShortMemory()
        self.meow_dir = os.path.join("character", "abstract_memory")
        self.topic_path = os.path.join(".temp", "current_topic.json")
        self._saved_topic = None
        self._topic_cache = ""
        self._topic_cache_time = 0.0
        self._llm = None
        self._lock = threading.Lock()

    def _ensure_llm(self):
        """懒加载摘要独立 LLM 客户端"""
        if self._llm is None:
            if self.config.abstract_llm_type == "gemini":
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
        """按当前月份生成摘要文件路径"""
        yymm = datetime.datetime.now().strftime("%y%m")
        return os.path.join("character", "abstract_memory", f"meow-{yymm}.json")

    def load(self) -> List[Dict]:
        """读取所有 meow-*.json 摘要记忆并按 id 去重"""
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
        """从条目的 time 字段提取月份 YYMM；缺失或格式异常时回退当前月份"""
        if isinstance(item, dict) and item.get("time"):
            m = re.match(r"^(\d{4})-(\d{2})", str(item["time"]))
            if m:
                return m.group(1)[2:] + m.group(2)
        return datetime.datetime.now().strftime("%y%m")

    def save(self, data: List[Dict]):
        """按条目 time 字段的月份分文件写回，避免跨月数据整体写入当月文件

        - 每个条目按自己的月份落入 meow-YYMM.json（time 缺失回退当前月，不丢数据）；
        - 同月内按 id 去重（保留首次出现的条目）。
        """
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

    def _current_topic(self, data: List[Dict]) -> str:
        """当前话题：缓存优先，过期后决策，失败回退最新摘要"""
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
        """话题更新后落盘到 .temp/current_topic.json"""
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
        """用短期记忆强制工具调用决策当前话题"""
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

    def decide_recall(self, message: str = "", username: str = "") -> Dict:
        """判定消息是否需要加强回忆及对应时间窗口"""
        empty = {"need_recall": False, "months": [], "label": ""}
        if not self.config.abmem_recall_enabled:
            return empty
        text = str(message or "").strip()
        if not text:
            return empty
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            return empty
        limit = max(1, int(self.config.abmem_recall_months_limit or 3))
        now = datetime.datetime.now()
        weekday = "星期" + "一二三四五六日"[now.weekday()]
        system_text = ("判断用户这句话是否在要求回忆过去的事。若是，给出对应的时间窗口月份列表"
                       f"（整年同月，格式 YYYY-MM，最多{limit}个）；看不出时间窗口时 need_recall 必须为 false 且 months 留空。")
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
        """规范化月份列表：格式校验、去重、限量"""
        result = []
        for m in (months or []):
            m = str(m or "").strip()
            if len(m) != 7 or m[4] != "-" or not (m[:4].isdigit() and m[5:].isdigit()):
                continue
            if m not in result:
                result.append(m)
            if len(result) >= limit:
                break
        return result

    def _tags_similarity(self, item: Dict, msg_words: set) -> float:
        """计算摘要 tags 与当前消息 jieba 关键词相似度"""
        tags = item.get("tags") or []
        if not tags or not msg_words:
            return 0.0
        best = 0.0
        for tag in tags[:3]:
            tag_words = set(self.jieba_tool.segment(str(tag)))
            if not tag_words:
                continue
            overlap = len(tag_words & msg_words)
            score = overlap / len(tag_words)
            if score > best:
                best = score
        return best

    def _joint_similarity(self, item: Dict, username: str) -> float:
        """计算 joint 相似度"""
        joint = item.get("joint") or []
        if not username:
            return 0.0
        return 1.0 if username in joint else 0.0

    @staticmethod
    def _format_time(item: Dict) -> str:
        """把条目 time 转为可读日期时间"""
        ts = str((item or {}).get("time") or "").strip()
        if not ts:
            return ""
        parts = ts.split("-")
        if len(parts) >= 5:
            return f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}"
        return ts

    @staticmethod
    def _item_month(item: Dict) -> str:
        """取条目 time 的年月（YYYY-MM）"""
        ts = str((item or {}).get("time") or "")
        return ts[:7] if len(ts) >= 7 else ""

    def _prioritize_months(self, ranked: List, months) -> List:
        """把时间窗口内的条目提到最前，其余保持原顺序"""
        want = {str(m).strip() for m in (months or []) if str(m).strip()}
        if not want:
            return ranked
        in_window, rest = [], []
        for row in ranked:
            (in_window if self._item_month(row[2]) in want else rest).append(row)
        return in_window + rest

    @staticmethod
    def _age_days(item: Dict, now) -> float:
        """按条目 time 计算距今天数（支持 YYYY-MM-DD-HH-MM 等格式）"""
        ts = item.get("time") if isinstance(item, dict) else None
        if not ts:
            return 0.0
        for fmt in ("%Y-%m-%d-%H-%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.datetime.strptime(str(ts), fmt)
            except ValueError:
                continue
            delta = (now - parsed).total_seconds()
            return delta / 86400 if delta > 0 else 0.0
        return 0.0

    def _text_similarity(self, item: Dict, msg_words: set) -> float:
        """计算摘要内容与当前消息的关键词命中度（子串命中，兼容复合词切分差异）"""
        if not msg_words:
            return 0.0
        event = str(item.get("event") or "")
        if not event:
            return 0.0
        words = msg_words - self.STOPWORDS
        if not words:
            return 0.0
        hits = sum(1 for w in words if w in event)
        return min(1.0, hits / self.OVERLAP_SATURATION)

    def _relevance(self, item: Dict, current_topic: str, msg_words: set, username: str) -> float:
        """计算条目与当前对话的相关性（内容/标签/话题/参与加权）"""
        topics = item.get("topics") or []
        w = self.REL_WEIGHTS
        return (w["text"] * self._text_similarity(item, msg_words)
                + w["tags"] * self._tags_similarity(item, msg_words)
                + w["topic"] * (1.0 if (current_topic and current_topic in topics) else 0.0)
                + w["joint"] * self._joint_similarity(item, username))

    def _score(self, item: Dict, current_topic: str, msg_words: set, username: str, now):
        """计算单条摘要的(综合分, 相关性分)，证据分为负时返回 None"""
        evidence = item.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        score = self.evidence.score(evidence, now)
        if score < 0:
            return None
        saturation = float(self.config.rank_evidence_saturation or 5.0) or 5.0
        strength = min(score, saturation) / saturation
        try:
            accuracy = float(item.get("accuracy", 0) or 0) / 5.0
        except (TypeError, ValueError):
            accuracy = 0.0
        relevance = self._relevance(item, current_topic, msg_words, username)
        half_life = float(self.config.rank_recency_half_life_days or 14) or 14.0
        age = self._age_days(item, now)
        recency = 0.5 ** (age / half_life) if age > 0 else 1.0
        try:
            importance = float(item.get("importance", 0) or 0) / 10.0
        except (TypeError, ValueError):
            importance = 0.0
        w = self.RANK_WEIGHTS
        total = (w["strength"] * strength + w["accuracy"] * accuracy
                 + w["relevance"] * relevance + w["recency"] * recency
                 + w["importance"] * importance)
        return total, relevance

    def _rank(self, data: List[Dict], current_message: str, username: str,
              topic_override: str = "") -> List:
        """按综合分（相关性/新近度/证据/准确度/重要度）排序，返回 [(总分, 相关性, 条目)]"""
        current_topic = topic_override or self._current_topic(data)
        msg_words = set(self.jieba_tool.segment(current_message)) if current_message else set()
        now = datetime.datetime.now()
        scored = []
        for item in data:
            if not isinstance(item, dict):
                continue
            result = self._score(item, current_topic, msg_words, username, now)
            if result is None:
                continue
            scored.append((result[0], result[1], item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    @staticmethod
    def _event_key(item: Dict) -> str:
        """条目文本归一化键（用于注入前去重）"""
        return re.sub(r"\s+", "", str(item.get("event") or ""))

    def _select(self, ranked: List, limit: int) -> List[Dict]:
        """挑选注入条目：先保证相关性保底，再按综合分补齐，并做文本去重"""
        guarantee = max(0, int(self.config.summary_relevance_guarantee or 0))
        selected, seen = [], set()
        for _total, relevance, item in ranked:
            if len(selected) >= guarantee:
                break
            key = self._event_key(item)
            if key in seen or relevance < self.RELEVANCE_THRESHOLD:
                continue
            seen.add(key)
            selected.append(item)
        for _total, _relevance, item in ranked:
            if len(selected) >= limit:
                break
            key = self._event_key(item)
            if key in seen:
                continue
            seen.add(key)
            selected.append(item)
        return selected[:limit]

    def build_prompt(self, current_message: str = "", username: str = "", limit: int = None,
                     topic_override: str = "", need_recall: bool = False, time_hint=None) -> str:
        """构建记忆摘要 markdown 提示词（相关性保底 + 文本去重 + 可优先时间窗口）"""
        data = self.load()
        if not data:
            return ""
        limit = limit if limit is not None else self.config.summary_top_limit
        limit = max(int(limit or 0), int(self.config.summary_relevance_guarantee or 0))
        ranked = self._rank(data, current_message, username, topic_override)
        if need_recall and isinstance(time_hint, dict):
            ranked = self._prioritize_months(ranked, time_hint.get("months"))
        lines = [f"# {AppConfig().ai_name}的记忆"]
        for item in self._select(ranked, limit):
            topics = "、".join(item.get("topics") or [])
            tags = "、".join(item.get("tags") or [])
            joint = "、".join(item.get("joint") or [])
            meta = f"话题:{topics}"
            if tags:
                meta += f" | 标签:{tags}"
            if joint:
                meta += f" | 参与:{joint}"
            when = self._format_time(item)
            if when:
                meta += f" | 时间:{when}"
            lines.append(f"- [{meta}] {item.get('event', '')}")
        return self._ensure_markdown("\n".join(lines))

    @staticmethod
    def _ensure_markdown(text: str) -> str:
        """确保输出为 markdown 语法"""
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
