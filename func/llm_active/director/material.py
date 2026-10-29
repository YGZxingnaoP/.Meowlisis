# -*- coding: utf-8 -*-
# func/llm_active/director/material.py
# 导演素材：沿用原主动回复的概率池（话题 / B站缓存视频），并组装成规划器可读的说明

from func.log.default_log import DefaultLog
from func.llm_active.config import AutoActiveConfig
from func.llm_active.origin.origin_core import AutoOriginCore
from func.llm_active.origin.random_topic import AutoRandomTopic


class DirectorMaterial:
    """素材选择：概率池与「视频由头」的写法完全沿用原 origin 模块

    - pick()：抽一项（topic / video），视频是概率出现的，和以前一致；
    - describe()：转成规划器提示词里的【素材】段；
    - consume()：计划真的开始后才把视频移到收藏（规划失败不吞素材）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoActiveConfig()
        self.random_topic = AutoRandomTopic()
        # 只借 origin 的「最近说话人/档案/摘要」拼装能力，不跑它的生成
        self.origin = AutoOriginCore(None)

    def pick(self):
        """从统一概率池抽一项（与 origin 完全一致）"""
        try:
            return self.random_topic.pick()
        except Exception:
            self.log.exception("[导演] 抽取素材失败")
            return {"type": "topic", "topic": "日常", "tag": ""}

    def describe(self, picked) -> str:
        """把素材渲染为规划器提示词里的【素材】段"""
        picked = picked or {}
        if picked.get("type") == "video":
            return self._describe_video(picked)
        return self._describe_topic(picked)

    def consume(self, picked) -> str:
        """素材被真正用于开场后调用：视频移到收藏目录，返回新路径（失败返回空串）"""
        if not picked or picked.get("type") != "video":
            return ""
        path = str(picked.get("path") or "")
        if not path:
            return ""
        try:
            from func.llm_active.origin.web_browse.store import AutoBrowseStore
            dest = AutoBrowseStore().move_to_collect(path)
            if dest:
                self.log.info(f"[导演] 视频已收藏: {dest}")
            return str(dest or "")
        except Exception:
            self.log.exception("[导演] 移动已消费视频失败")
            return ""

    # ==================== 内部 ====================
    @staticmethod
    def _describe_video(picked) -> str:
        data = picked.get("data") or {}
        title = str(data.get("title", "") or "").strip()
        length = str(data.get("len", "") or "").strip()
        uploader = str(data.get("uploader", "") or "").strip()
        content = str(data.get("content", "") or "").strip()
        topic = str(data.get("topic", "") or "").strip()
        tags = "、".join(str(t) for t in (data.get("tags") or []) if str(t).strip())
        lines = ["【素材·视频】你脑海里刚看过的一个视频"]
        if title:
            lines.append(f"标题：{title}")
        if length:
            lines.append(f"时长：{length}")
        if uploader:
            lines.append(f"UP主：{uploader}")
        if content:
            lines.append(f"内容：{content}")
        if topic:
            lines.append(f"话题：{topic}")
        if tags:
            lines.append(f"标签：{tags}")
        lines.append("这个视频是你开口的由头，不是必须交代的任务："
                     "不要复述视频信息，不要出现「好的」「我来分享」这类话；"
                     "你没有在跟别人分享视频，而是在分享自己的感想、自己关注的重点。")
        return "\n".join(lines)

    def _describe_topic(self, picked) -> str:
        topic = str(picked.get("topic", "") or "").strip() or "日常"
        tag = str(picked.get("tag", "") or "").strip()
        parts = [f"【素材·回忆】话题：{topic}" + (f"（标签：{tag}）" if tag else "")]
        try:
            speakers = self.origin._recent_speakers(self.config.origin_speaker_limit)
            profiles = self.origin._build_profiles(speakers)
            summaries = self.origin._build_summaries(
                topic, tag, self.config.origin_summary_limit)
            if profiles:
                parts.append(profiles)
            if summaries:
                parts.append(summaries)
        except Exception:
            self.log.exception("[导演] 组装回忆素材失败")
        parts.append("这些只是你可以拿来当由头的旧事，不是任务；用不上就自己起个话头。")
        return "\n".join(parts)
