# -*- coding: utf-8 -*-
# func/catbrain/config.py
# CatBrain 全部配置项统一管理（新增配置均带默认值，config.yml 可后续覆盖）

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class MeowCatBrainConfig:
    """集中管理 catbrain 节点的全部配置项与默认值"""

    def __init__(self):
        root = ConfigReader().get()
        cfg = root.get('catbrain', {})

        # ========== 角色卡选择 ==========
        # character_card 节点：卡片文件名（不含 .json 后缀）与当前选中角色
        card = root.get('character_card', {})
        self.character_card_file = card.get('card_file', 'prompt')
        self.character_card_select = card.get('select', '')

        # ========== 长期记忆 ==========
        lt = cfg.get('long_term_mem', {})
        # 长期记忆加载的回溯天数（从当天往前算）
        self.memory_days = lt.get('memory_days', 300)

        # ========== 记忆摘要 ==========
        am = cfg.get('abstract_mem', {})
        # 摘要触发轮数（.temp/record.txt 的消息行数）
        self.summary_rounds = am.get('summary_rounds', 30)
        # 摘要提示词检索时加载的摘要条数上限
        self.summary_top_limit = am.get('summary_top_limit', 20)
        # 当前话题更新间隔（秒）
        self.topic_update_interval = am.get('topic_update_interval', 60)
        # 摘要独立后端类型：deepseek / aliyun
        self.abstract_llm_type = am.get('llm_type', 'deepseek')

        # 摘要独立 DeepSeek 配置
        ds = am.get('deepseek', {})
        self.ab_deepseek_api_key = ds.get('api_key', '')
        self.ab_deepseek_base_url = ds.get('base_url', 'https://api.deepseek.com/v1')
        self.ab_deepseek_model = ds.get('model', 'deepseek-chat')
        self.ab_deepseek_temperature = ds.get('temperature', 0.7)
        self.ab_deepseek_max_tokens = ds.get('max_tokens', 2048)

        # 摘要独立 Qwen（阿里云）配置
        qw = am.get('aliyun', {})
        self.ab_aliyun_api_key = qw.get('api_key', '')
        self.ab_aliyun_base_url = qw.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.ab_aliyun_model = qw.get('model', 'qwen-plus')
        self.ab_aliyun_temperature = qw.get('temperature', 0.7)
        self.ab_aliyun_max_tokens = qw.get('max_tokens', 2048)

        # 摘要独立 Gemini 配置
        gm = am.get('gemini', {})
        self.ab_gemini_api_key = gm.get('api_key', '')
        self.ab_gemini_base_url = gm.get('base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/')
        self.ab_gemini_model = gm.get('model', 'gemini-3.6-flash')
        self.ab_gemini_temperature = gm.get('temperature', 0.7)
        self.ab_gemini_max_tokens = gm.get('max_tokens', 2048)

        # 摘要 tags 上限（事件概括的标签数量上限）
        self.summary_tags_limit = am.get('tags_limit', 3)

        # ========== 摘要证据 ==========
        ev = am.get('evidence', {})
        # 强化值半衰期（天）
        self.evidence_rein_half_life_days = ev.get('rein_half_life_days', 30)
        # 质疑值半衰期（天）
        self.evidence_disp_half_life_days = ev.get('disp_half_life_days', 180)
        # 净分数达到该值即 confirmed
        self.evidence_confirmed_threshold = ev.get('confirmed_threshold', 1.0)
        # 净分数低于该值即归档候选
        self.evidence_archive_threshold = ev.get('archive_threshold', -2.0)
        # 负分持续该天数后真正归档
        self.evidence_archive_days = ev.get('archive_days', 14)
        # same 判定的强化增量
        self.evidence_same_delta = ev.get('same_delta', 0.5)
        # opposite 判定的质疑增量
        self.evidence_opposite_delta = ev.get('opposite_delta', 1.0)

        # ========== 摘要去重 ==========
        dd = am.get('dedup', {})
        # 去重比对每批候选条数
        self.dedup_batch_size = dd.get('batch_size', 20)
        # 去重比对最大批次数
        self.dedup_max_batches = dd.get('max_batches', 9)
        # 检索匹配模式：strict 两元素相同 / broad 首 tag 匹配
        self.dedup_match_mode = dd.get('match_mode', 'strict')

        # ========== 摘要归档 ==========
        ar = am.get('archive', {})
        # 归档扫描间隔（秒）
        self.archive_sweep_interval_seconds = ar.get('sweep_interval_seconds', 3600)

        # ========== 摘要准确度 ==========
        ac = am.get('accuracy', {})
        # same 判定时 accuracy 增量
        self.accuracy_same_increment = ac.get('same_increment', 1)
        # opposite 判定时 accuracy 减量
        self.accuracy_opposite_decrement = ac.get('opposite_decrement', 2)

        # ========== 价值观 ==========
        vs = cfg.get('cat_values', cfg.get('values', {}))
        # 价值观独立后端类型：deepseek / aliyun（所有密钥独立配置，禁止混淆）
        self.values_llm_type = vs.get('llm_type', 'deepseek')
        vds = vs.get('deepseek', {})
        self.val_deepseek_api_key = vds.get('api_key', '')
        self.val_deepseek_base_url = vds.get('base_url', 'https://api.deepseek.com/v1')
        self.val_deepseek_model = vds.get('model', 'deepseek-chat')
        val = vs.get('aliyun', {})
        self.val_aliyun_api_key = val.get('api_key', '')
        self.val_aliyun_base_url = val.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.val_aliyun_model = val.get('model', 'qwen-plus')

        vgm = vs.get('gemini', {})
        self.val_gemini_api_key = vgm.get('api_key', '')
        self.val_gemini_base_url = vgm.get('base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/')
        self.val_gemini_model = vgm.get('model', 'gemini-3.6-flash')
        # 价值观硬编码参数：temperature 0.7，思考强度最高
        self.values_temperature = 0.7
        self.values_enable_thinking = True
        self.values_max_tokens = vs.get('max_tokens', 8192)
        # 单次更新中工具调用的最大迭代轮数（超出直接结束，不走后续流程）
        self.values_max_tool_rounds = vs.get('max_tool_rounds', 100)
        # 12 小时累计计时：检查间隔（秒）与触发间隔（小时）
        self.values_timer_check_seconds = vs.get('timer_check_seconds', 300)
        self.values_update_interval_hours = vs.get('update_interval_hours', 12)
        # 哲思话题触发更新的冷却时间（分钟）
        self.values_philosophy_cooldown_minutes = vs.get('philosophy_cooldown_minutes', 30)

        # 二次审查（默认关闭，需配置另一平台大模型）
        sr = vs.get('second_review', {})
        self.values_second_review_enabled = sr.get('enabled', False)
        self.values_second_review_llm_type = sr.get('llm_type', 'aliyun')
        srd = sr.get('deepseek', {})
        self.val_sr_deepseek_api_key = srd.get('api_key', '')
        self.val_sr_deepseek_base_url = srd.get('base_url', 'https://api.deepseek.com/v1')
        self.val_sr_deepseek_model = srd.get('model', 'deepseek-chat')
        sra = sr.get('aliyun', {})
        self.val_sr_aliyun_api_key = sra.get('api_key', '')
        self.val_sr_aliyun_base_url = sra.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.val_sr_aliyun_model = sra.get('model', 'qwen-plus')

        srg = sr.get('gemini', {})
        self.val_sr_gemini_api_key = srg.get('api_key', '')
        self.val_sr_gemini_base_url = srg.get('base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/')
        self.val_sr_gemini_model = srg.get('model', 'gemini-3.6-flash')

        # ========== 用户记忆 ==========
        um = cfg.get('user_memory', {})
        # 用户信息更新轮数（该用户发送多少条消息后触发分析更新）
        self.user_update_rounds = um.get('update_rounds', 50)
        # 用户记忆独立后端类型：deepseek / aliyun（所有密钥独立配置，禁止混淆）
        self.user_llm_type = um.get('llm_type', 'deepseek')
        uds = um.get('deepseek', {})
        self.user_deepseek_api_key = uds.get('api_key', '')
        self.user_deepseek_base_url = uds.get('base_url', 'https://api.deepseek.com/v1')
        self.user_deepseek_model = uds.get('model', 'deepseek-chat')
        ual = um.get('aliyun', {})
        self.user_aliyun_api_key = ual.get('api_key', '')
        self.user_aliyun_base_url = ual.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.user_aliyun_model = ual.get('model', 'qwen-plus')

        ugm = um.get('gemini', {})
        self.user_gemini_api_key = ugm.get('api_key', '')
        self.user_gemini_base_url = ugm.get('base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/')
        self.user_gemini_model = ugm.get('model', 'gemini-3.6-flash')
        # 用户记忆默认参数：temperature 0.7，思考强度高
        self.user_temperature = um.get('temperature', 0.7)
        self.user_enable_thinking = True
        self.user_max_tokens = um.get('max_tokens', 2048)
