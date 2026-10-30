# -*- coding: utf-8 -*-
"""文本脑：把「自己记下的画面 / 台词 / 感想」整理成角色口吻的回答与收尾影评。

只用注入的 ctx.llm()（主程序 toolbox 文本模型）+ 角色人设提示词；
任何一步失败都退回到「直接念自己记下的内容」，不会让观影流程卡住。
"""

from . import prompts


class MovieBrain:
    def __init__(self, ctx, config, log):
        self.ctx = ctx
        self.config = config
        self.log = log

    # ==================== 公共 ====================
    def persona(self, uid=""):
        """角色人设提示词（tool 口径：人设 + 行为约束，不带对话记忆）"""
        try:
            text = self.ctx.prompt().get_tool_prompt(uid, "")
            return str(text or "").strip()
        except Exception:
            self.log.exception("[movie_watch] 获取角色提示词失败")
            return ""

    def _chat(self, system, user, uid=""):
        try:
            llm = self.ctx.llm()
            if llm is None or not getattr(llm, "client", None):
                return ""
            resp = llm.chat([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ])
            if not resp or not resp.choices:
                return ""
            content = (resp.choices[0].message.content or "").strip()
            return self._clean(content)
        except Exception:
            self.log.exception("[movie_watch] 文本模型调用失败")
            return ""

    @staticmethod
    def _clean(text):
        import re
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"【[^】]*】", "", text)
        text = re.sub(r"^[#>*\-\s]+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ==================== 让角色自己开口 ====================
    def say(self, instruction, uid="", fallback=""):
        """按「这次要传达的意思」让角色自己说一句话（不背预设台词）"""
        instruction = str(instruction or "").strip()
        if not instruction:
            return fallback
        system = self.persona(uid)
        system = f"{system}\n\n{prompts.SAY_SYSTEM}" if system else prompts.SAY_SYSTEM
        reply = self._chat(system, instruction, uid)
        return reply or fallback

    def notes_context(self, notes):
        """把记录整理成给模型看的记忆文本（画面 + 台词 + 感想）"""
        limit = max(1, int(self.config.context_notes))
        picked = list(notes)[-limit:]
        lines = []
        for note in picked:
            clock = note.get("clock") or "--:--"
            scene = str(note.get("scene") or "").strip()
            comment = str(note.get("comment") or "").strip()
            dialogue = str(note.get("dialogue") or "").strip()
            row = f"[{clock}]"
            if scene:
                row += f" 画面：{scene}"
            if dialogue:
                row += f" 台词：{dialogue}"
            if comment:
                row += f" 我的想法：{comment}"
            lines.append(row)
        return "\n".join(lines)

    # ==================== 回答提问 ====================
    def answer(self, question, notes, meta, uid=""):
        """用户发问时，依据自己记下的内容回答"""
        context = self.notes_context(notes)
        if not context:
            return self._fallback_answer(notes)
        title = meta.get("window_title") or "这部片"
        system = self.persona(uid)
        system = f"{system}\n\n{prompts.ASK_SYSTEM}" if system else prompts.ASK_SYSTEM
        user = (
            "你记下的内容：\n" + context + "\n\n"
            f"你正在陪主人看的片（窗口）：{title}\n"
            f"已经看了 {meta.get('duration_text') or '一会儿'}。\n"
            f"主人问：{question or '刚才演到哪了？'}\n"
            "用你自己的口吻回答（60~120字，不列表）。"
        )
        reply = self._chat(system, user, uid)
        return reply or self._fallback_answer(notes)

    def _fallback_answer(self, notes):
        if not notes:
            return "刚才我还没看到什么呢，画面一直是空的"
        last = notes[-1]
        scene = str(last.get("scene") or "").strip()
        dialogue = str(last.get("dialogue") or "").strip()
        comment = str(last.get("comment") or "").strip()
        parts = []
        if dialogue:
            parts.append(f"刚听到的是：{dialogue}")
        elif scene:
            parts.append(f"刚才那一幕我看到的是：{scene}")
        if comment:
            parts.append(comment)
        return "，".join(parts) or "我看得出神，没顾上想太多"

    # ==================== 收尾影评（不道谢） ====================
    def finish_review(self, notes, meta, uid=""):
        """观影结束：说这一场的整体感觉"""
        context = self.notes_context(notes)
        system = self.persona(uid)
        system = f"{system}\n\n{prompts.FINISH_SYSTEM}" if system else prompts.FINISH_SYSTEM
        user = (
            f"你们一起看的片（窗口）：{meta.get('window_title') or '一部片'}\n"
            f"看了 {meta.get('duration_text') or '一会儿'}，一共记下 {len(notes)} 帧。\n"
            + ("你记下的内容：\n" + context + "\n\n" if context else "")
            + "现在说你的整体感觉（60~120字，不要道谢）。"
        )
        reply = self._chat(system, user, uid)
        return reply or self._fallback_review(notes, meta)

    def _fallback_review(self, notes, meta):
        duration = meta.get("duration_text") or "这么久"
        highlight = ""
        for note in reversed(notes):
            comment = str(note.get("comment") or "").strip()
            if comment:
                highlight = f"。最抓我的是——{comment}"
                break
        return f"{duration}看下来{highlight or '，我一直在看画面，没怎么分出神来'}。整体就这样吧"
