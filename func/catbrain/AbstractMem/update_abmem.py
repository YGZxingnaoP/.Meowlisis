# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/update_abmem.py
# 记忆摘要更新：调用独立端口概括并写入 character/abstract_memory/meow.json

import os
import re
import json
import math
import time
import datetime
import threading
from typing import List, Dict, Optional

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.port.deepseek import MeowAbstractDeepSeekLLM
from func.catbrain.AbstractMem.port.aliyun import MeowAbstractAliyunLLM
from func.catbrain.AbstractMem.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.tag_store import MeowTagStore
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory


class MeowUpdateAbstractMemory:
    """摘要更新类：构建概括提示词、调用独立 LLM、清洗并写入 meow.json"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.summary_tool = MeowSummaryTool()
        self.tag_store = MeowTagStore()
        self.llm = None
        self.meow_path = os.path.join("character", "abstract_memory", "meow.json")
        self._lock = threading.Lock()
        self._loader = MeowLoadAbstractMemory()
        # 哲思话题触发价值观更新的冷却控制
        self._last_philosophy_trigger = 0.0

    def _ensure_llm(self):
        """懒加载摘要独立 LLM 客户端"""
        if self.llm is None:
            self.llm = self._create_llm()
        return self.llm

    def _create_llm(self):
        """根据配置创建摘要独立 LLM 客户端"""
        if self.config.abstract_llm_type == "aliyun":
            return MeowAbstractAliyunLLM()
        return MeowAbstractDeepSeekLLM()

    def _word_limit(self, rounds: int) -> int:
        """计算概括字数：轮数×10 向上取整到整百，封顶 10000"""
        raw = rounds * 10
        if raw >= 10000:
            return 10000
        return math.ceil(raw / 100.0) * 100

    def _get_character_prompt(self) -> str:
        """延迟获取角色卡+价值观提示词（方法内导入，避免模块导入期循环依赖）"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_persona_prompt() or ""
        except Exception:
            return ""

    def _extract_joint(self, content: str) -> List[str]:
        """从对话内容中提取参与用户名（排除 AI 自己，按出现顺序去重）"""
        ai_name = AppConfig().ai_name or "喵呜"
        names = re.findall(r'\]\[([^\]]+)\]:', content)
        joint = []
        for n in names:
            n = n.strip()
            if n and n != ai_name and n not in joint:
                joint.append(n)
        return joint

    def _build_messages(self, content: str, rounds: int) -> List[Dict]:
        """构建概括消息：摘要指令(含字数) + 角色提示词 + tags附件 + 待概括内容"""
        word_limit = self._word_limit(rounds)
        instruction = self._load_instruction().format(
            ai_name=AppConfig().ai_name, word_limit=word_limit)
        system_text = instruction
        character_prompt = self._get_character_prompt()
        if character_prompt:
            system_text += "\n\n【角色提示词】\n" + character_prompt
        # tags 附件以独立 user 消息注入，让 AI 优先选择已有 tag
        tags_attachment = self.summary_tool.build_tags_attachment()
        return [
            {"role": "system", "content": system_text},
            {"role": "user", "content": tags_attachment},
            {"role": "user", "content": f"待概括的对话记录：\n{content}"}
        ]

    def _load_instruction(self) -> str:
        """读取摘要指令提示词文件（缺失时使用兜底指令）"""
        path = os.path.join("func", "catbrain", "AbstractMem", "summary_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            self.log.exception("读取摘要指令失败")
            return "请以第一人称客观概括以下对话记忆，控制在{word_limit}字左右。"

    def summarize(self, content: str, rounds: int) -> bool:
        """触发概括：调用 LLM 工具、清洗文本并写入 meow.json，返回是否成功"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("摘要 LLM 不可用，跳过概括")
            return False
        messages = self._build_messages(content, rounds)
        tools = self.summary_tool.build_tools()
        tool_choice = self.summary_tool.force_tool_choice()
        resp = llm.chat(messages, tools=tools, tool_choice=tool_choice)
        if not resp or not resp.choices:
            self.log.error("摘要 LLM 无响应")
            return False
        result = self._parse_tool_calls(resp)
        if not result:
            return False
        result["text"] = self._clean_text(result.get("text", ""))
        # tags 规范化：去空、去重、上限5个；新 tag 追加到 tags.json
        tags = self._normalize_tags(result.get("tags"))
        result["tags"] = tags
        self.tag_store.append(tags)
        # joint 从对话内容程序化提取（不由 AI 提取）
        result["joint"] = self._extract_joint(content)
        # topic 规范化为单个字符串
        result["topic"] = self._normalize_topic(result.get("topic"))
        self._append(result)
        # 话题为哲思时立即触发价值观更新（带冷却）
        if result["topic"] == "哲思":
            self._trigger_values_update()
        return True

    def _normalize_tags(self, tags) -> List[str]:
        """规范化 tags：转字符串、去空去重、上限5个"""
        if not isinstance(tags, list):
            return []
        result = []
        for t in tags:
            t = str(t).strip()
            if t and t not in result:
                result.append(t)
            if len(result) >= 5:
                break
        return result

    def _normalize_topic(self, topic) -> str:
        """规范化 topic：保证为枚举内单个字符串（列表取第一个有效值）"""
        if isinstance(topic, list):
            for t in topic:
                if str(t).strip() in self.summary_tool.TOPICS:
                    return str(t).strip()
            return str(topic[0]).strip() if topic else "日常"
        t = str(topic or "").strip()
        return t if t in self.summary_tool.TOPICS else "日常"

    def _trigger_values_update(self):
        """哲思话题触发价值观更新（30分钟冷却，异步执行）"""
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
        """清洗摘要文本：去除开头多余的口头语、自称等前缀"""
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

    def _parse_tool_calls(self, resp) -> Optional[Dict]:
        """解析 LLM 返回的摘要工具调用参数"""
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == self.summary_tool.TOOL_NAME:
                    return json.loads(tc.function.arguments)
        except Exception:
            self.log.exception("解析摘要工具调用失败")
        return None

    def _append(self, result: Dict):
        """将摘要结果追加写入 meow.json（加锁防止并发写丢数据）"""
        os.makedirs(os.path.dirname(self.meow_path), exist_ok=True)
        with self._lock:
            data = self._loader.load()
            record = {
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **result
            }
            data.append(record)
            try:
                with open(self.meow_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                self.log.exception("写入 meow.json 失败")
