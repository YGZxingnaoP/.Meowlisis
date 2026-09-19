import json
import re

from .prompt import (SUMMARIZE_SYSTEM, COMMENT_SYSTEM_EXTRA, JUDGE_SYSTEM,
                     summarize_user, judge_user)


class BookBrain:
    # 输出上限（250 字中文 ≈ 400 tokens，100 字 ≈ 200 tokens，留足余量防截断）
    SUMMARY_MAX_TOKENS = 512
    COMMENT_MAX_TOKENS = 320

    def __init__(self, llm, ctx):
        """剧情概括 / 角色点评 / 续读判定"""
        self.llm = llm
        self.ctx = ctx

    def summarize(self, title, text):
        """概括已读剧情（≤250 字）"""
        if not text or not text.strip():
            return ""
        content = self.llm.chat([
            {"role": "system", "content": SUMMARIZE_SYSTEM},
            {"role": "user", "content": summarize_user(title, text)},
        ], max_tokens=self.SUMMARY_MAX_TOKENS)
        return content

    def comment(self, username, title, summary):
        """以角色身份做简短点评（带短期记忆 + 完整系统角色卡，≤100 字）"""
        try:
            system = self.ctx.prompt().get_system_prompt(username or "", summary or "") or ""
        except Exception:
            system = ""
        history = self._short_history()
        user = (f"刚读完《{title}》的一段剧情。剧情概括：{summary or '（无）'}\n"
                f"请据此做一句简短点评。")
        messages = []
        if system:
            messages.append({"role": "system", "content": system + COMMENT_SYSTEM_EXTRA})
        else:
            messages.append({"role": "system", "content": COMMENT_SYSTEM_EXTRA.strip()})
        messages.extend(history)
        messages.append({"role": "user", "content": user})
        return self.llm.chat(messages, max_tokens=self.COMMENT_MAX_TOKENS)

    def judge_continue(self, title, text):
        """判定用户是否想继续读（失败按不继续）"""
        content = self.llm.chat([
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": judge_user(title, text)},
        ], temperature=self._judge_temperature(), max_tokens=self._judge_max_tokens())
        return self._parse_judge(content)

    def _short_history(self):
        """取近期短期记忆作为上下文"""
        try:
            data = self.ctx.short_memory().load() or []
            return [{"role": m["role"], "content": m["content"]}
                    for m in data[-6:] if m.get("role") and m.get("content")]
        except Exception:
            return []

    def _judge_temperature(self):
        """续读判定温度"""
        try:
            return float(getattr(self.llm.config, "followup_temperature", 0.2))
        except Exception:
            return 0.2

    def _judge_max_tokens(self):
        """续读判定的输出上限"""
        try:
            return int(getattr(self.llm.config, "followup_max_tokens", 256))
        except Exception:
            return 256

    @staticmethod
    def _parse_judge(content):
        """解析判定 JSON"""
        if not content:
            return False
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict) and "continue" in data:
                    return bool(data.get("continue"))
            except Exception:
                pass
        low = content.lower()
        return "true" in low
