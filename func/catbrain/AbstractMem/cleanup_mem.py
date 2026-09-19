# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/cleanup_mem.py
# 记忆精简：结构修复 -> 精确去重 -> 低价值过滤 -> 标签清洗 -> (可选)LLM语义归纳 -> 写回
# 默认 dry-run（只预览不写入）；--apply 才落盘，写入前整体备份到 _backup/cleanup_<时间戳>/
#
# 用法：
#   runtime\python.exe func\catbrain\AbstractMem\cleanup_mem.py                        # 预览
#   runtime\python.exe func\catbrain\AbstractMem\cleanup_mem.py --apply --no-llm       # 规则清理（默认不做重要度过滤）
#   runtime\python.exe func\catbrain\AbstractMem\cleanup_mem.py --apply --llm          # 规则+LLM语义归纳
#   runtime\python.exe func\catbrain\AbstractMem\cleanup_mem.py --apply --min-importance=5   # 可选：开启重要度过滤

import os
import re
import sys
import json
import shutil
import datetime
import argparse
import collections

# 运行时工作目录为应用根目录（func 的上一级），脚本可能被从任意位置调用，这里强制对齐
_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)
os.chdir(_BASE)

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory
from func.catbrain.AbstractMem.record.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.process.dedup import MeowDedup
from func.catbrain.AbstractMem.process.tag_store import MeowTagStore

# 归一化时剔除的空白与标点（与 dedup.py 保持一致）
PUNCT_PATTERN = r"[\s。，！？、,.!?;；:：~～·…—\-—_\"'“”‘’（）()【】\[\]]+"

# 清理时视为"泛化"的标签（仅清理脚本内部使用，不影响在线去重逻辑）
GENERIC_TAGS = {"闲聊", "日常", "情感", "爱好", "哲思", "社交", "直播互动", "视频分享", "图片分享"}


