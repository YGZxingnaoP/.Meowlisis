# -*- coding: utf-8 -*-
"""摘要去重：检索候选、LLM 比对、应用 same/opposite/origin 判定"""
import hashlib
import json
from datetime import datetime

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.evidence import MeowEvidence
from func.catbrain.AbstractMem.port import force_tool_call


class MeowDedup:
    """摘要去重类"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.summary_tool = MeowSummaryTool()
        self.evidence = MeowEvidence()
        self._llm = None

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
    def make_id(time_str, event):
        """生成事件稳定主键"""
        return "mem_" + hashlib.sha256(f"{time_str}|{event}".encode("utf-8")).hexdigest()[:12]

    def _match(self, event, item):
        """判断历史条目是否与新事件匹配"""
        event_set = set(event.get("tags") or []) | set(event.get("topics") or [])
        item_tags = item.get("tags") or []
        item_set = set(item_tags) | set(item.get("topics") or [])
        mode = self.config.dedup_match_mode
        if mode == "broad":
            return bool(item_tags and item_tags[0] in event_set)
        return len(event_set & item_set) >= 2

    def _search(self, event, data):
        """检索与新事件相关的候选旧记忆"""
        candidates = []
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            if self._match(event, item):
                candidates.append((item["id"], item.get("event", "")))
        return candidates

    def _judge(self, event, batch):
        """LLM 比对一批候选，返回候选编号到关系判定的映射"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            return {}
        lines = [f"{cid}：{text}" for cid, text in batch]
        messages = [
            {"role": "system", "content": "判断新事件与每条候选记忆的关系：same表示相同，opposite表示相反，origin表示无关。必须调用工具输出所有候选的判定。"},
            {"role": "user", "content": f"新事件：{event.get('event', '')}\n\n候选记忆：\n" + "\n".join(lines)}
        ]
        tools = self.summary_tool.build_dedup_tool()
        result = {}
        for _ in range(3):
            resp = force_tool_call(llm, messages, tools, self.summary_tool.TOOL_DEDUP_NAME)
            if not resp or not resp.choices:
                return result
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            messages.append({
                "role": "assistant",
                "content": msg.content or None,
                "reasoning_content": getattr(msg, "reasoning_content", "") or "",
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                               for tc in tool_calls]
            })
            parsed_any = False
            for tc in tool_calls:
                if tc.function.name != self.summary_tool.TOOL_DEDUP_NAME:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": "未知工具，请忽略"})
                    continue
                args = self.summary_tool.parse_arguments(tc.function.arguments)
                if not isinstance(args, dict) or "results" not in args:
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": "参数不是合法JSON，请重新调用工具，参数必须是合法JSON"})
                    continue
                parsed_any = True
                for r in args.get("results", []):
                    tid = str(r.get("text_id", ""))
                    rel = str(r.get("relation", "origin"))
                    if tid and rel in ("same", "opposite", "origin"):
                        result[tid] = rel
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "已记录判定"})
            if parsed_any:
                break
        return result

    def _apply_same(self, item, event, now_iso):
        """应用 same 判定：覆盖内容并强化"""
        evidence = item.setdefault("evidence", {})
        self.evidence.apply_signal(evidence, "same", now_iso)
        acc = int(item.get("accuracy", 5) or 5)
        item["accuracy"] = min(5, acc + self.config.accuracy_same_increment)
        item["event"] = event.get("event", item.get("event", ""))
        item["tags"] = event.get("tags", item.get("tags", []))
        item["topics"] = event.get("topics", item.get("topics", []))
        item["importance"] = event.get("importance", item.get("importance", 0))
        item["joint"] = event.get("joint", item.get("joint", []))

    def _apply_opposite(self, item, now_iso):
        """应用 opposite 判定：质疑降权"""
        evidence = item.setdefault("evidence", {})
        self.evidence.apply_signal(evidence, "opposite", now_iso)
        acc = int(item.get("accuracy", 5) or 5)
        item["accuracy"] = max(1, acc - self.config.accuracy_opposite_decrement)

    def _init_evidence(self, event, now_iso):
        """为新事件初始化证据字段"""
        rein = self.evidence.initial_reinforcement(event.get("importance", 0))
        event["evidence"] = {
            "reinforcement": rein,
            "disputation": 0.0,
            "rein_last_signal_at": now_iso if rein > 0 else None,
            "disp_last_signal_at": None,
            "sub_zero_days": 0,
            "sub_zero_last_increment_date": None
        }

    def process(self, events, data):
        """对每个新事件去重，原地更新旧记忆，返回需新增的事件列表"""
        index = {item.get("id"): item for item in data if isinstance(item, dict) and item.get("id")}
        add_events = []
        now = datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        batch_size = self.config.dedup_batch_size
        max_batches = self.config.dedup_max_batches
        for event in events:
            event["id"] = self.make_id(event.get("time", now_iso), event.get("event", ""))
            candidates = self._search(event, data)
            has_same = False
            if candidates:
                relations = {}
                for b in range(max_batches):
                    batch = candidates[b * batch_size:(b + 1) * batch_size]
                    if not batch:
                        break
                    relations.update(self._judge(event, batch))
                for cid, _text in candidates:
                    item = index.get(cid)
                    if not item:
                        continue
                    rel = relations.get(cid, "origin")
                    if rel == "same":
                        has_same = True
                        self._apply_same(item, event, now_iso)
                    elif rel == "opposite":
                        self._apply_opposite(item, now_iso)
            if not has_same:
                self._init_evidence(event, now_iso)
                add_events.append(event)
        return add_events

    def dedupe_self(self, data):
        """对数据内部做 same 合并去重，返回去重后的列表"""
        result = []
        index = {}
        now = datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        batch_size = self.config.dedup_batch_size
        max_batches = self.config.dedup_max_batches
        for item in data:
            if not isinstance(item, dict):
                result.append(item)
                continue
            candidates = self._search(item, result)
            has_same = False
            if candidates:
                relations = {}
                for b in range(max_batches):
                    batch = candidates[b * batch_size:(b + 1) * batch_size]
                    if not batch:
                        break
                    relations.update(self._judge(item, batch))
                for cid, _text in candidates:
                    target = index.get(cid)
                    if not target:
                        continue
                    rel = relations.get(cid, "origin")
                    if rel == "same":
                        has_same = True
                        self._apply_same(target, item, now_iso)
                        break
                    if rel == "opposite":
                        self._apply_opposite(target, now_iso)
            if not has_same:
                result.append(item)
                if item.get("id"):
                    index[item["id"]] = item
        return result
