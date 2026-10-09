import os
from typing import Dict, List, Tuple

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.AbstractMem.review.config import MeowMemoryReviewConfig
from func.catbrain.AbstractMem.review.review_tool import MeowMemoryReviewTool
from func.catbrain.AbstractMem.review.port.review import MeowMemoryReviewLLM
from func.catbrain.AbstractMem.record.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.port import force_tool_call


class MeowMemoryReview:
    def __init__(self):
        """记忆审查：按规则对候选事件逐条判定，合格保留并归类，不合格丢弃"""
        self.log = DefaultLog().getLogger()
        self.config = MeowMemoryReviewConfig()
        self.tool = MeowMemoryReviewTool()
        self._llm = None

    def _ensure_llm(self):
        """懒加载审查客户端"""
        if self._llm is None:
            self._llm = MeowMemoryReviewLLM()
        return self._llm

    def _load_prompt(self) -> str:
        """读取记忆审查指令文件"""
        path = os.path.join("func", "catbrain", "AbstractMem", "review", "review_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            self.log.exception("读取记忆审查指令失败")
            return "你在审查记忆候选，逐条判断是否可写入长期记忆，必须调用 review_memories 工具输出结论。"

    @staticmethod
    def _character_card() -> str:
        """获取角色卡文本，用于判断内容是否已存在于人设"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_character_prompt() or ""
        except Exception:
            return ""

    def _verdicts(self, llm, content: str, events: List[Dict]) -> Dict:
        """调用审查模型，返回 编号到结论 的映射，未调用工具时返回 None"""
        system_text = self._load_prompt().format(ai_name=AppConfig().ai_name)
        card = self._character_card()
        if card:
            system_text += "\n\n【角色卡（用于判断内容是否已存在）】\n" + card
        lines = [f"{i}. {e.get('event', '')}" for i, e in enumerate(events, 1)]
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": f"原文对话：\n{content}"},
            {"role": "user", "content": "候选记忆：\n" + "\n".join(lines)},
        ]
        resp = force_tool_call(llm, messages, self.tool.build_tools(), self.tool.TOOL_NAME,
                               max_attempts=self.config.max_rounds)
        return self._parse(resp)

    def _parse(self, resp) -> Dict:
        """解析审查工具调用结果，映射为 编号到结论 的字典"""
        if not resp or not resp.choices:
            return None
        for tc in (getattr(resp.choices[0].message, "tool_calls", None) or []):
            if tc.function.name != MeowMemoryReviewTool.TOOL_NAME:
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
        return None

    def review(self, events: List[Dict], content: str) -> Tuple[List[Dict], List[Dict]]:
        """审查候选事件，返回 合格事件(已写归类与置信度) 与 不合格事件"""
        if not events:
            return [], []
        if not self.config.enabled:
            return list(events), []
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("记忆审查 LLM 不可用，跳过审查")
            return list(events), []
        verdicts = self._verdicts(llm, content, events)
        if verdicts is None:
            self.log.error("记忆审查未返回结论，跳过审查")
            return list(events), []
        passed, dropped = [], []
        for i, event in enumerate(events, 1):
            verdict = verdicts.get(i)
            if not verdict or not verdict.get("pass"):
                dropped.append(event)
                continue
            kind = verdict.get("kind")
            accuracy = verdict.get("accuracy")
            if kind not in self.tool.KINDS or accuracy not in self.tool.ACCURACY_VALUES:
                dropped.append(event)
                continue
            event["kind"] = kind
            event["accuracy"] = accuracy
            passed.append(event)
        return passed, dropped
