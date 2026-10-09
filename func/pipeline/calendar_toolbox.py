# -*- coding: utf-8 -*-
# func/pipeline/calendar_toolbox.py
# 待办提醒 → QQ 桥接：用 toolbox LLM 拟写提醒词后经 NapCat 发送

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig
from func.pipeline.system_prompt import SystemPromptBridge


class DateCalendarToolbox:
    """待办提醒 QQ 链路：toolbox LLM 拟写提醒词，按昵称匹配 user_id 发送"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.llm = self._create_llm()

    def _create_llm(self):
        if self.config.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(self.config)
        if self.config.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(self.config)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(self.config)

    def remind(self, username, time_str, content):
        base = SystemPromptBridge().get_napcat_prompt(username, "")
        prompt = (
            f"{base}\n\n"
            f"【你此刻想到的事】现在是{time_str}，你想起了要提醒{username}：{content}\n"
            f"这是你主动开口说话，第一句就是你要说给{username}听的话；不要复述提醒内容，"
            f"不要出现“好的”“收到”“我这就”这类回应指令的话。"
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"提醒事项：{content}"},
        ]
        resp = self.llm.chat(messages)
        text = ""
        if resp and getattr(resp, "choices", None):
            text = (resp.choices[0].message.content or "").strip()
        if not text:
            self.log.warning(f"[待办提醒] QQ 提醒词为空: {username}")
            return
        user_id = self._resolve_user_id(username)
        if not user_id:
            self.log.warning(f"[待办提醒] 未匹配到 QQ 用户: {username}")
            return
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        TBNapCatCore().send_private_text(user_id, text)
        self.log.info(f"[待办提醒] 已发送 QQ 提醒给 {username}({user_id})")

    def _resolve_user_id(self, username):
        try:
            from func.toolbox.napcat.active_sender.get_friendlist import TBGetFriendList
            for f in TBGetFriendList().get():
                if f.get("remark") == username or f.get("nickname") == username:
                    return f.get("user_id")
        except Exception:
            self.log.exception("获取好友列表失败")
        return None
