# utils/comment_generator.py
import random
import re
from func.search.search_core import SearchCore
from func.llm.llm_core import LLmCore

class CommentGenerator:
    def __init__(self, lyric_handler, log):
        self.lyric_handler = lyric_handler
        self.log = log

    def generate_comment(self, songname, username, uid, query):
        """生成听后感，返回字符串"""
        self.log.info(f"提前准备歌曲《{songname}》的解说内容")
        llm_core = LLmCore()

        # 1. 获取角色卡系统提示
        character = None
        if llm_core.character_cards:
            if query:
                character = llm_core.select_character_by_message(query)
            else:
                character = random.choice(llm_core.character_cards)
        system_prompt = character.build_system_prompt() if character else "你是一个虚拟主播小猫娘，请用可爱、口语化的方式分享听后感。"

        # 2. 搜索结果
        search_core = SearchCore()
        results = search_core.baidu_web_search(songname)
        context = "\n".join([f"- {r.get('title','')}: {r.get('abstract','')}" for r in results[:3]]) if results else "没有找到关于这首歌的更多信息。"

        # 3. 歌词片段
        lyrics_snippet = ""
        all_sentences = self.lyric_handler.get_all_sentences(songname)
        if all_sentences and len(all_sentences) >= 3:
            start_idx = random.randint(0, len(all_sentences) - 3)
            selected = all_sentences[start_idx:start_idx+3]
            lyrics_snippet = " ".join([text for _, text in selected])
            self.log.info(f"选取歌词片段: {lyrics_snippet[:50]}...")

        # 4. 记忆检索
        memory_snippets = []
        try:
            uid_str = str(uid) if uid else "0"
            memory = llm_core._ensure_memory_manager(uid_str, username)
            if memory:
                retrieval_query = f"关于歌曲《{songname}》或用户{username}对这首歌的喜好"
                if query:
                    retrieval_query = f"{query} 关于歌曲《{songname}》"
                if hasattr(memory, 'retrieve_relevant_memories'):
                    memories = memory.retrieve_relevant_memories(retrieval_query, limit=2)
                    for mem in memories:
                        memory_snippets.append(mem.get('text', '') if isinstance(mem, dict) else str(mem))
                elif hasattr(memory, 'get_chat_record_context'):
                    memories = memory.get_chat_record_context(retrieval_query, top_k=2)
                    memory_snippets.extend(memories)
                elif hasattr(memory, 'get_relevant_memories'):
                    memories = memory.get_relevant_memories(retrieval_query, limit=2)
                    memory_snippets.extend(memories)
        except Exception as e:
            self.log.warning(f"记忆检索失败: {e}")
        memory_text = "\n".join([f"- {s}" for s in memory_snippets if s]) if memory_snippets else ""

        # 5. 构建用户提示
        if lyrics_snippet and memory_text:
            user_prompt = f"用户刚刚听完了《{songname}》这首歌。以下是关于这首歌的一些信息：\n{context}\n以下是这首歌中的一段歌词：\n{lyrics_snippet}\n以下是和用户相关的历史记忆：\n{memory_text}\n现在歌曲已经播放完毕，和主人分享一下歌曲内容，结合歌词、搜索结果以及这些记忆，自然、口语化地聊聊天吧。"
        elif lyrics_snippet:
            user_prompt = f"用户刚刚听完了《{songname}》这首歌。以下是关于这首歌的一些信息：\n{context}\n以下是这首歌中的一段歌词：\n{lyrics_snippet}\n现在歌曲已经播放完毕，和主人分享一下歌曲内容，结合歌词和搜索结果，聊聊天吧。"
        elif memory_text:
            user_prompt = f"用户刚刚听完了《{songname}》这首歌。以下是关于这首歌的一些信息：\n{context}\n以下是和用户相关的历史记忆：\n{memory_text}\n现在歌曲已经播放完毕，和主人分享一下歌曲内容，结合搜索结果和这些记忆，聊聊天吧。"
        else:
            user_prompt = f"用户刚刚听完了《{songname}》这首歌。以下是关于这首歌的一些信息：\n{context}\n现在歌曲已经播放完毕，和主人分享一下歌曲内容，聊聊天吧。"

        # 6. 调用 LLM
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        comment = ""
        if llm_core.local_llm_type == "aliyun":
            from func.llm.port.aliyun_stream import AliyunStreamLLM
            client = AliyunStreamLLM()
            full = ""
            for chunk in client.generate_stream(messages, options={"max_tokens": 512}):
                full += chunk
            comment = full.strip()
        elif llm_core.local_llm_type == "ollama":
            from func.llm.port.ollama import Ollama
            client = Ollama()
            combined = f"{system_prompt}\n\n{user_prompt}"
            comment = client.generate(combined, system="你是一个音乐解说员，请直接输出介绍。").strip()
        elif llm_core.local_llm_type == "deepseek":
            from func.llm.port.deepseek import DeepSeekLLM
            client = DeepSeekLLM()
            comment = client.generate(messages, options={"max_tokens": 512}).strip()
        else:
            comment = f"《{songname}》是一首很棒的歌曲。"

        # 7. 过滤开场白关键词
        forbidden = ["要开始唱", "要唱咯", "准备唱", "开始唱"]
        if any(phrase in comment for phrase in forbidden):
            self.log.warning(f"解说内容包含开场白词汇，使用默认评论: {comment}")
            comment = f"《{songname}》是一首很棒的歌曲。"

        return comment