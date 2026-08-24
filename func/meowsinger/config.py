# -*- coding: utf-8 -*-
# func/meowsinger/config.py
# meowsinger 全部配置项集中于此（独立 LLM port、点歌、翻唱、停止、感想）
from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class MeowSingerConfig:
    """meowsinger 配置管理：读取 config.yml 的 meowsinger 节点与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('meowsinger', {})
        self.enabled = bool(cfg.get('enabled', True))

        # 独立 LLM 端口
        self.llm_type = cfg.get('llm_type', 'deepseek')
        ds = cfg.get('deepseek', {})
        self.deepseek_api_key = ds.get('api_key', '')
        self.deepseek_base_url = ds.get('base_url', 'https://api.deepseek.com/v1')
        self.deepseek_model = ds.get('model', 'deepseek-chat')
        self.deepseek_temperature = ds.get('temperature', 0.7)
        self.deepseek_max_tokens = ds.get('max_tokens', 2048)
        al = cfg.get('aliyun', {})
        self.aliyun_api_key = al.get('api_key', '')
        self.aliyun_base_url = al.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.aliyun_model = al.get('model', 'qwen-plus')
        self.aliyun_temperature = al.get('temperature', 0.7)
        self.aliyun_max_tokens = al.get('max_tokens', 2048)

        # 点歌模块
        song = cfg.get('song', {})
        self.song_enabled = bool(song.get('enabled', True))
        self.song_trigger_mode = str(song.get('trigger_mode', 'both')).strip() or 'both'
        self.song_prefix = self._as_list(song.get('prefix', ['Meowlisis点歌']))
        self.song_intent = self._as_list(song.get('intent', ['点歌', '放歌', '放首歌']))
        self.netease_url = song.get('netease_url', 'http://127.0.0.1:5000')

        # 翻唱模块
        cover = cfg.get('cover', {})
        self.cover_enabled = bool(cover.get('enabled', True))
        self.cover_trigger_mode = str(cover.get('trigger_mode', 'both')).strip() or 'both'
        self.cover_prefix = self._as_list(cover.get('prefix', ['Meowlisis唱歌']))
        self.cover_intent = self._as_list(cover.get('intent', ['唱首歌', '唱歌']))
        self.rvc_url = cover.get('rvc_url', 'http://127.0.0.1:7865')
        self.rvc_model = cover.get('rvc_model', 'kikiV1.pth')
        self.rvc_index = cover.get('rvc_index', '')
        self.learn_mode = cover.get('learn_mode', 'idle')
        self.learn_users = self._as_list(cover.get('learn_users', []))
        self.learn_trigger = cover.get('learn_trigger', '喵利呜西斯，可以开始学歌啦')

        # 停止触发
        stop = cfg.get('stop', {})
        self.stop_keywords = self._as_list(stop.get('keywords', ['停止唱歌', '停停停']))

        # 感想
        sentiment = cfg.get('sentiment', {})
        self.sentiment_enabled = bool(sentiment.get('enabled', True))
        self.sentiment_word_count = int(sentiment.get('word_count', 300) or 300)
        self.sentiment_prompt = sentiment.get('prompt', '') or ''

        # 引导词
        prompt = cfg.get('prompt', {})
        self.prompt_reply = prompt.get('reply', '') or ''
        self.prompt_summary = prompt.get('summary', '') or ''

        # 搜索引导词
        search = cfg.get('search', {})
        self.search_prompt = search.get('prompt', '') or ''

    @staticmethod
    def _as_list(value):
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [v.strip() for v in value.split(',') if v.strip()]
        return []
