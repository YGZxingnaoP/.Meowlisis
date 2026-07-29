# utils/intro_generator.py
from func.llm.llm_core import LLmCore

class IntroGenerator:
    def __init__(self, tts_core, log):
        self.tts_core = tts_core
        self.log = log

    def generate_intro(self, songname, username, user_query="", uid=0):
        """生成并播放开场白，返回文本内容"""
        base_prompt = f"用户{username}点播歌曲《{songname}》，"
        character_suffix = self._get_character_prompt_suffix(user_query) if user_query else ""
        if character_suffix:
            prompt = base_prompt + character_suffix
        else:
            prompt = base_prompt + "请以小猫娘的口吻，生成一句简短、热情的开场白，表示即将演唱这首歌。不要超过20个字。"

        intro_text = f"喵呜，那我们来听《{songname}》"
        llm_generated = False
        try:
            llm_core = LLmCore()
            if llm_core.local_llm_type == "ollama":
                from func.llm.port.ollama import Ollama
                client = Ollama()
                response = client.generate(prompt, system="你是一个虚拟主播，请直接输出回复，不要有任何额外解释。")
                intro_text = response.strip()
                llm_generated = True
            elif llm_core.local_llm_type == "aliyun":
                from func.llm.port.aliyun_stream import AliyunStreamLLM
                client = AliyunStreamLLM()
                messages = [{"role": "user", "content": prompt}]
                full = ""
                for chunk in client.generate_stream(messages, options={"max_tokens": 50}):
                    full += chunk
                intro_text = full.strip()
                llm_generated = True
            elif llm_core.local_llm_type == "deepseek":
                from func.llm.port.deepseek import DeepSeekLLM
                client = DeepSeekLLM()
                messages = [{"role": "user", "content": prompt}]
                try:
                    intro_text = client.generate(messages, options={"max_tokens": 50}).strip()
                    llm_generated = True
                except TypeError:
                    intro_text = client.generate(messages).strip()
                    llm_generated = True
        except Exception as e:
            self.log.warning(f"LLM 生成开场白失败: {e}")

        # 播放
        self.tts_core.tts_say(intro_text)
        # 等待播放完成（通过外部传入等待方法，或者由调用方负责）
        # 这里假设外部会调用 wait_tts_finish，我们只返回文本和标志
        return intro_text, llm_generated

    def _get_character_prompt_suffix(self, user_query: str) -> str:
        try:
            llm_core = LLmCore()
            if not llm_core.character_cards:
                return ""
            card = llm_core.select_character_by_message(user_query)
            if card:
                personality = card.personality[:50] if card.personality else ""
                if personality:
                    return f"请以下角色个性：{personality}。以{card.name}的口吻说一句简短的开场白，表示即将演唱这首歌。不要超过20个字。"
                else:
                    return f"请以角色“{card.name}”的口吻说一句简短的开场白，表示即将演唱这首歌。不要超过20个字。"
        except Exception as e:
            self.log.warning(f"获取角色卡失败: {e}")
        return ""