# utils/helper.py
import re
import time
from func.llm.llm_core import LLmCore

class SingHelper:
    """唱歌模块的通用辅助方法"""

    def __init__(self, tts_core, log):
        self.tts_core = tts_core
        self.log = log

    def wait_tts_finish(self, timeout=10):
        """等待当前 TTS 播放结束"""
        start = time.time()
        while self.tts_core.mpvPlay.current_process is not None:
            if time.time() - start > timeout:
                break
            time.sleep(0.1)

    def record_conversation(self, user_msg, ai_msg, user_name="系统", uid=0):
        """将对话记录到聊天历史和记忆系统"""
        try:
            llm_core = LLmCore()
            llm_core._write_chat_record(user_name, user_msg, user_name)
            llm_core._write_chat_record(user_name, ai_msg, llm_core.llmData.Ai_Name)
            uid_str = str(uid)
            memory = llm_core._ensure_memory_manager(uid_str, user_name)
            if memory:
                memory.add_user_message(user_msg, user_name)
                memory.add_assistant_message(ai_msg)
        except Exception as e:
            self.log.warning(f"记录对话失败: {e}")

    def split_comment_into_sentences(self, comment):
        """将长评论拆分为适合 TTS 的短句列表"""
        if not comment:
            return []
        split_pattern = r'([。！？；：，,.;:!?])'
        parts = re.split(split_pattern, comment)
        segments = []
        buffer = ""
        for part in parts:
            if re.match(split_pattern, part):
                buffer += part
                if buffer.strip():
                    segments.append(buffer.strip())
                buffer = ""
            else:
                buffer += part
        if buffer.strip():
            segments.append(buffer.strip())

        final_segments = []
        for seg in segments:
            if len(seg) > 20:
                sub_parts = re.split(r'([，, ])', seg)
                sub_buf = ""
                for sp in sub_parts:
                    sub_buf += sp
                    if len(sub_buf) > 15 and (sp in ['，', ',', ' '] or sub_buf.endswith(('。','！','？','；','：'))):
                        if sub_buf.strip():
                            final_segments.append(sub_buf.strip())
                        sub_buf = ""
                if sub_buf.strip():
                    final_segments.append(sub_buf.strip())
            else:
                final_segments.append(seg)
        return final_segments if final_segments else [comment]

    def remove_parentheses(self, text):
        """去除括号及其内容"""
        text = re.sub(r'[（(][^）)]*[）)]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def safe_get_uid_str(self, uid):
        """将 uid 转换为字符串，确保不为 None"""
        return str(uid) if uid else "0"