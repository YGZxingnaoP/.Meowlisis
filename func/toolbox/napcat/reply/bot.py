# -*- coding: utf-8 -*-
# func/toolbox/napcat/reply/bot.py
# 幻梦（群机器人）被动回复（自 func/toolbox/qq_response.py 原样拆出，行为不变）


class BotReplyMixin:
    """幻梦（群机器人）被动回复"""
    # ==================== 幻梦回复评价 ====================
    def _reply_bot_reply(self, parsed: dict):
        """幻梦回复角色：基于图 + 幻梦文字，简短评价/接话，发群一次（10~20 字）"""
        group_id = str(parsed.get("group_id", "") or "")
        group_name = str(parsed.get("group_name", "") or "")
        username = str(parsed.get("username", "") or "")
        self_id = str(parsed.get("self_id", "") or "")
        text = str(parsed.get("text", "") or "").strip()
        raw_message = parsed.get("raw_message") or []

        from func.toolbox.napcat.image.image_search import TBImageSearch
        from func.toolbox.meowvision.config import TBVisionConfig

        # 1. 提取幻梦的图（markdown 图 + image 段图）并落地本地（含压缩/抽帧/大小限制保护）
        images = TBImageSearch.extract_markdown_images(raw_message) + TBImageSearch.extract_images(raw_message)
        image_paths = []
        if images:
            try:
                image_paths = TBImageSearch.prepare_for_vision(images, TBVisionConfig().cache_dir)
            except Exception:
                self.log.exception("幻梦图片落地本地失败")

        reply = ""
        if image_paths:
            # 2. 有图：视觉看图（图 + 幻梦文字），简短评价
            from func.toolbox.napcat.vision_active.vision import TBNapCatVisionActive
            try:
                from func.pipeline.id_signup import IdSignupBridge
                bot_uid = IdSignupBridge().meowid_of_account(
                    "qq", str(parsed.get("user_id", "") or ""), username) or username
            except Exception:
                bot_uid = username
            if text:
                user_message = (
                    f"幻梦回复：{text}\n"
                    f"请结合图片和这段文字，用你的角色口吻给出简短评价，字数控制在10到20字之间。"
                )
            else:
                user_message = "幻梦发来了一张图，请用你的角色口吻给出简短评价，字数严格控制在10到20字之间。"
            try:
                result = TBNapCatVisionActive().process(
                    image_paths, user_message, bot_uid,
                    need_description=False, write_memory=False,
                )
                reply = (result.get("reply") or "").strip()
            except Exception:
                self.log.exception("幻梦图片视觉回复失败")
        else:
            # 3. 无图：基于幻梦文字简短接话
            try:
                from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
                from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
                short_memory = TBGetGroupRecord().fetch(group_id, self_id)
                group_info_text = TBGroupInfo().build_prompt(group_name)
                prompt_text = f"幻梦机器人回复了：{text}\n请用你的角色口吻简短接话或评价，字数严格控制在10到20字之间。"
                reply = self.napcat_group_llm.reply(
                    username, group_id, group_name, prompt_text, short_memory, group_info_text,
                )
            except Exception:
                self.log.exception("幻梦文字回复失败")

        # 4. 发群（字数由提示词约束为 10~20 字，不做截断）
        reply = (reply or "").strip()
        if not reply:
            return
        from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
        for seg in TBNapCatGroupLLM.split_segments(reply):
            self.napcat_core.send_group_text(group_id, seg)
        self.log.info(f"[幻梦评价] 已回复 {group_name}: {reply[:30]}")

    def _is_bot(self, user_id) -> bool:
        """判断发送者是否为已配置的群机器人（如幻梦），机器人消息不写任何记忆文件"""
        try:
            meowid = str(user_id or "")
            for qq in (self.napcat_config.group_bots or {}).values():
                if str(qq) == meowid:
                    return True
        except Exception:
            pass
        return False
