/**
 * 精简卡片 + 高级设置
 *
 * 精简：Config.SIMPLE[卡片id] = 该卡点开只保留的配置项，其余裁掉（Modal.show 后处理）。
 * 高级设置：左侧分类 → 中间**原地渲染原面板**（把 Modal.show 重定向到中间区，
 *          面板自身的绑定/保存逻辑照旧可用，不另写一套）；另含「原始配置」全量编辑器。
 */
(function () {
    if (typeof Config === 'undefined' || typeof Modal === 'undefined') return;

    function T(s, vars) {
        if (typeof Config._t === 'function') return Config._t(s, vars);
        if (typeof window._t === 'function') return window._t(s, vars);
        return s;
    }

    // ==================== 1. 卡片精简白名单 ====================
    Config.SIMPLE = {
        'active_browse': ['llm_active.vision.base_url', 'llm_active.vision.gemini.base_url', 'llm_active.vision.gemini.model', 'llm_active.vision.llm_type', 'llm_active.vision.model', 'llm_active.web_browse.allow_topics', 'llm_active.web_browse.cache_dir', 'llm_active.web_browse.collect_dir', 'llm_active.web_browse.enabled', 'llm_active.web_browse.forbid_abstract', 'llm_active.web_browse.strictness'],
        'add_backlog': ['add_backlog.enabled', 'add_backlog.qq_enabled'],
        // 'basic' 不进白名单：它的面板是页签结构（礼物 / API / 端口），
        // 精简会删掉页签内容，导致"卡片点开是空的、高级设置点开却正常"。
        'catbrain_abstract': ['catbrain.abstract_mem.aliyun.base_url', 'catbrain.abstract_mem.aliyun.model', 'catbrain.abstract_mem.deepseek.base_url', 'catbrain.abstract_mem.deepseek.model', 'catbrain.abstract_mem.gemini.base_url', 'catbrain.abstract_mem.gemini.model', 'catbrain.abstract_mem.llm_type'],
        'catbrain_ltmem': ['catbrain.long_term_mem.inject_recent'],
        'catbrain_rulesbreak': ['rulebreak.deepseek.base_url', 'rulebreak.deepseek.model', 'rulebreak.enabled_msg', 'rulebreak.enabled_qq'],
        'catbrain_usermem': ['catbrain.user_memory.aliyun.base_url', 'catbrain.user_memory.aliyun.model', 'catbrain.user_memory.deepseek.base_url', 'catbrain.user_memory.deepseek.model', 'catbrain.user_memory.gemini.base_url', 'catbrain.user_memory.gemini.model', 'catbrain.user_memory.llm_type'],
        'catbrain_values': ['catbrain.cat_values.aliyun.base_url', 'catbrain.cat_values.aliyun.model', 'catbrain.cat_values.deepseek.base_url', 'catbrain.cat_values.deepseek.model', 'catbrain.cat_values.gemini.base_url', 'catbrain.cat_values.gemini.model', 'catbrain.cat_values.llm_type', 'catbrain.cat_values.second_review.aliyun.base_url', 'catbrain.cat_values.second_review.aliyun.model', 'catbrain.cat_values.second_review.deepseek.base_url', 'catbrain.cat_values.second_review.deepseek.model', 'catbrain.cat_values.second_review.enabled', 'catbrain.cat_values.second_review.gemini.base_url', 'catbrain.cat_values.second_review.gemini.model', 'catbrain.cat_values.second_review.llm_type'],
        'character': ['character_card.card_file', 'character_card.select'],
        'danmaku': ['danmaku.active_send.enabled', 'danmaku.blivedm.enabled', 'danmaku.blivedm.room_id', 'danmaku.gift_thanks_enabled', 'danmaku.ltmem_enabled', 'danmaku.multi_danmaku_strategy', 'danmaku.read_aloud_enabled', 'danmaku.read_aloud_mode', 'danmaku.sc_llm_reply_enabled'],
        'db_prefill': ['database.match.know_keywords', 'database.match.neg_keywords', 'database.match.search_keywords'],
        'db_search': ['database.search.aliyun.base_url', 'database.search.aliyun.model', 'database.search.deepseek.base_url', 'database.search.deepseek.model', 'database.search.gemini.base_url', 'database.search.gemini.model', 'database.search.llm_type', 'database.search.sites.3dmgame.base_url', 'database.search.sites.3dmgame.description', 'database.search.sites.3dmgame.enabled', 'database.search.sites.3dmgame.label', 'database.search.sites.3dmgame.search_url', 'database.search.sites.3dmgame.strategy', 'database.search.sites.baidu.base_url', 'database.search.sites.baidu.description', 'database.search.sites.baidu.enabled', 'database.search.sites.baidu.label', 'database.search.sites.baidu.search_url', 'database.search.sites.baidu.strategy', 'database.search.sites.mcmod.base_url', 'database.search.sites.mcmod.description', 'database.search.sites.mcmod.enabled', 'database.search.sites.mcmod.label', 'database.search.sites.mcmod.search_url', 'database.search.sites.mcmod.strategy', 'database.search.sites.moegirl.base_url', 'database.search.sites.moegirl.description', 'database.search.sites.moegirl.enabled', 'database.search.sites.moegirl.label', 'database.search.sites.moegirl.search_url', 'database.search.sites.moegirl.strategy'],
        'db_store': ['database.store.db_dir', 'database.store.embedding.aliyun.base_url', 'database.store.embedding.aliyun.model', 'database.store.embedding.dimension', 'database.store.embedding.provider', 'database.store.embedding.siliconflow.base_url', 'database.store.embedding.siliconflow.model'],
        'desktopet': ['desktopet_emote.body_sway.enabled', 'desktopet_emote.body_sway.parameter', 'desktopet_emote.emotion_slots.angry_strong', 'desktopet_emote.emotion_slots.angry_weak', 'desktopet_emote.emotion_slots.approve_strong', 'desktopet_emote.emotion_slots.approve_weak', 'desktopet_emote.emotion_slots.blood_strong', 'desktopet_emote.emotion_slots.blood_weak', 'desktopet_emote.emotion_slots.blush_strong', 'desktopet_emote.emotion_slots.blush_weak', 'desktopet_emote.emotion_slots.call_strong', 'desktopet_emote.emotion_slots.call_weak', 'desktopet_emote.emotion_slots.happy_strong', 'desktopet_emote.emotion_slots.happy_weak', 'desktopet_emote.emotion_slots.love_strong', 'desktopet_emote.emotion_slots.love_weak', 'desktopet_emote.emotion_slots.sad_strong', 'desktopet_emote.emotion_slots.sad_weak', 'desktopet_emote.emotion_slots.sweat_strong', 'desktopet_emote.emotion_slots.sweat_weak', 'desktopet_emote.emotion_slots.wordless_strong', 'desktopet_emote.emotion_slots.wordless_weak', 'desktopet_emote.mouth_sync.enabled', 'desktopet_emote.mouth_sync.parameter', 'desktopet_emote.switch', 'desktopet_emote.vtuber_authenticationToken', 'desktopet_emote.vtuber_pluginDeveloper', 'desktopet_emote.vtuber_pluginName', 'desktopet_emote.vtuber_websocket'],
        'flux_painter': ['flux_painter.adult_mode', 'flux_painter.aliyun.base_url', 'flux_painter.aliyun.model', 'flux_painter.artist_sources', 'flux_painter.backup_dir', 'flux_painter.canvas_sizes', 'flux_painter.comfy.artist_data', 'flux_painter.comfy.comfy_node_dir', 'flux_painter.comfy.engine_window', 'flux_painter.comfy.host', 'flux_painter.comfy.internal_main', 'flux_painter.comfy.internal_python', 'flux_painter.comfy.mode', 'flux_painter.comfy.output_dir', 'flux_painter.comfy.port', 'flux_painter.comfy.prompt_reference_dir', 'flux_painter.comfy.workflow_file', 'flux_painter.deepseek.base_url', 'flux_painter.deepseek.model', 'flux_painter.enabled', 'flux_painter.llm_type', 'flux_painter.lora_chain', 'flux_painter.memory_enabled', 'flux_painter.memory_type', 'flux_painter.moegirl_lookup', 'flux_painter.nsfw_check.enabled', 'flux_painter.nsfw_check.fail_action', 'flux_painter.nsfw_check.mode', 'flux_painter.nsfw_check.model_path', 'flux_painter.nsfw_check.model_url', 'flux_painter.pro.allow_custom_nodes', 'flux_painter.pro.detailers.eye.detector', 'flux_painter.pro.detailers.eye.enabled', 'flux_painter.pro.detailers.eye.force_inpaint', 'flux_painter.pro.detailers.eye.noise_mask', 'flux_painter.pro.detailers.face.detector', 'flux_painter.pro.detailers.face.enabled', 'flux_painter.pro.detailers.face.force_inpaint', 'flux_painter.pro.detailers.face.noise_mask', 'flux_painter.pro.detailers.hand.detector', 'flux_painter.pro.detailers.hand.enabled', 'flux_painter.pro.detailers.hand.force_inpaint', 'flux_painter.pro.detailers.hand.noise_mask', 'flux_painter.pro.enabled', 'flux_painter.pro.hires.enabled', 'flux_painter.pro.hires.resize', 'flux_painter.pro.hires.upscale_model', 'flux_painter.pro.pos_hand', 'flux_painter.pro.sam.sam_detection_hint', 'flux_painter.pro.sam.sam_mask_hint_use_negative', 'flux_painter.pro.sam_model', 'flux_painter.pro.usdu.enabled', 'flux_painter.pro.usdu.force_uniform_tiles', 'flux_painter.pro.usdu.mode_type', 'flux_painter.pro.usdu.sampler', 'flux_painter.pro.usdu.scheduler', 'flux_painter.pro.usdu.seam_fix_mode', 'flux_painter.pro.usdu.tiled_decode', 'flux_painter.progress_detail', 'flux_painter.quality_mode', 'flux_painter.quality_prefix', 'flux_painter.review_enabled', 'flux_painter.review_mode', 'flux_painter.sampler_name', 'flux_painter.sampler_scheduler', 'flux_painter.style_on_keywords', 'flux_painter.temp_dir', 'flux_painter.thinking_enabled', 'flux_painter.tts_source', 'flux_painter.unet_model', 'flux_painter.wait_timeout'],
        'llm_algorithm': ['llm.narration.enabled', 'llm.narration.score_log_enabled', 'llm.split_flag'],
        'llm_model': ['llm.aliyun.base_url', 'llm.aliyun.enable_thinking', 'llm.aliyun.model', 'llm.aliyun.stream', 'llm.deepseek.base_url', 'llm.deepseek.enable_thinking', 'llm.deepseek.model', 'llm.deepseek.stream', 'llm.gemini.base_url', 'llm.gemini.enable_thinking', 'llm.gemini.model', 'llm.gemini.stream', 'llm.local_llm_type'],
        'meowsinger_cover': ['meowsinger.cover.enabled', 'meowsinger.cover.f0_method', 'meowsinger.cover.intent', 'meowsinger.cover.learn_mode', 'meowsinger.cover.learn_trigger', 'meowsinger.cover.learn_users', 'meowsinger.cover.prefix', 'meowsinger.cover.resample_sr', 'meowsinger.cover.rvc_index', 'meowsinger.cover.rvc_model', 'meowsinger.cover.rvc_url', 'meowsinger.cover.trigger_mode'],
        'meowsinger_model': ['meowsinger.aliyun.base_url', 'meowsinger.aliyun.model', 'meowsinger.deepseek.base_url', 'meowsinger.deepseek.model', 'meowsinger.enabled', 'meowsinger.gemini.base_url', 'meowsinger.gemini.model', 'meowsinger.llm_type', 'meowsinger.prompt.reply', 'meowsinger.stop.keywords'],
        'meowsinger_sentiment': ['meowsinger.sentiment.enabled', 'meowsinger.sentiment.word_count'],
        'meowsinger_song': ['meowsinger.song.enabled', 'meowsinger.song.intent', 'meowsinger.song.netease_url', 'meowsinger.song.prefix', 'meowsinger.song.trigger_mode'],
        'meowsongs': ['meowsongs.enabled', 'meowsongs.pass_the_baton.enabled', 'meowsongs.pass_the_baton.feeling_prompt', 'meowsongs.pass_the_baton.match_threshold', 'meowsongs.pass_the_baton.min_margin'],
        'meowvision': ['meowvision.base_url', 'meowvision.cache_dir', 'meowvision.gemini.base_url', 'meowvision.gemini.model', 'meowvision.llm_type', 'meowvision.model', 'meowvision.watching.enabled', 'meowvision.watching.max_duration'],
        'minecraft': ['minecraft.enabled', 'minecraft.encoding', 'minecraft.filter_players', 'minecraft.ignore_self_messages', 'minecraft.include_player_name_in_prompt', 'minecraft.log_path', 'minecraft.use_player_name', 'minecraft.username_fixed'],
        'napcat_account': ['napcat.debug_event_dump', 'napcat.emote_dir', 'napcat.enabled', 'napcat.ltmem_enabled', 'napcat.poke_enabled', 'napcat.self_nickname', 'napcat.short_mem_enabled', 'napcat.ws_url'],
        'napcat_group': ['napcat.group_active_enabled', 'napcat.group_blacklist', 'napcat.group_bots.幻梦', 'napcat.group_followup.enabled', 'napcat.group_followup.max_passes', 'napcat.group_followup.max_rounds', 'napcat.group_keyword_reply.case_sensitive', 'napcat.group_keyword_reply.enabled', 'napcat.group_keyword_reply.keywords', 'napcat.group_keyword_reply.reply_with_at', 'napcat.group_merge.enabled', 'napcat.group_merge.sliding', 'napcat.group_reply_enabled', 'napcat.group_reply_word_count', 'napcat.group_reply_reject_ratio', 'napcat.group_reply_reject_rounds', 'napcat.group_reply_punct_check.enabled', 'napcat.group_reply_punct_check.max_punct', 'napcat.group_reply_quote.enabled', 'napcat.group_reply_quote.quote_back', 'napcat.group_reply_pace.enabled', 'napcat.group_reply_pace.ms_per_char', 'napcat.group_reply_pace.jitter', 'napcat.group_reply_pace.sentence_extra', 'napcat.group_reply_pace.max_seconds', 'napcat.group_reply_pace.first_delay'],
        'napcat_private': ['napcat.emote_enabled', 'napcat.private_reply_enabled', 'napcat.thinking_level', 'napcat.reply_word_count', 'napcat.reply_reject_ratio', 'napcat.reply_reject_rounds', 'napcat.reply_punct_check.enabled', 'napcat.reply_punct_check.max_punct', 'napcat.reply_quote.enabled', 'napcat.reply_quote.quote_back', 'napcat.reply_pace.enabled', 'napcat.reply_pace.ms_per_char', 'napcat.reply_pace.jitter', 'napcat.reply_pace.sentence_extra', 'napcat.reply_pace.max_seconds', 'napcat.reply_pace.first_delay'],
        'napcat_send': ['napcat.active_sender.enabled'],
        'news': ['news.enabled'],
        'sensevoice_audio': ['audio.prefer_native_rate', 'audio.resample_converter', 'audio.sources.inject.allow_interrupt', 'audio.sources.inject.enabled', 'audio.sources.inject.speaker_verify', 'audio.sources.inject.type', 'audio.sources.inject.username', 'audio.sources.loopback.allow_interrupt', 'audio.sources.loopback.enabled', 'audio.sources.loopback.speaker_verify', 'audio.sources.loopback.type', 'audio.sources.loopback.username', 'audio.sources.mic.allow_interrupt', 'audio.sources.mic.enabled', 'audio.sources.mic.speaker_verify', 'audio.sources.mic.type'],
        'sensevoice_config': ['sensevoice.enabled', 'sensevoice.hotwords', 'sensevoice.itn', 'sensevoice.language', 'sensevoice.mode', 'sensevoice.replace_rules.喵呜', 'sensevoice.replace_rules.异环', 'sensevoice.server_url', 'sensevoice.target_speakers'],
        'sensevoice_mic': ['silence.enabled', 'silence.mute_phrases', 'silence.wake_phrases'],
        'toolbox': ['toolbox.aliyun.base_url', 'toolbox.aliyun.model', 'toolbox.deepseek.base_url', 'toolbox.deepseek.model', 'toolbox.excuse_enabled', 'toolbox.gemini.base_url', 'toolbox.gemini.model', 'toolbox.llm_type'],
        'tts_config': ['tts.gpt-sovits.emotion_audio.angry', 'tts.gpt-sovits.emotion_audio.approve', 'tts.gpt-sovits.emotion_audio.blood', 'tts.gpt-sovits.emotion_audio.blush', 'tts.gpt-sovits.emotion_audio.call', 'tts.gpt-sovits.emotion_audio.happy', 'tts.gpt-sovits.emotion_audio.love', 'tts.gpt-sovits.emotion_audio.sad', 'tts.gpt-sovits.emotion_audio.sweat', 'tts.gpt-sovits.emotion_audio.wordless', 'tts.gpt-sovits.gpt_sovits_url', 'tts.gpt-sovits.lang_judge_enabled', 'tts.gpt-sovits.media_type', 'tts.gpt-sovits.pause_enabled', 'tts.gpt-sovits.pause_sources', 'tts.gpt-sovits.phone_local_play', 'tts.gpt-sovits.streaming_mode', 'tts.gpt-sovits.text_lang', 'tts.interrupt.key', 'tts.interrupt.mode', 'tts.output_dir', 'tts.select'],
        'turtle_soup': ['turtle_soup.bank_dir', 'turtle_soup.cache_dir', 'turtle_soup.enabled', 'turtle_soup.qq_enabled'],
        'vts_config': ['emote.body_sway.enabled', 'emote.body_sway.parameter', 'emote.emotion_slots.angry_strong', 'emote.emotion_slots.angry_weak', 'emote.emotion_slots.approve_strong', 'emote.emotion_slots.approve_weak', 'emote.emotion_slots.blood_strong', 'emote.emotion_slots.blood_weak', 'emote.emotion_slots.blush_strong', 'emote.emotion_slots.blush_weak', 'emote.emotion_slots.call_strong', 'emote.emotion_slots.call_weak', 'emote.emotion_slots.happy_strong', 'emote.emotion_slots.happy_weak', 'emote.emotion_slots.love_strong', 'emote.emotion_slots.love_weak', 'emote.emotion_slots.sad_strong', 'emote.emotion_slots.sad_weak', 'emote.emotion_slots.sweat_strong', 'emote.emotion_slots.sweat_weak', 'emote.emotion_slots.wordless_strong', 'emote.emotion_slots.wordless_weak', 'emote.mouth_sync.enabled', 'emote.mouth_sync.parameter', 'emote.switch', 'emote.vtuber_authenticationToken', 'emote.vtuber_pluginDeveloper', 'emote.vtuber_pluginName', 'emote.vtuber_websocket'],
        'weather': ['weather.enabled']
    };

    Config.filterSimple = function (root, cardId) {
        const keep = Config.SIMPLE[cardId];
        if (!keep || !root) return;
        root.querySelectorAll('[data-path]').forEach(function (el) {
            // 页签（礼物 / API / 端口）是卡片的详细部分，不参与精简：
            // 否则「基本」卡的 API 页签会被这条规则整片删掉，面板看起来是空的。
            if (el.closest('[data-tab-content]')) return;
            const p = el.dataset.path || '';
            const hit = keep.some(function (k) { return p === k || p.indexOf(k + '.') === 0; });
            if (!hit) {
                const g = el.closest('.form-group');
                if (g) g.remove();
            }
        });
        root.querySelectorAll('.form-section').forEach(function (s) {
            if (s.closest('[data-tab-content]')) return;
            const n = s.nextElementSibling;
            if (!n || (n.classList && n.classList.contains('form-section'))) s.remove();
        });
    };

    // ==================== 2. 分类表（id 与卡片 id 对齐，kind 决定走哪条打开逻辑） ====================
    const GROUPS = [
        { t: '基础', items: [
            { id: 'identity_users', t: '用户 ID', kind: 'render', build: function () { return Config.identityUsers(); } },
            { id: 'basic', t: '基础设置', kind: 'planet' },
            { id: 'api_platforms', t: 'API 平台', kind: 'render', build: function () { return Config.apiPlatforms(); } },
            { id: 'character', t: '角色卡', kind: 'planet' },
            { id: 'subtitle', t: '字幕', kind: 'planet' },
            { id: 'calendar', t: '待办', kind: 'planet' }
        ] },
        { t: '语音', items: [
            { id: 'sensevoice_config', t: '语音识别', kind: 'planet' },
            { id: 'sensevoice_mic', t: '闭麦', kind: 'planet' },
            { id: 'sensevoice_audio', t: '音频采集', kind: 'planet' },
            { id: 'tts_config', t: 'TTS 配置', kind: 'planet' },
            { id: 'tts_model', t: 'TTS 模型', kind: 'planet' },
            { id: 'tts_params', t: 'TTS 参数', kind: 'planet' },
            { id: 'tts_pause', t: 'TTS 间隔', kind: 'planet' }
        ] },
        { t: '大脑', items: [
            { id: 'llm_model', t: 'LLM 模型', kind: 'planet' },
            { id: 'llm_prompt', t: 'LLM 提示词', kind: 'planet' },
            { id: 'llm_algorithm', t: 'LLM 算法', kind: 'planet' },
            { id: 'active_config', t: '主动回复', kind: 'planet' },
            { id: 'active_browse', t: 'B站浏览', kind: 'planet' },
            { id: 'ltmem', t: '长期记忆', kind: 'planet' },
            { id: 'abstract', t: '记忆摘要', kind: 'planet' },
            { id: 'rulesbreak', t: '原则词', kind: 'planet' },
            { id: 'values', t: '价值观', kind: 'planet' },
            { id: 'usermem', t: '用户记忆', kind: 'planet' },
            { id: 'db_search', t: '搜索学习', kind: 'planet' },
            { id: 'db_store', t: '知识存储', kind: 'planet' },
            { id: 'db_source', t: '数据来源', kind: 'planet' },
            { id: 'db_prefill', t: '知识预填', kind: 'planet' }
        ] },
        { t: '形象', items: [
            { id: 'vts_config', t: 'VTS 配置', kind: 'planet' },
            { id: 'vts_emotion', t: 'VTS 表情', kind: 'planet' },
            { id: 'desktopet', t: '桌宠', kind: 'planet' },
            { id: 'vts_params', t: 'VTS 参数', kind: 'planet' }
        ] },
        { t: '娱乐', items: [
            { id: 'meowsinger_model', t: '歌曲模型', kind: 'planet' },
            { id: 'meowsinger_song', t: '点歌', kind: 'planet' },
            { id: 'meowsinger_cover', t: '翻唱', kind: 'planet' },
            { id: 'meowsinger_sentiment', t: '感想', kind: 'planet' },
            { id: 'danmaku', t: '弹幕', kind: 'toolbox' }
        ] },
        { t: '工具箱', items: [
            { id: 'center', t: '父级模型', kind: 'toolbox' },
            { id: 'minecraft', t: 'Minecraft', kind: 'toolbox' },
            { id: 'meowvision', t: '视觉', kind: 'toolbox' },
            { id: 'napcat_account', t: 'NapCat 角色名', kind: 'toolbox' },
            { id: 'napcat_private', t: 'NapCat 私聊', kind: 'toolbox' },
            { id: 'napcat_group', t: 'NapCat 群聊', kind: 'toolbox' },
            { id: 'napcat_send', t: 'NapCat 主动发送', kind: 'toolbox' },
            { id: 'weather', t: '天气', kind: 'toolbox' },
            { id: 'news', t: '新闻', kind: 'toolbox' },
            { id: 'add_backlog', t: '提醒', kind: 'toolbox' },
            { id: 'meowsongs', t: '哼唱', kind: 'toolbox' },
            { id: 'turtle_soup', t: '海龟汤', kind: 'toolbox' },
            { id: 'flux_painter_service', t: '绘画·服务', kind: 'toolbox' },
            { id: 'flux_painter_model', t: '绘画·模型', kind: 'toolbox' },
            { id: 'flux_painter_prompt', t: '绘画·提示词', kind: 'toolbox' },
            { id: 'flux_painter_workflow', t: '绘画·工作流', kind: 'toolbox' },
            { id: 'plugins', t: '插件', kind: 'plugins' }
        ] },
        { t: '全量', items: [
            { id: 'raw_config', t: '原始配置（全部键）', kind: 'raw' }
        ] }
    ];

    // 原始配置中文标签（仅顶层，缺省显示键名）
    const LABELS = {
        AiName: 'AI 名称', app: '应用', audio: '音频采集', catbrain: 'CatBrain', character_card: '角色卡',
        danmaku: '弹幕', database: '数据库', desktopet_emote: '桌宠', emote: 'VTS', flux_painter: '绘画',
        llm: 'LLM', llm_active: '主动回复', meowsinger: '歌曲', meowsongs: '哼唱', meowvision: '视觉',
        minecraft: 'Minecraft', napcat: 'NapCat', news: '新闻', rulebreak: '原则词', sensevoice: '语音识别',
        silence: '闭麦', toolbox: '工具箱', tts: 'TTS', turtle_soup: '海龟汤', weather: '天气',
        add_backlog: '提醒', rewards: '奖励', plugins: '插件'
    };

    // ==================== 3. 高级设置 ====================
    const Adv = {
        built: false,
        hosting: false,
        bodyEl: null,
        onSave: null,
        activeId: null,

        flatten: function () {
            const out = [];
            GROUPS.forEach(function (g) { g.items.forEach(function (it) { out.push(Object.assign({ group: g.t }, it)); }); });
            return out;
        },

        ensure: function () {
            if (this.built) return;
            const ov = document.createElement('div');
            ov.className = 'adv-overlay';
            ov.id = 'advOverlay';
            ov.innerHTML =
                '<div class="adv-panel">' +
                    '<div class="adv-side">' +
                        '<div class="adv-side-title">高级设置</div>' +
                        '<div class="adv-side-list" id="advSideList"></div>' +
                    '</div>' +
                    '<div class="adv-main">' +
                        '<div class="adv-head"><h3 id="advTitle">高级设置</h3><button class="adv-close" id="advClose">&times;</button></div>' +
                        '<div class="adv-body" id="advBody"></div>' +
                        '<div class="adv-foot"><span class="adv-note" id="advNote"></span><button class="btn btn-primary" id="advSave">保存</button></div>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(ov);
            this.bodyEl = ov.querySelector('#advBody');
            const sideTitle = ov.querySelector('.adv-side-title');
            if (sideTitle) sideTitle.textContent = T('高级设置');

            const list = ov.querySelector('#advSideList');
            GROUPS.forEach(function (g) {
                const h = document.createElement('div');
                h.className = 'adv-group';
                h.textContent = T(g.t);
                list.appendChild(h);
                g.items.forEach(function (it) {
                    const a = document.createElement('div');
                    a.className = 'adv-item';
                    a.textContent = T(it.t);
                    a.dataset.id = it.id;
                    a.addEventListener('click', function () { Adv.open(it.id); });
                    list.appendChild(a);
                });
            });

            ov.querySelector('#advClose').addEventListener('click', function () { Adv.close(); });
            ov.addEventListener('click', function (e) { if (e.target === ov) Adv.close(); });
            ov.querySelector('#advSave').addEventListener('click', function () { Adv.save(); });
            this.built = true;
        },

        find: function (id) {
            const all = this.flatten();
            for (let i = 0; i < all.length; i++) if (all[i].id === id) return all[i];
            return null;
        },

        mark: function (id) {
            this.activeId = id;
            document.querySelectorAll('#advSideList .adv-item').forEach(function (a) {
                a.classList.toggle('active', a.dataset.id === id);
            });
        },

        open: function (id) {
            this.ensure();
            document.getElementById('advOverlay').classList.add('show');
            document.body.style.overflow = 'hidden';
            const item = (id && this.find(id)) || this.flatten()[0];
            this.mark(item.id);
            document.getElementById('advTitle').textContent = T(item.t);
            const note = document.getElementById('advNote');
            note.textContent = '';
            clearTimeout(this._guard);

            if (item.kind === 'raw') {
                this.unhost();
                this.onSave = null;
                this.renderRaw();
                note.textContent = T('原始配置：直接编辑全部键（数组/对象用 JSON）');
                return;
            }
            if (item.kind === 'render') {
                this.unhost();
                this.onSave = null;
                this.bodyEl.innerHTML = item.build ? item.build() : '';
                Modal.initAutoGrow(this.bodyEl);
                this.binds();
                note.textContent = T('整块配置，可直接编辑并保存');
                return;
            }
            if (item.kind === 'plugins') {
                this.unhost();
                this.onSave = null;
                this.renderPlugins();
                note.textContent = T('选择一个插件，进入其配置');
                return;
            }

            this.host();
            this.onSave = null;
            this.bodyEl.innerHTML = '<div class="help-text">' + T('加载中…') + '</div>';
            const self = this;
            this._guard = setTimeout(function () { self.hosting = false; }, 6000);
            try {
                if (item.kind === 'toolbox') {
                    if (window.App && App.onToolboxPlanetClick) App.onToolboxPlanetClick(item.id);
                } else {
                    if (window.App && App.onPlanetClick) App.onPlanetClick(item.id);
                }
            } catch (e) {
                console.error('[Adv] open failed', item.id, e);
                this.hosting = false;
                this.bodyEl.innerHTML = '<div class="help-text">' + T('打开失败：') + (e && e.message ? e.message : e) + '</div>';
            }
        },

        openPlugin: function (pid) {
            this.ensure();
            this.host();
            this.onSave = null;
            document.getElementById('advTitle').textContent = T('插件') + ' · ' + pid;
            document.getElementById('advNote').textContent = '';
            this.bodyEl.innerHTML = '<div class="help-text">' + T('加载中…') + '</div>';
            const self = this;
            clearTimeout(this._guard);
            this._guard = setTimeout(function () { self.hosting = false; }, 6000);
            if (window.App && App.openPluginPanel) App.openPluginPanel(pid);
        },

        renderPlugins: function () {
            const list = (window.App && App.plugins) || [];
            let h = '<div class="form-section"><h4>' + T('插件') + '</h4></div>';
            if (!list.length) {
                h += '<div class="help-text">' + T('暂无插件') + '</div>';
            } else {
                list.forEach(function (p) {
                    h += '<div class="form-group"><button type="button" class="btn btn-secondary" data-plugin="'
                        + Adv.esc(p.id) + '">' + Adv.esc(p.title || p.id) + T(' · 配置') + '</button></div>';
                });
            }
            this.bodyEl.innerHTML = h;
            this.bodyEl.querySelectorAll('[data-plugin]').forEach(function (b) {
                b.addEventListener('click', function () { Adv.openPlugin(b.dataset.plugin); });
            });
        },

        binds: function () {
            try {
                if (App.bindTabs) App.bindTabs();
                if (App.bindSplitFlagEditor) App.bindSplitFlagEditor();
                if (App.bindWordTagEditor) App.bindWordTagEditor();
                if (App.bindDictEditors) App.bindDictEditors();
                if (App.bindTriggerMode) App.bindTriggerMode();
                if (App.bindSessdataVerify) App.bindSessdataVerify();
                if (App.bindBiliLogin) App.bindBiliLogin();
                if (App.bindVtsParamsQuery) App.bindVtsParamsQuery();
            } catch (e) { console.error('[Adv] bind failed', e); }
        },

        // 把 id=modalBody 让给中间区，令原面板的 collectValues()/绑定 照常工作
        host: function () {
            const real = document.getElementById('modalBody');
            if (real && real.id !== 'modalBody_stash') real.id = 'modalBody_stash';
            if (this.bodyEl) this.bodyEl.id = 'modalBody';
            this.hosting = true;
        },

        unhost: function () {
            if (this.bodyEl) this.bodyEl.id = 'advBody';
            const stashed = document.getElementById('modalBody_stash');
            if (stashed) stashed.id = 'modalBody';
            this.hosting = false;
        },

        _hostPanel: function (title, html, onSave) {
            clearTimeout(this._guard);
            this.hosting = false;
            document.getElementById('advTitle').textContent = T(title || '高级设置');
            if (this.bodyEl) {
                this.bodyEl.innerHTML = html;
                Modal.initAutoGrow(this.bodyEl);
            }
            this.onSave = (typeof onSave === 'function') ? onSave : null;
            const self = this;
            setTimeout(function () { self.binds(); }, 10);
        },

        // ---- 原始配置：整棵 config 树 ----
        renderRaw: function () {
            this.bodyEl.innerHTML = this.nodeHtml('', App.config, true);
            Modal.initAutoGrow(this.bodyEl);
        },

        nodeHtml: function (path, val, top) {
            const self = this;
            if (val === null || typeof val !== 'object') return this.leafHtml(path, val);
            if (Array.isArray(val)) return this.jsonHtml(path, val);
            const keys = Object.keys(val);
            if (!keys.length) return this.jsonHtml(path, val);
            let h = '';
            keys.forEach(function (k) {
                const p = path ? path + '.' + k : k;
                const v = val[k];
                if (v !== null && typeof v === 'object') {
                    const label = (top && LABELS[k]) ? T(LABELS[k]) + '（' + k + '）' : k;
                    h += '<div class="form-section"><h4>' + self.esc(label) + '</h4></div>';
                    h += self.nodeHtml(p, v, false);
                } else {
                    h += self.leafHtml(p, v);
                }
            });
            return h;
        },

        leafHtml: function (path, val) {
            const label = path;
            if (typeof val === 'boolean') {
                return '<div class="form-group"><div class="checkbox-group"><input type="checkbox" data-path="' + this.esc(label) + '"' + (val ? ' checked' : '') + '><label>' + this.esc(label) + '</label></div></div>';
            }
            if (typeof val === 'number') {
                return '<div class="form-group"><label>' + this.esc(label) + '</label><input type="number" step="any" data-path="' + this.esc(label) + '" value="' + val + '"></div>';
            }
            const s = (val === null || val === undefined) ? '' : String(val);
            if (s.indexOf('\n') >= 0 || s.length > 80) {
                return '<div class="form-group"><label>' + this.esc(label) + '</label><textarea class="auto-grow" rows="3" data-path="' + this.esc(label) + '">' + this.esc(s) + '</textarea></div>';
            }
            return '<div class="form-group"><label>' + this.esc(label) + '</label><input type="text" data-path="' + this.esc(label) + '" value="' + this.esc(s) + '"></div>';
        },

        jsonHtml: function (path, val) {
            const s = JSON.stringify(val, null, 2);
            return '<div class="form-group"><label>' + this.esc(path) + T('（JSON）') + '</label><textarea class="auto-grow" rows="6" data-json="1" data-path="' + this.esc(path) + '">' + this.esc(s) + '</textarea></div>';
        },

        esc: function (s) {
            return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        },

        close: function () {
            this.unhost();
            const ov = document.getElementById('advOverlay');
            if (ov) ov.classList.remove('show');
            if (!document.body.classList.contains('modal-open')) document.body.style.overflow = '';
        },

        // ---- 保存：面板自带 onSave 优先，否则通用收集 ----
        save: async function () {
            try {
                if (this.onSave) {
                    await this.onSave();
                    if (App.showToast) App.showToast(T('配置已保存（已热重载）'));
                    return;
                }
                const updates = [];
                const scope = this.bodyEl;
                scope.querySelectorAll('[data-path]').forEach(function (el) {
                    const path = el.dataset.path;
                    let value;
                    if (el.dataset.json) {
                        const t = el.value.trim();
                        try { value = t ? JSON.parse(t) : {}; } catch (e) { throw new Error(T('JSON 格式错误：') + path); }
                    } else if (el.type === 'checkbox') value = el.checked;
                    else if (el.type === 'number') { if (el.value === '') return; value = parseFloat(el.value); }
                    else value = el.value;
                    updates.push({ path: path, value: value });
                });
                Config.applyUpdates(updates, App.config);
                await API.saveConfig(App.config);
                if (App.showToast) App.showToast(T('配置已保存（已热重载）'));
            } catch (e) {
                if (App.showToast) App.showToast(T('保存失败: ') + (e && e.message ? e.message : e), true);
                else alert(T('保存失败: ') + (e && e.message ? e.message : e));
            }
        }
    };
    window.Adv = Adv;

    // ==================== 4. 接管 Modal.show（精简 + 重定向到高级设置） ====================
    const origShow = Modal.show;
    Modal.show = function (title, html, onSave, fromEl) {
        if (Adv.hosting) { Adv._hostPanel(title, html, onSave); return; }
        origShow.call(this, title, html, onSave, fromEl);
        const ov = document.getElementById('advOverlay');
        const fromAdv = ov && ov.classList.contains('show');
        const btn = document.getElementById('modalMore');
        if (fromAdv) { if (btn) btn.style.display = 'none'; return; }
        const src = Modal.source;
        const navId = (src && src.dataset) ? (src.dataset.id || null) : null;
        const cardId = (src && src.dataset) ? (src.dataset.card || navId) : null;
        if (cardId && Config.SIMPLE[cardId]) {
            Config.filterSimple(Modal.getBody(), cardId);
            if (btn) { btn.style.display = ''; btn.dataset.target = navId || cardId; }
        } else if (btn) {
            btn.style.display = 'none';
        }
    };

    // ==================== 5. 入口与按钮 ====================
    function addEntry() {
        const ls = document.getElementById('langSwitch');
        if (!ls || document.getElementById('advEntry')) return;
        const b = document.createElement('button');
        b.id = 'advEntry';
        b.type = 'button';
        b.className = 'adv-entry';
        b.textContent = T('高级设置');
        b.addEventListener('click', function () { Adv.open(); });
        ls.parentNode.insertBefore(b, ls.nextSibling);
    }

    function addMoreButton() {
        const footer = document.querySelector('#modalWindow .modal-footer');
        if (!footer || document.getElementById('modalMore')) return;
        const b = document.createElement('button');
        b.id = 'modalMore';
        b.type = 'button';
        b.className = 'btn btn-secondary';
        b.textContent = T('更多设置 →');
        b.style.display = 'none';
        b.addEventListener('click', function () {
            const id = b.dataset.target;
            Modal.hide();
            Adv.open(id);
        });
        footer.insertBefore(b, footer.firstChild);
    }

    document.addEventListener('DOMContentLoaded', function () {
        addEntry();
        addMoreButton();
    });
})();
