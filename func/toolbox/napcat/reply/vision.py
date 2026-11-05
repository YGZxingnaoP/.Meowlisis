# -*- coding: utf-8 -*-
# func/toolbox/napcat/reply/vision.py
# QQ 群聊看图回复（自 func/toolbox/qq_response.py 原样拆出，行为不变）


class VisionReplyMixin:
    """QQ 群聊看图回复"""
    # ==================== 群聊图片视觉回复 ====================
    def _reply_group_image(self, group_id, group_name, user_id, username, text,
                           images, is_bot, self_id, static_only=False) -> str:
        """群聊图片视觉回复：无文本向上检索 → 落地图片 → 视觉 → 发群"""
        from func.toolbox.napcat.image.image_search import TBImageSearch
        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        # 拉取群聊短期记忆（一次拉取，两处复用：无文本补上下文 + 传给视觉模型）
        group_history = None
        try:
            group_history = TBGetGroupRecord().fetch(group_id, self_id)
        except Exception:
            self.log.exception("群聊图片拉取历史失败")

        # 无文本 → 向上检索最近群历史用户文本作为看图上下文
        if not text.strip():
            text = TBImageSearch.gather_text_context("", group_history or [])

        # 图片落地本地缓存区 + 动图抽帧 + 张数/大小限制
        from func.toolbox.meowvision.config import TBVisionConfig
        cache_dir = TBVisionConfig().cache_dir
        if static_only:
            image_paths = TBImageSearch.prepare_static_only(images, cache_dir)
        else:
            image_paths = TBImageSearch.prepare_for_vision(images, cache_dir)
        if image_paths:
            from func.toolbox.napcat.vision_active.vision import TBNapCatVisionActive
            try:
                from func.pipeline.id_signup import IdSignupBridge
                vision_uid = IdSignupBridge().meowid_of_account("qq", str(user_id or ""), username)
            except Exception:
                self.log.exception("群图片视觉身份解析失败")
                vision_uid = ""
            if not vision_uid:
                self.log.error(f"[视觉] 群图片身份无法识别，跳过看图: {user_id}")
                return ""
            result = TBNapCatVisionActive().process(
                image_paths, text, vision_uid,
                need_description=True, write_memory=not is_bot,
                history_messages=group_history,
            )
            vision_reply = (result.get("reply") or "").strip()
            if vision_reply:
                from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
                for seg in TBNapCatGroupLLM.split_segments(vision_reply):
                    self.napcat_core.send_group_text(group_id, seg)
                self.log.info(f"[视觉] 群图片视觉回复已发群 {group_name}: {vision_reply[:30]}")
            return vision_reply
        return ""

    # ==================== 辅助 ====================
    @staticmethod
    def _extract_emote_text(segments) -> str:
        """从消息段提取动画表情文本（mface 有 summary 名称），静态 face 忽略"""
        buf = ""
        for seg in segments or []:
            if isinstance(seg, dict) and seg.get("type") == "mface":
                summary = str((seg.get("data") or {}).get("summary", "") or "").strip()
                if summary:
                    buf += f"[动画表情：{summary}]"
        return buf.strip()
