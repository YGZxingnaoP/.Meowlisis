# -*- coding: utf-8 -*-
# func/llm_active/origin/origin_core.py
# 创造型主动回复：随机话题/视频筛选摘要，结合长期记忆与用户档案深度思考输出

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
    """创造型主动回复：随机话题/视频筛选摘要，结合长期记忆与用户档案深度思考输出"""

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
        picked = self.random_topic.pick()
        if picked.get("type") == "video":
            self._run_video(picked)
        else:
            self._run_topic(picked)

    # ==================== 话题分支（仅用记忆） ====================
    def _run_topic(self, picked):
        topic = picked.get("topic", "")
        tag = picked.get("tag", "")
        speakers = self._recent_speakers(self.config.origin_speaker_limit)
        if not speakers:
            self.log.info("未找到最近说话人，跳过本次主动回复")
            return

        profile_text = self._build_profiles(speakers)
        summary_text = self._build_summaries(topic, tag, self.config.origin_summary_limit)
        long_text = self.ltmem.load()

        ai_name = AppConfig().ai_name
        guide = f"# 你是{ai_name}，无聊的你正在回忆着过去，思考着什么：\n{long_text}\n{profile_text}\n{summary_text}"

        prompt = self.get_prompt.get_active_prompt(self.config.cold_time)
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": guide},
        ]
        self._stream_generate(messages)

    # ==================== 视频分支（替换记忆） ====================
    def _run_video(self, picked):
        data = picked.get("data") or {}
        path = picked.get("path", "")
        title = str(data.get("title", "") or "").strip()
        length = str(data.get("len", "") or "").strip()
        uploader = str(data.get("uploader", "") or "").strip()
        content = str(data.get("content", "") or "").strip()
        topic = str(data.get("topic", "") or "").strip()
        tags = list(data.get("tags") or [])

        ai_name = AppConfig().ai_name
        guide = (
            f"# 你是{ai_name}，你之前看到了一个视频，想和别人分享：\n"
            f"视频的标题是{title}，有{length}，由{uploader}上传，内容是{content}"
        )

        # system 提示词的话题/tags 筛选用视频的 topic 与 tags
        tags_text = "、".join(tags)
        current_message = " ".join([x for x in (title, tags_text, content) if x])
        prompt = self.get_prompt.get_active_prompt(
            self.config.cold_time,
            current_message=current_message,
            topic_override=topic,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": guide},
        ]
        self._stream_generate(messages)

        # 消费后移动到收藏目录（缓存减 1）
        self._move_collected(path)

    def _stream_generate(self, messages):
        """流式生成并写短期记忆（origin 深度思考输出）"""
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
            # 写入长期记忆与摘要缓存（不写用户档案，不需要 username）
            try:
                from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
                MeowLLMLtMemBridge().record_ltmem_only(AppConfig().ai_name, final_text)
            except Exception:
                self.log.exception("[主动回复-origin] 写入长期记忆失败")
        self.log.info(f"[{traceid}][主动回复-origin]{final_text}")

    def _move_collected(self, path):
        """把已消费的视频 json 移到收藏目录"""
        if not path:
            return
        try:
            from func.llm_active.origin.web_browse.store import AutoBrowseStore
            dest = AutoBrowseStore().move_to_collect(path)
            if dest:
                self.log.info(f"[主动回复-origin] 视频已收藏: {dest}")
        except Exception:
            self.log.exception("移动已消费视频失败")

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
