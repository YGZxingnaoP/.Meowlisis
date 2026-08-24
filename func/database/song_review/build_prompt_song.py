# -*- coding: utf-8 -*-
# func/database/song_review/build_prompt_song.py
# 构建感想引导词（非系统提示词），供 database_llm 合成感想
class MeowSongBuildPrompt:
    """感想引导词构建"""

    def build(self, song_title, mode, lrc, search_result, word_count=300):
        from func.meowsinger.config import MeowSingerConfig
        template = MeowSingerConfig().sentiment_prompt
        if not template:
            return ""
        verb = "唱" if mode == "cover" else "放"
        result_text = search_result or "暂时没有搜到这首歌的资料"
        return (
            template
            .replace("{verb}", verb)
            .replace("{song_title}", song_title)
            .replace("{lrc}", lrc)
            .replace("{result_text}", result_text)
            .replace("{word_count}", str(word_count))
        )
