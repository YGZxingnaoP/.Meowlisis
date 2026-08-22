# -*- coding: utf-8 -*-
# func/llm_active/origin/origin_core.py
# 创造型主动回复：随机话题筛选摘要，结合长期记忆与用户档案深度思考输出

import glob
import json
import os
import uuid

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.llm.output import Output
from func.llm.state import LLmState
from func.pipeline.short_memory import ShortMemory
from func.catbrain.UserMemory.load_usrmem import MeowLoadUserMemory
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory
from func.catbrain.LongTermMem.load_memory import MeowLoadMemory
from func.llm_active.config import AutoActiveConfig
from func.llm_active.get_prompt import AutoGetPrompt
from func.llm_active.origin.random_topic import AutoRandomTopic


class AutoOriginCore:
    """创造型主动回复：随机话题筛选摘要，结合长期记忆与用户档案深度思考输出"""

    def __init__(self, llm):
        self.log = DefaultLog().getLogger()
        self.llm = llm
        self.config = AutoActiveConfig()
        self.get_prompt = AutoGetPrompt()
        self.random_topic = AutoRandomTopic()
        self.usrmem = MeowLoadUserMemory()
        self.abmem = MeowLoadAbstractMemory()
        self.ltmem = MeowLoadMemory()
        self.short_memory = ShortMemory()

    def run(self):
        """执行创造型主动回复"""
        topic, tag = self.random_topic.pick()
        speakers = self._recent_speakers(self.config.origin_speaker_limit)
        if not speakers:
            self.log.info("未找到最近说话人，跳过本次主动回复")
            return

        profile_text = self._build_profiles(speakers)
        summary_text = self._build_summaries(topic, tag, self.config.origin_summary_limit)
        long_text = self.ltmem.load()

        ai_name = AppConfig().ai_name
        guide = f"你是{ai_name}，无聊的你正在回忆着过去，思考着什么：\n{long_text}\n{profile_text}\n{summary_text}"

        prompt = self.get_prompt.get_active_prompt(self.config.cold_time)
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": guide},
        ]

        traceid = str(uuid.uuid4())
        output = Output(self.config, LLmState(), enable_narration=False)
        stream = self.llm.chat_stream(messages, options={"enable_thinking": True})
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                output.process_chunk(delta.content, traceid)

        final_text = output.finalize(traceid)
        if final_text:
            # 仅 AI 输出写入短期记忆，引导词不传递
            self.short_memory.save(
                {"role": "assistant", "content": final_text, "type": "llm_active_response"},
                self._max_rounds(),
            )
        self.log.info(f"[{traceid}][主动回复-origin]{final_text}")

    def _max_rounds(self):
        from func.llm.config import LLMConfig
        return LLMConfig().short_term_rounds

    def _recent_speakers(self, limit):
        """从 .temp/*_record.txt 按修改时间倒序取最近说话人"""
        try:
            files = glob.glob(os.path.join(".temp", "*_record.txt"))
            files.sort(key=os.path.getmtime, reverse=True)
            speakers = []
            for f in files:
                base = os.path.basename(f)
                name = base[:-len("_record.txt")]
                if name:
                    speakers.append(name)
            return speakers[:limit]
        except Exception:
            self.log.exception("读取最近说话人失败")
            return []

    def _build_profiles(self, speakers):
        """按说话人读取用户档案并拼接"""
        parts = []
        for name in speakers:
            data = self.usrmem.load(name)
            if data:
                parts.append(f"【{name}的档案】{json.dumps(data, ensure_ascii=False)}")
        return "\n".join(parts)

    def _build_summaries(self, topic, tag, limit):
        """按随机话题与标签筛选记忆摘要并转 markdown"""
        data = self.abmem.load()
        if not data:
            return ""
        scored = []
        for item in data:
            topic_score = 1 if item.get("topic") == topic else 0
            tag_score = 1 if tag and tag in (item.get("tags") or []) else 0
            importance = float(item.get("importance", 0) or 0)
            scored.append(((topic_score, tag_score, importance), item))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [item for _, item in scored[:limit]]

        ai_name = AppConfig().ai_name
        lines = [f"# {ai_name}的记忆"]
        for item in top:
            meta = f"话题:{item.get('topic', '')}"
            tags = "、".join(item.get("tags") or [])
            if tags:
                meta += f" | 标签:{tags}"
            lines.append(f"- [{meta}] {item.get('text', '')}")
        return "\n".join(lines)
