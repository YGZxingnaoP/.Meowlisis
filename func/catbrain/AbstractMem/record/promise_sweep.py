# -*- coding: utf-8 -*-
import os
import re
import glob
import datetime
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.record.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory
from func.catbrain.AbstractMem.process.dedup import MeowDedup
from func.catbrain.AbstractMem.port import force_tool_call
from func.catbrain.txt_reader.jieba_segment import MeowJiebaSegmentTool


class MeowPromiseSweep:
    """临时约定清理：每次摘要时判定带 temp_promise 的条目是否已完成"""

    TOOL_NAME = "resolve_temp_promises"
    TAG = MeowSummaryTool.TEMP_PROMISE_TAG
    MAX_LEN = 50
    EVIDENCE_LIMIT = 3
    EVIDENCE_DAYS = 30
    KEYWORD_LIMIT = 5
    RELATIVE_WORDS = ("今天", "明天", "昨天", "周末", "下周", "上周", "最近", "近期",
                      "今晚", "昨晚", "等会儿", "一会儿", "下次", "以后", "今年")
    PROMISE_WORDS = ("约定", "答应", "说好", "承诺", "尚未", "还没", "暂时", "正在")
    STOP_WORDS = {"主人", "喵呜", "喵利呜西斯", "自己", "什么", "这个", "那个", "然后",
                  "已经", "还是", "就是", "没有", "不是", "一个", "这次", "今天", "昨天",
                  "明天", "答应", "承诺", "约定", "说好", "待会儿", "时候", "事情"}
    GENERIC_TAGS = {"闲聊", "日常", "情感", "爱好", "哲思", "社交", "直播互动",
                    "视频分享", "图片分享", "约定"}
    EVIDENCE_BLOCK = ("答应", "承诺", "约定", "说好", "欠", "挂账", "还没", "尚未",
                      "下次", "以后", "记着", "记着这笔")
    COMPLETION_MARKERS = ("了", "给", "收到", "拿到", "弄到", "看完", "看到", "看", "玩",
                          "唱", "哼", "去", "做", "完成", "结束", "买", "送", "见", "陪", "支招")
    DIALOG_MARKERS = ("了", "过", "已经", "完成", "结束", "收到", "拿到", "弄到",
                      "看完", "去了", "给了")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.loader = MeowLoadAbstractMemory()
        self.dedup = MeowDedup()
        self.jieba = MeowJiebaSegmentTool()

    def _load_prompt(self) -> str:
        """读取临时约定清理指令"""
        path = os.path.join("func", "catbrain", "AbstractMem", "record", "temp_promise_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            self.log.exception("读取临时约定清理指令失败")
            return ("你是{ai_name}的记忆整理员。现在是{now}。下面带 temp_promise 的条目是有时效的约定。"
                    "只依据本段对话与证据片段判断是否完成，禁止推断，拿不准一律 pending；"
                    "已完成的去掉承诺语气改成客观事实，50 字以内，其余留空；"
                    "一次性把全部条目按编号写进 resolve_temp_promises。")

    def build_tool(self) -> List[Dict]:
        """构建临时约定判定工具"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "逐条判定临时约定是否已完成，已完成的给出改写后的客观描述",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "results": {
                            "type": "array",
                            "description": "与待判定条目一一对应的结论",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "index": {"type": "integer", "description": "条目编号"},
                                    "state": {"type": "string", "enum": ["done", "pending"],
                                              "description": "done 已完成，pending 未完成或无法判断"},
                                    "event": {"type": "string", "description": "done 时改写后的客观描述，pending 留空"},
                                    "quote": {"type": "string", "description": "done 时必填：从本段对话或证据里原样复制一句能证明完成的话"}
                                },
                                "required": ["index", "state"]
                            }
                        }
                    },
                    "required": ["results"]
                }
            }
        }]

    def collect(self, data: List[Dict]) -> List[Dict]:
        """取出带 tag 的条目"""
        items = []
        for item in data:
            if not isinstance(item, dict):
                continue
            tags = item.get("tags")
            if isinstance(tags, list) and self.TAG in tags:
                items.append(item)
        limit = max(1, int(self.config.temp_promise_max_items or 30))
        return items[:limit]

    def _load_history(self) -> List[tuple]:
        """读取长期记忆原始记录，返回 (日期, 行内容)"""
        rows = []
        for path in sorted(glob.glob(os.path.join("character", "memory", "*.txt"))):
            date = os.path.basename(path)[:10]
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            rows.append((date, line))
            except Exception:
                continue
        return rows

    def _keywords(self, event: str) -> List[str]:
        """取事件里的内容关键词"""
        jieba = getattr(self, "jieba", None)
        if jieba is None:
            return []
        try:
            words = jieba.segment(str(event or ""))
        except Exception:
            return []
        words = [w for w in words if len(w) >= 2 and w not in self.STOP_WORDS]
        words = sorted(set(words), key=len, reverse=True)
        return words[:self.KEYWORD_LIMIT]

    @staticmethod
    def _window(since: str):
        """返回约定之后 EVIDENCE_DAYS 天的日期上界"""
        if not since:
            return ""
        try:
            start = datetime.datetime.strptime(since[:10], "%Y-%m-%d")
        except ValueError:
            return ""
        return (start + datetime.timedelta(days=MeowPromiseSweep.EVIDENCE_DAYS)).strftime("%Y-%m-%d")

    def _memory_evidence(self, item: Dict, data: List[Dict]) -> List[str]:
        """从已有记忆里找该约定之后同主题的条目"""
        tags = [t for t in (item.get("tags") or [])
                if t not in MeowSummaryTool.SYSTEM_TAGS and t not in self.GENERIC_TAGS]
        if not tags:
            return []
        since = str(item.get("time") or "")
        end = self._window(since)
        scored = []
        for other in data:
            if not isinstance(other, dict) or other is item:
                continue
            if other.get("id") and other.get("id") == item.get("id"):
                continue
            other_tags = other.get("tags")
            if not isinstance(other_tags, list):
                continue
            if self.TAG in other_tags:
                continue
            other_time = str(other.get("time") or "")
            if since and other_time < since:
                continue
            if end and other_time[:10] > end:
                continue
            hit = len(set(tags) & set(other_tags))
            if hit <= 0:
                continue
            event = str(other.get("event") or "")
            if any(w in event for w in self.EVIDENCE_BLOCK):
                continue
            scored.append((hit, other_time, event))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [f"记忆 {time} {event[:80]}" for _, time, event in scored[:self.EVIDENCE_LIMIT]]

    def _evidence(self, item: Dict, history: List[tuple], data: List[Dict]) -> List[str]:
        """从已有记忆与历史记录里找与该条目相关的证据行"""
        result = self._memory_evidence(item, data)
        keywords = self._keywords(item.get("event", ""))
        if keywords and history:
            since = str(item.get("time") or "")[:10]
            end = self._window(since)
            scored = []
            for date, line in history:
                if since and date < since:
                    continue
                if end and date > end:
                    continue
                if any(w in line for w in self.EVIDENCE_BLOCK):
                    continue
                hit = sum(1 for k in keywords if k in line)
                if hit <= 0:
                    continue
                scored.append((hit, date, line))
            scored.sort(key=lambda x: (-x[0], x[1]))
            for _, date, line in scored[:max(0, self.EVIDENCE_LIMIT - len(result))]:
                result.append(f"{date} {line[:100]}")
        return result[:self.EVIDENCE_LIMIT]

    def _messages(self, items: List[Dict], content: str, history: List[tuple],
                  data: List[Dict]) -> List[Dict]:
        """构建判定消息"""
        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item.get('time', '')} | {item.get('event', '')}")
            for row in self._evidence(item, history, data):
                lines.append(f"   证据：{row}")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        system_text = self._load_prompt().format(ai_name=AppConfig().ai_name, now=now)
        return [
            {"role": "system", "content": system_text},
            {"role": "user", "content": "【本段对话】\n" + (str(content or "") or "（无）")},
            {"role": "user", "content": "【待判定条目】\n" + "\n".join(lines)},
        ]

    def _parse(self, resp) -> Dict[int, Dict]:
        """解析工具调用结果，返回 编号到结论 的映射"""
        if not resp or not resp.choices:
            return {}
        for tc in (getattr(resp.choices[0].message, "tool_calls", None) or []):
            if tc.function.name != self.TOOL_NAME:
                continue
            args = MeowSummaryTool.parse_arguments(tc.function.arguments)
            if not isinstance(args, dict):
                continue
            result = {}
            for item in (args.get("results") or []):
                if not isinstance(item, dict):
                    continue
                try:
                    result[int(item.get("index"))] = item
                except (TypeError, ValueError):
                    continue
            return result
        return {}

    def _clean(self, text, origin: str) -> str:
        """校验改写结果，不合格返回空串"""
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text or len(text) > self.MAX_LEN:
            return ""
        if text == str(origin or "").strip():
            return ""
        if any(w in text for w in self.RELATIVE_WORDS):
            return ""
        if any(w in text for w in self.PROMISE_WORDS):
            return ""
        return text

    @staticmethod
    def _norm(text) -> str:
        """归一化文本用于证据比对"""
        return re.sub(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()【】\[\]]+", "", str(text or ""))

    def _grounded(self, quote: str, item: Dict, evidence: List[str], content: str) -> bool:
        """校验引用的证据真实存在且包含动作结果"""
        q = self._norm(quote)
        if len(q) < 2:
            return False
        if any(w in quote for w in self.EVIDENCE_BLOCK):
            return False
        if q in self._norm(item.get("event", "")):
            return False
        if any(q in self._norm(s) for s in evidence):
            return any(m in quote for m in self.COMPLETION_MARKERS)
        if content and q in self._norm(content):
            return any(m in quote for m in self.DIALOG_MARKERS)
        return False

    def judge(self, llm, content: str, data: List[Dict]) -> List[Dict]:
        """判定已完成条目，返回改写提案"""
        items = self.collect(data)
        if not items:
            return []
        history = self._load_history()
        resp = force_tool_call(llm, self._messages(items, content, history, data), self.build_tool(),
                               self.TOOL_NAME, max_attempts=2, temperature=0, max_tokens=4096)
        verdicts = self._parse(resp)
        if not verdicts:
            self.log.error("临时约定清理未返回结论，保持原样")
            return []
        proposals = []
        for index, item in enumerate(items, 1):
            verdict = verdicts.get(index) or {}
            if str(verdict.get("state") or "").strip().lower() != "done":
                continue
            text = self._clean(verdict.get("event"), item.get("event"))
            if not text:
                self.log.warning(f"临时约定改写不合格，跳过: {item.get('id')}")
                continue
            evidence = self._evidence(item, history, data)
            if not self._grounded(str(verdict.get("quote") or ""), item, evidence, content):
                self.log.warning(f"临时约定缺少可核对的完成证据，跳过: {item.get('id')}")
                continue
            proposals.append({"item": item, "event": text})
        return proposals

    def preview(self, llm, content: str, data: List[Dict]) -> List[Dict]:
        """只返回改写提案，不写库"""
        return [{"time": p["item"].get("time", ""), "id": p["item"].get("id", ""),
                 "before": p["item"].get("event", ""), "after": p["event"]}
                for p in self.judge(llm, content, data)]

    def sweep(self, llm, content: str, data: List[Dict]) -> int:
        """判定并改写已完成的约定，返回改写条数"""
        if not self.config.temp_promise_enabled:
            return 0
        proposals = self.judge(llm, content, data)
        if not proposals:
            return 0
        return self.apply(proposals, data)

    def apply(self, proposals: List[Dict], data: List[Dict]) -> int:
        """把改写提案落到数据并保存，返回改写条数"""
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        used_ids = {item.get("id") for item in data if isinstance(item, dict) and item.get("id")}
        changed = 0
        for prop in proposals:
            item, text = prop["item"], prop["event"]
            new_id = self.dedup.make_id({"event": text, "joint": item.get("joint")})
            if new_id != item.get("id") and new_id in used_ids:
                self.log.warning(f"临时约定改写后编号冲突，跳过: {item.get('id')}")
                continue
            used_ids.discard(item.get("id"))
            used_ids.add(new_id)
            item["event"] = text
            item["tags"] = [t for t in (item.get("tags") or []) if t != self.TAG]
            item["id"] = new_id
            item["resolved_at"] = now_iso
            changed += 1
        if changed:
            self.loader.save(data)
            self.log.info(f"临时约定清理 {changed} 条")
        return changed
