# -*- coding: utf-8 -*-
"""摘要更新：多事件概括、临时保存、去重比对与写入"""
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
from func.catbrain.AbstractMem.port.deepseek import MeowAbstractDeepSeekLLM
from func.catbrain.AbstractMem.port.aliyun import MeowAbstractAliyunLLM
from func.catbrain.AbstractMem.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.tag_store import MeowTagStore
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory
from func.catbrain.AbstractMem.dedup import MeowDedup
from func.catbrain.AbstractMem.archive import MeowArchive
from func.catbrain.AbstractMem.port import force_tool_call


class MeowUpdateAbstractMemory:
    """摘要更新类：概括为多事件、去重后写入 meow-YYMM.json"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.summary_tool = MeowSummaryTool()
        self.tag_store = MeowTagStore()
        self.llm = None
        self._lock = threading.Lock()
        self._loader = MeowLoadAbstractMemory()
        self._dedup = MeowDedup()
        self._archive = MeowArchive()
        self._last_philosophy_trigger = 0.0

    def _ensure_llm(self):
        """懒加载摘要独立 LLM 客户端"""
        if self.llm is None:
            self.llm = self._create_llm()
        return self.llm

    def _create_llm(self):
        """根据配置创建摘要独立 LLM 客户端"""
        if self.config.abstract_llm_type == "gemini":
            from func.catbrain.AbstractMem.port.gemini import MeowAbstractGeminiLLM
            return MeowAbstractGeminiLLM()
        if self.config.abstract_llm_type == "aliyun":
            return MeowAbstractAliyunLLM()
        return MeowAbstractDeepSeekLLM()

    def _get_character_prompt(self) -> str:
        """延迟获取角色卡+价值观提示词"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_persona_prompt() or ""
        except Exception:
            return ""

    def _extract_joint(self, content: str) -> List[str]:
        """从对话内容中提取参与用户名"""
        ai_name = AppConfig().ai_name or "喵呜"
        names = re.findall(r'\]\[([^\]]+)\]:', content)
        joint = []
        for n in names:
            n = n.strip()
            if n and n != ai_name and n not in joint:
                joint.append(n)
        return joint

    def _build_messages(self, content: str) -> List[Dict]:
        """构建概括消息：摘要指令 + 角色提示词 + tags附件 + 待概括内容"""
        instruction = self._load_instruction().format(ai_name=AppConfig().ai_name)
        system_text = instruction
        character_prompt = self._get_character_prompt()
        if character_prompt:
            system_text += "\n\n【角色提示词】\n" + character_prompt
        tags_attachment = self.summary_tool.build_tags_attachment()
        return [
            {"role": "system", "content": system_text},
            {"role": "user", "content": tags_attachment},
            {"role": "user", "content": f"待概括的对话记录：\n{content}"}
        ]

    def _load_instruction(self) -> str:
        """读取摘要指令提示词文件"""
        path = os.path.join("func", "catbrain", "AbstractMem", "summary_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            self.log.exception("读取摘要指令失败")
            return "请以第一人称客观概括以下对话记忆，每个事件调用一次 save_memory_summary 工具。"

    def _collect_events(self, resp, messages) -> List[Dict]:
        """回填工具消息并解析事件工具调用参数"""
        events = []
        if not resp or not resp.choices:
            return events
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return events
        messages.append({
            "role": "assistant",
            "content": None,
            "reasoning_content": getattr(msg, "reasoning_content", "") or "",
            "tool_calls": [{"id": tc.id, "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                           for tc in msg.tool_calls]
        })
        for tc in msg.tool_calls:
            if tc.function.name == self.summary_tool.TOOL_NAME:
                args = self.summary_tool.parse_arguments(tc.function.arguments)
                if isinstance(args, dict) and args:
                    events.append(args)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": "已保存该事件"})
                else:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": "参数不是合法JSON，请重新调用"})
            else:
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "未知工具，请忽略"})
        return events

    def _extract_events(self, content: str) -> List[Dict]:
        """多轮工具调用概括出多个事件"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            return []
        messages = self._build_messages(content)
        tools = self.summary_tool.build_tools()
        events = []
        resp = force_tool_call(llm, messages, tools, self.summary_tool.TOOL_NAME)
        if not resp or not resp.choices:
            return events
        events.extend(self._collect_events(resp, messages))
        for _ in range(20):
            resp = llm.chat(messages, tools=tools)
            if not resp or not resp.choices:
                break
            if not resp.choices[0].message.tool_calls:
                break
            events.extend(self._collect_events(resp, messages))
        return events

    def _normalize_tags(self, tags) -> List[str]:
        """规范化 tags：去空去重并限制上限"""
        if not isinstance(tags, list):
            return []
        result = []
        for t in tags:
            t = str(t).strip()
            if t and t not in result:
                result.append(t)
            if len(result) >= self.config.summary_tags_limit:
                break
        return result

    def _normalize_topics(self, topics) -> List[str]:
        """规范化 topics：仅保留限定话题"""
        result = []
        for t in (topics or []):
            t = str(t).strip()
            if t in self.summary_tool.TOPICS and t not in result:
                result.append(t)
        return result if result else ["日常"]

    def _normalize_accuracy(self, accuracy) -> int:
        """规范化 accuracy 到 1/3/5 三档"""
        try:
            a = int(accuracy)
        except (TypeError, ValueError):
            return 5
        if a <= 1:
            return 1
        if a <= 3:
            return 3
        return 5

    def _normalize_number(self, value, minimum, maximum) -> float:
        """规范化数值到区间内"""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return float(minimum)
        if v < minimum:
            return float(minimum)
        if v > maximum:
            return float(maximum)
        return v

    def _normalize_joint(self, joint, content) -> List[str]:
        """规范化 joint：清洗后为空则程序化提取"""
        ai_name = AppConfig().ai_name or "喵呜"
        result = []
        for n in (joint or []):
            n = str(n).strip()
            if n and n != ai_name and n not in result:
                result.append(n)
        if not result:
            result = self._extract_joint(content)
        return result

    def _normalize_event(self, event: Dict, content: str) -> Dict:
        """规范化单个事件的字段"""
        event["event"] = self._clean_text(event.get("event", ""))
        event["tags"] = self._normalize_tags(event.get("tags"))
        event["topics"] = self._normalize_topics(event.get("topics"))
        event["joint"] = self._normalize_joint(event.get("joint"), content)
        event["importance"] = self._normalize_number(event.get("importance"), 0, 10)
        event["accuracy"] = self._normalize_accuracy(event.get("accuracy"))
        return event

    def _save_temp(self, events: List[Dict]):
        """把待去重事件写入 .temp/abmem_temp.json"""
        os.makedirs(".temp", exist_ok=True)
        path = os.path.join(".temp", "abmem_temp.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(events, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入临时事件失败")

    def _clear_temp(self):
        """清理临时事件文件"""
        path = os.path.join(".temp", "abmem_temp.json")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            self.log.exception("清理临时事件失败")

    def _trigger_values_update(self):
        """哲思话题触发价值观更新"""
        cooldown = self.config.values_philosophy_cooldown_minutes * 60
        now = time.time()
        if now - self._last_philosophy_trigger < cooldown:
            self.log.info("哲思触发价值观更新处于冷却期，跳过")
            return
        self._last_philosophy_trigger = now
        try:
            from func.pipeline.llm_values import MeowLLMValuesBridge
            MeowLLMValuesBridge().trigger_update("哲思话题触发")
        except Exception:
            self.log.exception("触发价值观更新失败")

    def _clean_text(self, text: str) -> str:
        """清洗事件文本前缀"""
        if not text:
            return ""
        ai = AppConfig().ai_name or "喵呜"
        patterns = [
            r'^(好的|好|嗯+|哈哈+|嘿嘿+)[，。！？、,.!?\s]*',
            rf'^(我是|我是{re.escape(ai)}|{re.escape(ai)})[，。！？、,.!?\s]*',
        ]
        prev = None
        while prev != text and text:
            prev = text
            for p in patterns:
                text = re.sub(p, '', text, count=1)
        return text.strip()

    def summarize(self, content: str, rounds: int) -> bool:
        """触发概括：多事件提取、去重、写入、归档扫描"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("摘要 LLM 不可用，跳过概括")
            return False
        events = self._extract_events(content)
        if not events:
            self.log.info("摘要未提取到事件")
            return False
        now_str = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
        for event in events:
            event["time"] = now_str
            self._normalize_event(event, content)
        self._save_temp(events)
        data = self._loader.load()
        add_events = self._dedup.process(events, data)
        data.extend(add_events)
        for event in events:
            self.tag_store.append(event.get("tags", []))
        self._loader.save(data)
        self._clear_temp()
        for event in events:
            if "哲思" in (event.get("topics") or []):
                self._trigger_values_update()
                break
        try:
            self._archive.scan()
        except Exception:
            self.log.exception("归档扫描失败")
        return True
