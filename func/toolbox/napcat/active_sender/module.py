# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/module.py
# NapCat 主动发送模块：父级 QQ 动作入口（napcat_send）
#
# 分层：父级只看这一个入口；查群名、查好友、查 @ 成员全部在链路内部由
# subtools.py（内部子工具）完成，不注册到父级。解析不出来或有歧义时
# 不猜、不瞎发，直接发起 excuse 向用户追问。

import re
from typing import Dict, List, Optional, Tuple

from func.log.default_log import DefaultLog


class TBNapcatActiveModule:
    """NapCat 主动发送模块入口：父级只暴露 napcat_send。

    执行顺序：
    1) 内部子工具解析目标（群名→群号、昵称→QQ号、@名字→QQ号）→ 直发；
       解析不出来 / 歧义 → excuse 追问，补一次再解析，仍不行就明确返回未发送；
    2) 只有意图、没给内容 → 同样按不确定处理：让角色问一句要发什么，拿到后再发。
    """

    TOOL_NAME = "napcat_send"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._meowid = ""

    def set_meowid(self, meowid: str):
        """注入当前用户（供 excuse 询问时使用）"""
        self._meowid = meowid or ""

    # ==================== 父级 schema ====================
    def build_tools(self) -> List[Dict]:
        """父级唯一入口 schema：目标与内容都直传，查找在链路内部完成"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "通过 QQ 主动给好友或群发送消息、链接、图片、文件，也可在群里 @ 某个成员。"
                    "发给谁直接写群名、群号、好友昵称或 QQ 号（要 @ 谁就把名字填进 mention），"
                    "系统会在内部解析目标，不需要事先查好友列表或群列表。"
                    "拿不准发给谁或发什么时，把 need_clarify 设为 true 并给出 clarify_question。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_type": {
                            "type": "string",
                            "enum": ["friend", "group"],
                            "description": "发送目标类型：friend 好友 / group 群聊",
                        },
                        "target": {
                            "type": "string",
                            "description": "发送目标：群名、群号、好友昵称、备注或 QQ 号",
                        },
                        "mention": {
                            "type": "string",
                            "description": "群聊里要 @ 的成员：群名片、昵称或 QQ 号，可空",
                        },
                        "content_type": {
                            "type": "string",
                            "enum": ["text", "link", "file", "image"],
                            "description": "要发送的内容类型",
                        },
                        "text": {"type": "string", "description": "content_type=text 时的正文"},
                        "url": {"type": "string", "description": "content_type=link 时的链接"},
                        "file_path": {
                            "type": "string",
                            "description": "content_type=file/image 时的本地文件或图片路径",
                        },
                        "request": {
                            "type": "string",
                            "description": "发送需求描述（可选）：给小王发一句生日快乐 / 在某个群发活动通知",
                        },
                        "need_clarify": {
                            "type": "boolean",
                            "description": "目标或内容不确定时置 true，由系统向用户追问",
                        },
                        "clarify_question": {
                            "type": "string",
                            "description": "need_clarify=true 时要问用户的问题",
                        },
                    },
                    "required": ["target_type"],
                },
            },
        }]

    # ==================== 父级分发 ====================
    def dispatch(self, name: str, arguments: Dict) -> str:
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        args = arguments or {}
        # 规则硬触发只给 request、不带 target_type：留空表示群/好友都查，解析出结果再定
        raw_type = str(args.get("target_type") or "").strip()
        target_type = raw_type if raw_type in ("friend", "group") else ""
        target = str(args.get("target") or "").strip()
        mention = str(args.get("mention") or args.get("at_name") or "").strip()
        content_type = str(args.get("content_type") or "")
        text = str(args.get("text") or "")
        url = str(args.get("url") or "")
        file_path = str(args.get("file_path") or "")
        request = str(args.get("request") or "")

        # 上层 AI 已判定信息不足 → 先向用户追问，补齐后再执行
        if bool(args.get("need_clarify")):
            question = str(args.get("clarify_question") or
                           "你想把这条消息发给谁？发什么内容呢？")
            answer = self._ask(question)
            if not answer and not target:
                return "未发送：没有拿到发送目标"
            if answer and not target:
                target = answer

        from func.toolbox.napcat.active_sender import subtools
        from func.toolbox.napcat.active_sender.sender import TBSender
        err = TBSender().check_active_send()
        if err:
            return err

        direct = subtools.direct_content(content_type, text, url, file_path)
        if not (direct.get("text") or direct.get("url") or direct.get("file_path")):
            # 只说了「发个消息」没给内容 → 先由角色自己拟稿；拟不出来才追问
            drafted = self._draft(request, target_type, target, mention) if request else ""
            if drafted:
                self.log.info(f"[napcat_send] 角色拟稿: {drafted[:40]}")
                direct = subtools.direct_content("text", drafted, "", "")
            else:
                hint = f"（{request}）" if request else ""
                answer = self._ask(f"这条消息要发什么内容呀{hint}？给我一句话就行。")
                if not answer:
                    return "未发送：没有拿到要发送的内容"
                direct = subtools.direct_content("text", answer, "", "")

        resolved, why, ask, candidates = self._resolve(target_type, target, mention)
        if resolved is None:
            question = self._clarify_question(why, ask, target_type, candidates)
            answer = self._ask(question)
            if answer:
                if ask == "mention":
                    mention = answer
                else:
                    target = answer
                resolved, why, _ask, _cand = self._resolve(target_type, target, mention)
        if resolved is None:
            self.log.info(f"[napcat_send] 目标未确定，未发送：{why}")
            return f"未发送：{why}"
        send_type = target_type or ("group" if resolved.get("group_id") else "friend")
        return self._do_send(send_type, resolved, direct)

    # ==================== 链路内部查找 ====================
    def _resolve(self, target_type: str, target: str, mention: str
                 ) -> Tuple[Optional[Dict], str, str, list]:
        """内部子工具搜索目标，返回 (resolved, why, 待追问字段: target/mention, 候选)

        群名/好友先拉全量列表再按归一化 + 拼音 + 相似度排序（subtools.find_group /
        find_friend），只有能确定时才直接用；多个都像或只有错字级相似 → 交追问确认。
        """
        from func.toolbox.napcat.active_sender import subtools
        target = str(target or "").strip()
        mention = str(mention or "").strip()
        if not target:
            return None, "还不知道这条消息要发给谁", "target", []
        if str(target_type) not in ("friend", "group"):
            return self._resolve_any(target, mention)
        if str(target_type) == "group":
            gid, why, candidates = subtools.find_group(target)
            if not gid:
                return None, why, "target", candidates
            if mention:
                row = subtools.find_member(gid, mention)
                if not row:
                    members = subtools.member_names(gid, query=mention)
                    tail = f"（群里的人：{members}）" if members else ""
                    return None, f"群 {gid} 里没找到成员「{mention}」{tail}", "mention", []
                return {"group_id": gid, "member": row}, "", "", candidates
            return {"group_id": gid, "member": None}, "", "", candidates
        uid, why, candidates = subtools.find_friend(target)
        if not uid:
            return None, why, "target", candidates
        return {"user_id": uid}, "", "", candidates

    def _resolve_any(self, target: str, mention: str
                     ) -> Tuple[Optional[Dict], str, str, list]:
        """未指定 target_type（规则硬触发）时的目标解析：群/好友两表都查。

        只有一边能确定才直接用；两边都能确定时，名称带「群」按群处理，否则交追问，
        不猜、不瞎发。
        """
        from func.toolbox.napcat.active_sender import subtools
        gid, g_why, g_cand = subtools.find_group(target)
        uid, f_why, f_cand = subtools.find_friend(target)
        candidates = (g_cand + f_cand)[:6]
        if gid and (not uid or "群" in target):
            if mention:
                row = subtools.find_member(gid, mention)
                if not row:
                    members = subtools.member_names(gid, query=mention)
                    tail = f"（群里的人：{members}）" if members else ""
                    return None, f"群 {gid} 里没找到成员「{mention}」{tail}", "mention", []
                return {"group_id": gid, "member": row}, "", "", candidates
            return {"group_id": gid, "member": None}, "", "", candidates
        if uid and not gid:
            return {"user_id": uid}, "", "", candidates
        if uid and gid:
            return None, f"「{target}」既像好友也像群，我不确定该发哪里", "target", candidates
        why = g_why if "群" in target else (f_why or g_why)
        return None, str(why or f"没有能确定是「{target}」的好友或群"), "target", candidates

    def _clarify_question(self, why: str, ask: str, target_type: str,
                          candidates: list) -> str:
        """按「缺哪个字段」构造追问；带排序后的候选，用户一句话就能确认"""
        if ask == "mention":
            return f"{why}，你希望 @ 谁呢？给我名字或 QQ 号都行。"
        names = [n for _s, n in (candidates or [])[:5] if n]
        if names:
            return f"{why}，你要找的是不是：{'、'.join(names)}？回一句名字或号码就行。"
        if "还不知道" in why:
            return "这条消息要发给谁呀？给我昵称、群名或号码都行。"
        return f"{why}，你再说一下具体是哪个，或者直接给我号码也行。"

    def _ask(self, question: str) -> str:
        """发起 excuse 追问（阻塞等用户补充，超时/未启用返回空串）"""
        try:
            from func.toolbox.excuse import TBExcuse
            return str(TBExcuse().ask(question, meowid=self._meowid) or "").strip()
        except Exception:
            self.log.exception("[napcat_send] excuse 追问失败")
            return ""

    # ==================== 角色拟稿 ====================
    def _draft(self, request: str, target_type: str, target: str,
               mention: str) -> str:
        """只有意图、没有现成内容时，由角色自己写出一条要发出去的正文"""
        from func.toolbox.napcat.active_sender import subtools
        request = str(request or "").strip()
        if not request:
            return ""
        llm = subtools.toolbox_llm()
        if not llm or not getattr(llm, "client", None):
            self.log.warning("[napcat_send] 拟稿 LLM 不可用，改为追问内容")
            return ""
        target_desc = str(target or "").strip() or "（还没定，先按主人的意思写）"
        extra = ""
        if str(target_type) == "group":
            target_desc = f"{target_desc}（群聊）"
            if mention:
                target_desc = f"{target_desc}，要 @ {mention}"
                extra = f"\n（@{mention} 由系统单独 @ 出去，正文里不要再写 @{mention}）"
        else:
            if str(target_type) == "friend":
                target_desc = f"{target_desc}（好友私聊）"
        try:
            resp = llm.chat([
                {"role": "system",
                 "content": subtools.draft_prompt(self._meowid, request)},
                {"role": "user", "content": (
                    f"发给谁：{target_desc}\n"
                    f"主人的要求：{request}\n"
                    f"请直接写出要发送的消息正文。{extra}"
                )},
            ])
        except Exception:
            self.log.exception("[napcat_send] 拟稿失败，改为追问内容")
            return ""
        if not resp or not resp.choices:
            return ""
        text = self._clean_draft(resp.choices[0].message.content)
        # @ 由系统单独发出，正文开头自带的 @名字 去掉，避免重复 @
        if text and mention:
            text = re.sub(r"^@\s*" + re.escape(str(mention)) + r"[\s:：,，]*", "", text).strip()
        return text

    @staticmethod
    def _clean_draft(text) -> str:
        """清洗拟稿：去掉「正文：」这类前缀和包裹引号，只留消息本身"""
        s = str(text or "").strip()
        if not s:
            return ""
        s = re.sub(r"^(消息内容|消息|正文|内容|发送内容)\s*[:：]\s*", "", s)
        return s.strip().strip('"“”\'‘’「」『』').strip()

    # ==================== 内部子工具发送 ====================
    def _do_send(self, target_type: str, resolved: Dict, direct: Dict) -> str:
        from func.toolbox.napcat.active_sender import subtools
        kind = str(direct.get("type") or "")
        text = str(direct.get("text") or "")
        group_id = resolved.get("group_id")
        user_id = resolved.get("user_id")
        member = resolved.get("member") or {}
        target_id = str(group_id or user_id or "")

        if member and group_id and kind == "text":
            return subtools.dispatch("send_qq_at", {
                "group_id": group_id,
                "user_id": str(member.get("user_id") or ""),
                "text": text,
            })
        if member and kind != "text":
            self.log.warning("[napcat_send] @ 只对文本生效，本次按普通内容发送")

        if kind == "link":
            return subtools.dispatch("send_qq_link", {
                "target_type": target_type, "target_id": target_id,
                "url": direct.get("url") or "", "desc": text,
            })
        if kind == "image":
            return subtools.dispatch("send_qq_image", {
                "target_type": target_type, "target_id": target_id,
                "file_path": direct.get("file_path") or "",
            })
        if kind == "file":
            return subtools.dispatch("send_qq_file", {
                "target_type": target_type, "target_id": target_id,
                "file_path": direct.get("file_path") or "",
            })
        return subtools.dispatch("send_qq_message", {
            "target_type": target_type, "target_id": target_id, "text": text,
        })