class MeowMemorySlimmer:
    """记忆精简器：分步清理现有 meow-*.json"""

    def __init__(self, min_importance=0, use_llm=True, apply=False,
                 llm_min_group=3, llm_max_groups=25):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.loader = MeowLoadAbstractMemory()
        self.summary_tool = MeowSummaryTool()
        self.dedup = MeowDedup()
        self.tag_store = MeowTagStore()
        self.generic = set(GENERIC_TAGS) | set(self.summary_tool.TOPICS)
        self.meow_dir = os.path.join("character", "abstract_memory")
        self.tags_path = os.path.join(self.meow_dir, "tags", "tags.json")
        self.backup_dir = os.path.join(self.meow_dir, "_backup")
        self.min_importance = float(min_importance or 0)
        self.use_llm = bool(use_llm)
        self.apply = bool(apply)
        self.llm_min_group = int(llm_min_group or 3)
        self.llm_max_groups = int(llm_max_groups or 25)
        self._llm = None
        self.stats = collections.OrderedDict()
        self._discarded = []

    # ---------------- 基础工具 ----------------
    @staticmethod
    def _norm(text):
        return re.sub(PUNCT_PATTERN, "", str(text or ""))

    @staticmethod
    def _num(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _merge_list(a, b):
        result = list(a or [])
        for v in (b or []):
            v = str(v).strip()
            if v and v not in result:
                result.append(v)
        return result

    def _merge_into(self, base, item):
        """把 item 合并进 base（保留较早 time、合并列表、取较大数值/证据）"""
        if str(item.get("time") or "") and (
                not base.get("time") or str(item.get("time")) < str(base.get("time"))):
            base["time"] = item.get("time")
        base["tags"] = self._merge_list(base.get("tags"), item.get("tags"))
        base["topics"] = self._merge_list(base.get("topics"), item.get("topics"))
        base["joint"] = self._merge_list(base.get("joint"), item.get("joint"))
        base["accuracy"] = int(max(self._num(base.get("accuracy")), self._num(item.get("accuracy"))))
        base["importance"] = max(self._num(base.get("importance")), self._num(item.get("importance")))
        be, ie = base.setdefault("evidence", {}), item.get("evidence") or {}
        for key in ("reinforcement", "disputation"):
            be[key] = max(self._num(be.get(key)), self._num(ie.get(key)))
        for key in ("rein_last_signal_at", "disp_last_signal_at", "sub_zero_last_increment_date"):
            be.setdefault(key, None)
            if not be.get(key):
                be[key] = ie.get(key)
        be["sub_zero_days"] = int(max(self._num(be.get("sub_zero_days")), self._num(ie.get("sub_zero_days"))))

    def _primary_tag(self, item):
        """首个"具体标签"（忽略泛化标签与话题）"""
        for t in (item.get("tags") or []):
            t = str(t).strip()
            if t and t not in self.generic:
                return t
        return None

    # ---------------- 各阶段 ----------------
    def load(self):
        data = self.loader.load()
        self.stats["载入条数"] = len(data)
        return data

    def step_structure(self, data):
        """结构修复：剔除空 event、规范字段、补齐 evidence、封顶证据、补 id"""
        out = []
        dropped = 0
        saturation = self._num(self.config.rank_evidence_saturation) or 5.0
        for item in data:
            if not isinstance(item, dict):
                continue
            event = str(item.get("event") or "").strip()
            if not event:
                dropped += 1
                continue
            item["event"] = event
            try:
                acc = int(item.get("accuracy", 5) or 5)
            except (TypeError, ValueError):
                acc = 5
            item["accuracy"] = 1 if acc <= 1 else (3 if acc <= 3 else 5)
            item["importance"] = min(10.0, max(0.0, self._num(item.get("importance"))))
            tags = []
            for t in (item.get("tags") or []):
                t = str(t).strip()
                if t and t not in tags:
                    tags.append(t)
            item["tags"] = tags[: self.config.summary_tags_limit or 3]
            topics = [str(t).strip() for t in (item.get("topics") or [])
                      if str(t).strip() in self.summary_tool.TOPICS]
            item["topics"] = topics or ["日常"]
            joint = []
            for j in (item.get("joint") or []):
                j = str(j).strip()
                if j and j not in joint:
                    joint.append(j)
            item["joint"] = joint
            ev = item.get("evidence")
            if not isinstance(ev, dict):
                ev = {}
            ev.setdefault("reinforcement", 0.0)
            ev.setdefault("disputation", 0.0)
            ev.setdefault("rein_last_signal_at", None)
            ev.setdefault("disp_last_signal_at", None)
            ev.setdefault("sub_zero_days", 0)
            ev.setdefault("sub_zero_last_increment_date", None)
            ev["reinforcement"] = min(self._num(ev.get("reinforcement")), saturation)
            item["evidence"] = ev
            item["id"] = item.get("id") or self.dedup.make_id(item)
            item.setdefault("time", "")
            out.append(item)
        self.stats["丢弃空条目"] = dropped
        return out

    def step_exact(self, data):
        """精确去重：先按 id 合并，再按归一化文本合并"""
        merged = 0
        by_id, order = {}, []
        for item in data:
            key = item.get("id") or self._norm(item.get("event"))
            if key in by_id:
                self._merge_into(by_id[key], item)
                merged += 1
            else:
                by_id[key] = item
                order.append(item)
        by_text, result = {}, []
        for item in order:
            key = self._norm(item.get("event"))
            if key and key in by_text:
                self._merge_into(by_text[key], item)
                merged += 1
            else:
                if key:
                    by_text[key] = item
                result.append(item)
        self.stats["精确合并"] = merged
        return result

    def _protected(self, item):
        """低价值过滤的保护规则：高重要度 / 被强化过 / 高准确度且较重要 均保留"""
        if self._num(item.get("importance")) >= 8:
            return True
        if self._num((item.get("evidence") or {}).get("reinforcement")) > 0:
            return True
        if int(self._num(item.get("accuracy"))) >= 5 and self._num(item.get("importance")) >= 6:
            return True
        return False

    def step_importance(self, data):
        """低价值过滤（受保护条目除外）"""
        kept, discarded = [], []
        for item in data:
            if self._num(item.get("importance")) < self.min_importance and not self._protected(item):
                discarded.append(item)
            else:
                kept.append(item)
        self.stats["低价值删除"] = len(discarded)
        self._discarded = discarded
        return kept

    def step_tags(self, data):
        """标签清洗：有具体标签时去掉泛化标签；回收再也不被引用的孤儿 tag"""
        referenced = set()
        for item in data:
            tags = item.get("tags") or []
            specific = [t for t in tags if t not in self.generic]
            if specific:
                item["tags"] = specific
            referenced.update(item.get("tags") or [])
        old_tags = self.tag_store.load()
        kept_tags = [t for t in old_tags if t in referenced]
        self.stats["孤儿tag删除"] = len(old_tags) - len(kept_tags)
        return data, kept_tags

    # ---------------- LLM 语义归纳 ----------------
    def _ensure_llm(self):
        if self._llm is None:
            llm_type = self.config.abstract_llm_type
            if llm_type == "gemini":
                from func.catbrain.AbstractMem.port.gemini import MeowAbstractGeminiLLM
                self._llm = MeowAbstractGeminiLLM()
            elif llm_type == "aliyun":
                from func.catbrain.AbstractMem.port.aliyun import MeowAbstractAliyunLLM
                self._llm = MeowAbstractAliyunLLM()
            else:
                from func.catbrain.AbstractMem.port.deepseek import MeowAbstractDeepSeekLLM
                self._llm = MeowAbstractDeepSeekLLM()
        return self._llm

    def _llm_merge_group(self, tag, items):
        """让 LLM 把一组同主题条目中的重复/同义项合并，返回事件列表；失败返回 None

        说明：清理属于离线批处理，这里直接调用底层 client（不开启"思考"、单次调用），
        以显著降低单次耗时；与在线摘要链路的思考模式互不影响。
        """
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            return None
        lines = "\n".join(f"{i + 1}. {x.get('event', '')}" for i, x in enumerate(items))
        messages = [
            {"role": "system", "content": (
                "你在精简长期记忆。下面是一组主题相近的记忆条目。"
                "请把其中【描述同一件事】的重复或同义条目合并成一条，"
                "但必须保留所有彼此不同的事实，不要新增原文没有的信息，也不要丢掉不同的事实。"
                "每条事件都调用一次 save_memory_summary 工具输出，可在同一次回复里多次调用。"
                "若这些条目本来就各不相同，就原样各输出一条。")},
            {"role": "user", "content": f"主题标签：{tag}\n条目：\n{lines}"}
        ]
        tools = self.summary_tool.build_tools()
        try:
            resp = llm.client.chat.completions.create(
                model=llm.model,
                messages=messages,
                tools=tools,
                tool_choice={"type": "function",
                             "function": {"name": self.summary_tool.TOOL_NAME}},
                max_tokens=llm.max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception:
            self.log.exception(f"LLM 归纳调用失败，跳过主题 {tag}")
            return None
        events = []
        if resp and resp.choices:
            for tc in (resp.choices[0].message.tool_calls or []):
                if tc.function.name != self.summary_tool.TOOL_NAME:
                    continue
                args = self.summary_tool.parse_arguments(tc.function.arguments)
                if isinstance(args, dict) and args:
                    events.append(args)
        return events or None

    def _normalize_merged(self, raw, items):
        """把 LLM 合并结果规范成条目，并继承组内 time/joint/evidence"""
        event = str(raw.get("event") or "").strip()
        if not event:
            return None
        acc = self._num(raw.get("accuracy"))
        acc = 1 if acc <= 1 else (3 if acc <= 3 else 5)
        tags = []
        for t in (raw.get("tags") or []):
            t = str(t).strip()
            if t and t not in tags:
                tags.append(t)
        topics = [str(t).strip() for t in (raw.get("topics") or [])
                  if str(t).strip() in self.summary_tool.TOPICS]
        joint = []
        for j in (raw.get("joint") or []):
            j = str(j).strip()
            if j and j not in joint:
                joint.append(j)
        if not joint:
            for x in items:
                joint = self._merge_list(joint, x.get("joint"))
        item = {
            "event": event,
            "accuracy": acc,
            "importance": min(10.0, max(0.0, self._num(raw.get("importance")))),
            "tags": tags[: self.config.summary_tags_limit or 3],
            "topics": topics or ["日常"],
            "joint": joint,
            "time": min((str(x.get("time") or "") for x in items), default=""),
            "evidence": {"reinforcement": 0.0, "disputation": 0.0, "rein_last_signal_at": None,
                         "disp_last_signal_at": None, "sub_zero_days": 0,
                         "sub_zero_last_increment_date": None},
        }
        for x in items:
            self._merge_into(item, x)
        item["id"] = self.dedup.make_id(item)
        return item

    def step_llm(self, data):
        """按具体标签分组做语义归纳（只处理较大的组，按组大小从大到小、限组数）"""
        if not self.use_llm:
            return data
        groups = collections.defaultdict(list)
        for item in data:
            tag = self._primary_tag(item)
            if tag:
                groups[tag].append(item)
        candidates = sorted(
            ((tag, items) for tag, items in groups.items()
             if self.llm_min_group <= len(items) <= 40),
            key=lambda kv: len(kv[1]), reverse=True)[: self.llm_max_groups]
        handled, merged_out = set(), []
        merged_count = 0
        for tag, items in candidates:
            try:
                raw_events = self._llm_merge_group(tag, items)
            except Exception:
                self.log.exception(f"LLM 归纳失败，跳过主题 {tag}")
                continue
            if not raw_events:
                continue
            normalized = [x for x in (self._normalize_merged(r, items) for r in raw_events) if x]
            if not normalized or len(normalized) >= len(items):
                continue
            merged_out.extend(normalized)
            handled.update(id(x) for x in items)
            merged_count += len(items) - len(normalized)
        if not merged_out:
            self.stats["LLM语义合并"] = 0
            return data
        result = [it for it in data if id(it) not in handled] + merged_out
        self.stats["LLM语义合并"] = merged_count
        return result

    # ---------------- 备份与写回 ----------------
    def _month_files(self):
        files = []
        if os.path.isdir(self.meow_dir):
            for name in os.listdir(self.meow_dir):
                if name.startswith("meow-") and name.endswith(".json"):
                    files.append(os.path.join(self.meow_dir, name))
        return files

    def _backup(self):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(self.backup_dir, f"cleanup_{stamp}")
        os.makedirs(dest, exist_ok=True)
        for path in self._month_files() + [os.path.join(self.meow_dir, "wrong_mem.json"), self.tags_path]:
            if os.path.exists(path):
                shutil.copy2(path, os.path.join(dest, os.path.basename(path)))
        return dest

    def _write(self, data, kept_tags):
        backup = self._backup()
        with open(os.path.join(backup, "discarded.json"), "w", encoding="utf-8") as f:
            json.dump(self._discarded, f, ensure_ascii=False, indent=2)
        for path in self._month_files():
            try:
                os.remove(path)
            except OSError:
                self.log.exception(f"删除旧摘要文件失败: {path}")
        data.sort(key=lambda x: str(x.get("time") or ""))
        self.loader.save(data)
        os.makedirs(os.path.dirname(self.tags_path), exist_ok=True)
        with open(self.tags_path, "w", encoding="utf-8") as f:
            json.dump(kept_tags, f, ensure_ascii=False, indent=2)
        return backup

    def run(self):
        data = self.load()
        before = len(data)
        data = self.step_structure(data)
        data = self.step_exact(data)
        data = self.step_importance(data)
        data, kept_tags = self.step_tags(data)
        data = self.step_llm(data)
        after = len(data)

        report = collections.OrderedDict()
        report["模式"] = "应用(apply)" if self.apply else "预览(dry-run)"
        report["重要度阈值"] = self.min_importance
        report["启用LLM归纳"] = self.use_llm
        report.update(self.stats)
        report["清理前条数"] = before
        report["清理后条数"] = after
        report["净减少"] = before - after
        if before:
            report["减少比例%"] = round(100.0 * (before - after) / before, 1)

        if self.apply:
            report["备份目录"] = self._write(data, kept_tags)
            os.makedirs(".temp", exist_ok=True)
            with open(os.path.join(".temp", "cleanup_report.json"), "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        return report


def main():
    parser = argparse.ArgumentParser(description="记忆精简脚本")
    parser.add_argument("--apply", action="store_true", help="真正写入（默认仅预览）")
    parser.add_argument("--min-importance", type=float, default=0,
                        help="低价值过滤阈值（0 表示不过滤，默认 0）")
    parser.add_argument("--min-group", type=int, default=3, help="LLM归纳时主题组的最小条目数")
    parser.add_argument("--max-groups", type=int, default=25, help="LLM归纳最多处理的主题组数")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--llm", action="store_true", help="启用 LLM 语义归纳")
    group.add_argument("--no-llm", action="store_true", help="禁用 LLM 语义归纳")
    args = parser.parse_args()

    use_llm = args.llm or not args.no_llm  # 默认启用，--no-llm 关闭
    slimmer = MeowMemorySlimmer(min_importance=args.min_importance, use_llm=use_llm,
                                apply=args.apply, llm_min_group=args.min_group,
                                llm_max_groups=args.max_groups)
    report = slimmer.run()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
