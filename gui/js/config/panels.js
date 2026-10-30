/**
 * 面板声明（唯一真值）
 *
 * 新增面板：在下面加一行 registerPanel / renderPanel / openPanel。
 * 不再改 app/core.js 的 if/else，也不在 advanced.js 里重复一份列表。
 */
(function () {
    const P = window.ConfigPanels;
    if (!P) throw new Error('config/panels.js requires config/registry.js');

    const panel = (id, title, group, def) => P.register(Object.assign({ id, title, group }, def));
    const render = (fn) => ({ render: fn });
    const open = (fn) => ({ open: fn });

    // ==================== 基础 ====================
    panel('basic', '基本设置', '基础', open(() => App.openBasicPanel()));
    panel('character', '角色卡', '基础', open(() => App.openCharacterPanel()));
    panel('subtitle', '字幕设置', '基础', render(() => Config.subtitle()));
    panel('calendar', '待办', '基础', open(() => App.openCalendarPanel()));
    panel('catpaws', '手机操作', '基础', { advanced: false, open: () => App.openCatpawsPanel() });

    // ==================== 语音 ====================
    panel('sensevoice', 'SenseVoice', '语音', { advanced: false, open: () => App.openSensevoicePanel() });
    panel('sensevoice_config', '语音识别', '语音', open(() => App.openSensevoicePanel()));
    panel('sensevoice_mic', '闭麦', '语音', open(() => App.openSilencePanel()));
    panel('sensevoice_audio', '音频采集', '语音', open(() => App.openAudioPanel()));
    panel('tts', 'TTS', '语音', { advanced: false, open: () => App.openTtsPanel() });
    panel('tts_config', 'TTS 配置', '语音', { fields: [
        { type: 'section', label: '流式开关' },
        { type: 'select', path: 'tts.gpt-sovits.streaming_mode', label: '流式模式', default: '2',
          options: [{ value: '0', label: '关闭（整段合成）' }, { value: '2', label: '智能流式（静音点切分）' }, { value: '3', label: '定长流式（响应更快）' }],
          help: '2=按静音点切分听感连贯，3=定长切分响应更快' },
        { type: 'select', path: 'tts.gpt-sovits.media_type', label: '媒体类型', default: 'raw',
          options: [{ value: 'raw', label: 'raw（裸 PCM）' }, { value: 'wav', label: 'wav（带 wav 头）' }],
          help: '流式推荐 raw，避免每块 wav 头解析' },
        { type: 'number', path: 'tts.gpt-sovits.fragment_interval', label: '段尾静音(秒)',
          default: 0, min: 0, max: 2, step: 0.1, help: '流式下必须为 0，否则段尾会有静音' },
        { type: 'select', path: 'tts.gpt-sovits.text_lang', label: '合成文本语言', default: 'zh',
          options: [{ value: 'zh', label: '中文 zh（最稳，可读短英文词）' }, { value: 'auto', label: '自动 auto（中英混合，可能误判成日文）' }, { value: 'en', label: '英文 en' }],
          help: '中文为主建议 zh，避免 auto 误判成日语出现伪日文' },
        { type: 'check', path: 'tts.gpt-sovits.lang_judge_enabled', label: '整段语言自动切换', default: true,
          help: '仅当整段是英文/日文时自动切换语言，其余仍用上方默认语言' },
        { type: 'section', label: '打断' },
        { type: 'select', path: 'tts.interrupt.mode', label: '打断模式', default: 'pipeline',
          options: [{ value: 'pipeline', label: 'pipeline（说话打断）' }, { value: 'keyboard', label: 'keyboard（按键打断）' }, { value: 'off', label: 'off（关闭）' }] },
        { type: 'text', path: 'tts.interrupt.key', label: '打断按键', default: 'f8' },
        { type: 'number', path: 'tts.interrupt.poll_interval', label: '打断轮询间隔(秒)', default: 0.1, min: 0.01, max: 1, step: 0.01 },
        { type: 'section', label: '服务与引擎' },
        { type: 'select', path: 'tts.select', label: '语音合成引擎', default: 'gpt-sovits',
          options: [{ value: 'gpt-sovits', label: 'GPT-SoVITS' }] },
        { type: 'text', path: 'tts.gpt-sovits.gpt_sovits_url', label: 'GPT-SoVITS 服务地址', default: 'http://127.0.0.1:9880' },
        { type: 'text', path: 'tts.output_dir', label: '输出目录', default: './output' },
    ] });
    panel('tts_model', 'TTS 模型', '语音', open(() => App.openTtsModelPanel()));
    panel('tts_params', 'TTS 参数', '语音', {
        load: () => API.getTtsConfig(),
        fields: [
            { type: 'custom', render: (panel) => Config._section('合成参数 (tts_infer.yaml)') + Config.ttsModelFields(panel.data) },
            { type: 'section', label: '流式参数 (config.yml)' },
            { type: 'number', path: 'tts.gpt-sovits.min_chunk_length', label: '语义 token 块长度', default: 12, min: 1, max: 50, step: 1, help: '越小首包越快，越大越流畅' },
            { type: 'number', path: 'tts.gpt-sovits.overlap_length', label: '块间重叠 token 数', default: 2, min: 0, max: 10, step: 1, help: '越大块间衔接越自然' },
            { type: 'number', path: 'tts.gpt-sovits.sample_rate', label: '输出采样率', default: 32000, min: 8000, max: 48000, step: 1000, help: 'v2Pro 流式输出固定 32000' },
            { type: 'section', label: '播放与合成 (config.yml)' },
            { type: 'number', path: 'tts.volume', label: '音量', default: 1.0, min: 0, max: 2, step: 0.1 },
            { type: 'number', path: 'tts.synth_workers', label: '合成线程数', default: 2, min: 1, max: 8, step: 1 },
            { type: 'number', path: 'tts.seg_min_len', label: '分段最小长度(字)', default: 24, min: 0, max: 200, step: 1,
              help: '整段朗读按标点切分的下限；不足该字数即使遇到标点也不切，0=遇标点就切' },
        ],
        save: async () => {
            const updates = Config.collectValues();
            Config.applyUpdates(updates, App.config);
            await API.saveConfig(App.config);
            await API.saveTtsConfig(Config.collectTtsModel());
            App.showToast('参数配置已保存');
        },
    });
    panel('tts_pause', 'TTS 间隔', '语音', { fields: [
        { type: 'section', label: '段间随机停顿（每播完一段后停顿，可被说话/抢占中断）' },
        { type: 'check', path: 'tts.gpt-sovits.pause_enabled', label: '启用段间停顿', default: true,
          help: '关闭后每段连续播放，无额外停顿' },
        { type: 'number', path: 'tts.gpt-sovits.pause_min_ms', label: '最小停顿(毫秒)', default: 500, min: 0, max: 5000, step: 50, help: '建议 500（0.5 秒）' },
        { type: 'number', path: 'tts.gpt-sovits.pause_max_ms', label: '最大停顿(毫秒)', default: 1000, min: 0, max: 5000, step: 50,
          help: '建议 1000（1 秒）；实际在最小与最大之间随机' },
        { type: 'list', path: 'tts.gpt-sovits.pause_sources', label: '适用来源(留空=全部)', default: [],
          help: '留空表示所有语音来源都停顿；填写来源名如 llm、toolbox_news（逗号分隔）则仅这些来源停顿' },
    ], save: async () => {
        const updates = Config.collectValues();
        Config.applyUpdates(updates, App.config);
        const gs = App.config && App.config.tts && App.config.tts['gpt-sovits'];
        if (gs && typeof gs.pause_sources === 'string') {
            gs.pause_sources = gs.pause_sources.split(/[,，\n]/).map(s => s.trim()).filter(Boolean);
        }
        await API.saveConfig(App.config);
        App.showToast('配置已保存');
    } });

    // ==================== 大脑 ====================
    panel('llm_model', 'LLM 模型', '大脑', { fields: [
        { type: 'custom', render: () => {
            const type = Config._val('llm.local_llm_type', 'deepseek');
            return `<div class="form-group"><label>${Config._t('LLM类型')}</label>
                <select data-path="llm.local_llm_type" onchange="Config.toggleMeowLLMLink(this)">
                    <option value="deepseek"${type === 'deepseek' ? ' selected' : ''}>DeepSeek</option>
                    <option value="aliyun"${type === 'aliyun' ? ' selected' : ''}>${Config._t('阿里云')}</option>
                    <option value="gemini"${type === 'gemini' ? ' selected' : ''}>Gemini</option>
                    <option value="meowllm"${type === 'meowllm' ? ' selected' : ''}>MeowLLM</option>
                </select>${Config._mllLink(type === 'meowllm')}</div>`;
        } },
        { type: 'tabs', id: 'llm_model', active: () => Config._val('llm.local_llm_type', 'deepseek'), tabs: [
            { id: 'deepseek', label: 'DeepSeek', fields: [
                { type: 'text', path: 'llm.deepseek.model', label: '模型', default: 'deepseek-chat' },
                { type: 'number', path: 'llm.deepseek.temperature', label: '温度', default: 0.7, min: 0, max: 2, step: 0.1 },
                { type: 'number', path: 'llm.deepseek.max_tokens', label: '最大输出 tokens', default: 1024, min: 1, max: 8192, step: 16 },
                { type: 'number', path: 'llm.deepseek.top_p', label: 'Top P', default: 0.9, min: 0, max: 1, step: 0.05 },
                { type: 'check', path: 'llm.deepseek.stream', label: '启用流式输出', default: true },
                { type: 'check', path: 'llm.deepseek.enable_thinking', label: '启用思考模式', default: false },
            ] },
            { id: 'aliyun', label: '阿里云', fields: [
                { type: 'text', path: 'llm.aliyun.model', label: '模型', default: 'qwen-plus' },
                { type: 'number', path: 'llm.aliyun.temperature', label: '温度', default: 0.7, min: 0, max: 2, step: 0.1 },
                { type: 'number', path: 'llm.aliyun.max_tokens', label: '最大输出 tokens', default: 1024, min: 1, max: 8192, step: 16 },
                { type: 'number', path: 'llm.aliyun.top_p', label: 'Top P', default: 0.9, min: 0, max: 1, step: 0.05 },
                { type: 'check', path: 'llm.aliyun.stream', label: '启用流式输出', default: true },
                { type: 'check', path: 'llm.aliyun.enable_thinking', label: '启用思考模式', default: false },
            ] },
            { id: 'gemini', label: 'Gemini', fields: [
                { type: 'text', path: 'llm.gemini.model', label: '模型', default: 'gemini-3.6-flash' },
                { type: 'number', path: 'llm.gemini.temperature', label: '温度', default: 0.7, min: 0, max: 2, step: 0.1 },
                { type: 'number', path: 'llm.gemini.max_tokens', label: '最大输出 tokens', default: 1024, min: 1, max: 8192, step: 16 },
                { type: 'number', path: 'llm.gemini.top_p', label: 'Top P', default: 0.9, min: 0, max: 1, step: 0.05 },
                { type: 'check', path: 'llm.gemini.stream', label: '启用流式输出', default: true },
                { type: 'check', path: 'llm.gemini.enable_thinking', label: '启用思考模式', default: false },
            ] },
            { id: 'meowllm', label: 'MeowLLM', fields: [
                { type: 'custom', render: () => Config.llm_meowllmContent() },
            ] },
        ] },
        { type: 'number', path: 'llm.short_term_rounds', label: '短期记忆轮数', default: 5, min: 1, max: 60, step: 1 },
        { type: 'custom', render: () => Config.splitFlagEditor('llm.split_flag') },
        { type: 'number', path: 'llm.split_limit', label: '最小分段长度', default: 6, min: 1, max: 100, step: 1 },
    ] });
    panel('llm_prompt', 'LLM 提示词', '大脑', open(() => App.openLlmPromptPanel()));
    panel('llm_algorithm', 'LLM 算法', '大脑', open(() => App.openLlmAlgorithmPanel()));
    panel('active', '主动回复设置', '大脑', { advanced: false, render: () => Config.llm_active() });
    panel('active_config', '主动回复', '大脑', open(() => App.openActiveConfigPanel()));
    panel('active_browse', 'B站浏览', '大脑', open(() => App.openActiveBrowsePanel()));
    panel('ltmem', '长期记忆', '大脑', { fields: [
        { type: 'section', label: '长期记忆 (long_term_mem)' },
        { type: 'number', path: 'catbrain.long_term_mem.memory_days', label: '长期记忆回溯天数',
          default: 300, min: 1, max: 3650, step: 1,
          help: '把多少天内的长期记忆读进上下文；越大越完整，也越占提示词。' },
        { type: 'check', path: 'catbrain.long_term_mem.inject_recent', label: '注入最近原文', default: false,
          help: '把当前用户最近的原始记录追加到提示词，作为摘要之外的兜底。' },
        { type: 'number', path: 'catbrain.long_term_mem.inject_recent_lines', label: '注入原文条数',
          default: 20, min: 1, max: 200, step: 1,
          help: '开启“注入最近原文”时追加多少条原始消息。' },
    ] });
    panel('abstract', '记忆摘要', '大脑', render(() => Config.catbrain_abstract()));
    panel('rulesbreak', '原则词', '大脑', open(() => App.openRulesBreakPanel()));
    panel('values', '价值观', '大脑', render(() => Config.catbrain_values()));
    panel('usermem', '用户记忆', '大脑', render(() => Config.catbrain_usermem()));
    panel('db_search', '搜索学习', '大脑', render(() => Config.db_search()));
    panel('db_store', '知识存储与检索', '大脑', render(() => Config.db_store()));
    panel('db_source', '数据来源', '大脑', open(() => App.openDatabaseSourcePanel()));
    panel('db_prefill', '知识预填', '大脑', open(() => App.openDbPrefillPanel()));

    // ==================== 形象 ====================
    panel('vts_config', 'VTS 配置', '形象', render(() => Config.vts_config()));
    panel('vts_emotion', 'VTS 表情', '形象', render(() => Config.vts_emotion()));
    panel('desktopet', '桌宠', '形象', render(() => Config.desktopet_config()));
    panel('vts_params', 'VTS 参数', '形象', render(() => Config.vts_params()));

    // ==================== 娱乐 ====================
    panel('meowsinger_model', '歌曲模型', '娱乐', render(() => Config.meowsingerModel()));
    panel('meowsinger_song', '点歌', '娱乐', render(() => Config.meowsingerSong()));
    panel('meowsinger_cover', '翻唱', '娱乐', open(() => App.openMeowsingerCoverPanel()));
    panel('meowsinger_sentiment', '感想', '娱乐', { fields: [
        { type: 'section', label: '唱歌感想' },
        { type: 'check', path: 'meowsinger.sentiment.enabled', label: '启用感想', default: true,
          help: '完整唱完一首歌后，AI 结合歌词与歌曲信息发表感想' },
        { type: 'number', path: 'meowsinger.sentiment.max_tokens', label: '感想 max_tokens',
          default: 2048, min: 1, max: 32768, step: 16, help: '感想生成的最大 token 数' },
        { type: 'number', path: 'meowsinger.sentiment.word_count', label: '感想字数',
          default: 300, min: 50, max: 2000, step: 10, help: '感想引导词中要求的字数（默认 300）' },
        { type: 'area', path: 'meowsinger.sentiment.prompt', label: '感想引导词', default: '',
          help: '唱完整首歌后生成感想的引导词，{verb}/{song_title}/{lrc}/{result_text}/{word_count}=占位符' },
        { type: 'area', path: 'meowsinger.prompt.summary', label: '汇总回复引导词', default: '',
          help: '唱歌期间收到的观众消息汇总后统一回复的引导词，{lines}=观众消息列表' },
        { type: 'area', path: 'meowsinger.search.prompt', label: '歌曲搜索引导词', default: '',
          help: '唱歌开始/结束时搜索歌曲资料的引导词，{song_title}=歌名' },
    ] });
    panel('danmaku', '弹幕', '娱乐', render(() => Config.danmaku()));

    // ==================== 工具箱 ====================
    panel('toolbox', '工具箱', '工具箱', { advanced: false, open: () => App.openToolbox() });
    panel('center', '父级模型', '工具箱', render(() => Config.toolbox()));
    panel('minecraft', 'Minecraft', '工具箱', { fields: [
        { type: 'section', label: 'Minecraft 日志读取' },
        { type: 'check', path: 'minecraft.enabled', label: '启用 Minecraft 日志读取', default: false },
        { type: 'text', path: 'minecraft.log_path', label: '日志文件路径', default: '' },
        { type: 'text', path: 'minecraft.encoding', label: '编码', default: 'utf-8' },
        { type: 'number', path: 'minecraft.check_interval', label: '检查间隔（秒）', default: 30, min: 1, max: 60, step: 1 },
        { type: 'check', path: 'minecraft.use_player_name', label: '使用玩家名作为 UID', default: false },
        { type: 'text', path: 'minecraft.username_fixed', label: '固定用户名', default: 'YGZ醒脑片' },
        { type: 'check', path: 'minecraft.include_player_name_in_prompt', label: '在提示词中包含玩家名', default: true },
        { type: 'list', path: 'minecraft.filter_players', label: '玩家白名单（逗号分隔，空=不过滤）', default: [] },
        { type: 'check', path: 'minecraft.ignore_self_messages', label: '忽略自己发送的消息', default: false },
    ] });
    panel('meowvision', '视觉', '工具箱', render(() => Config.meowvision()));
    panel('napcat', 'NapCat', '工具箱', { advanced: false, render: () => Config.napcat() });
    panel('napcat_private', 'NapCat 私聊', '工具箱', render(() => Config.napcat_private()));
    panel('napcat_group', 'NapCat 群聊', '工具箱', render(() => Config.napcat_group()));
    panel('napcat_send', 'NapCat 主动发送', '工具箱', { fields: [
        { type: 'section', label: 'NapCat 主动发送（触发型工具）' },
        { type: 'check', path: 'napcat.active_sender.enabled', label: '启用主动发送', default: true,
          help: 'AI 主动给好友/群发消息、文件、链接（受 toolcalls 控制）' },
        { type: 'number', path: 'napcat.active_sender.cooldown', label: '冷却时间(秒)',
          default: 60, min: 0, max: 3600, step: 1, help: '两次主动发送的最小间隔' },
    ] });
    panel('napcat_account', 'NapCat 角色名', '工具箱', { fields: [
        { type: 'section', label: 'NapCat 连接与角色名' },
        { type: 'check', path: 'napcat.enabled', label: '启用 NapCat', default: false },
        { type: 'text', path: 'napcat.ws_url', label: 'WebSocket 地址', default: 'ws://127.0.0.1:3001' },
        { type: 'password', path: 'napcat.access_token', label: 'Access Token（可空）', default: '' },
        { type: 'text', path: 'napcat.self_nickname', label: '角色名（群内 @ 该昵称触发立即回复）', default: '喵利呜西斯' },
        { type: 'check', path: 'napcat.debug_event_dump', label: '调试：原始事件落盘', default: false,
          help: '开启后把 NapCat 原始事件写入 .temp/napcat_raw_events.jsonl（用于拿群机器人消息样本）' },
    ] });
    panel('weather', '天气', '工具箱', { fields: [
        { type: 'section', label: '天气查询（触发型工具）' },
        { type: 'check', path: 'weather.enabled', label: '启用天气查询', default: true,
          help: 'AI 根据用户天气询问触发查询并播报，数据来自中国天气网（受 toolcalls 控制）' },
    ] });
    panel('news', '新闻', '工具箱', { fields: [
        { type: 'section', label: '新闻查询（触发型工具）' },
        { type: 'check', path: 'news.enabled', label: '启用新闻查询', default: true,
          help: 'AI 根据用户新闻/热点询问触发爬取并概括，数据来自 Readhub（受 toolcalls 控制）' },
        { type: 'number', path: 'news.top_n', label: '爬取条数', default: 3, min: 1, max: 10, step: 1,
          help: '每次爬取并概括的新闻条数（默认 3，最多 10）' },
    ] });
    panel('add_backlog', '提醒', '工具箱', { fields: [
        { type: 'section', label: '新建待办（触发型工具）' },
        { type: 'check', path: 'add_backlog.enabled', label: '启用新建待办', default: true,
          help: 'AI 根据用户「记一下 / 提醒我几点做什么」触发，深度思考后写入 character/backlog（受 toolcalls 控制）' },
        { type: 'check', path: 'add_backlog.qq_enabled', label: 'QQ 对接', default: true,
          help: '开启后 QQ 私聊 / 群聊@ 也可触发新建待办，且待办 qq 提醒强制开启' },
    ] });
    panel('meowsongs', '哼唱', '工具箱', render(() => Config.meowsongs()));
    panel('turtle_soup', '海龟汤', '工具箱', { fields: [
        { type: 'section', label: '海龟汤（触发型工具）' },
        { type: 'check', path: 'turtle_soup.enabled', label: '启用海龟汤', default: true,
          help: 'AI 根据用户「玩海龟汤 / 情境猜谜」触发，生成谜题并主持游戏（受 toolcalls 控制）' },
        { type: 'check', path: 'turtle_soup.qq_enabled', label: 'QQ 对接', default: true,
          help: '开启后 QQ 私聊 / 群聊@ 也可触发海龟汤，QQ 线仅发文本、不播语音' },
        { type: 'text', path: 'turtle_soup.bank_dir', label: '题库归档目录', default: './character/turtle_soup',
          help: '结束的局会归档到这里，供以后复用' },
        { type: 'text', path: 'turtle_soup.cache_dir', label: '运行时缓存目录', default: './.temp/turtle_soup',
          help: '进行中的局缓存到这里（含谜底谜面），结束或启动时清理' },
        { type: 'number', path: 'turtle_soup.surface_len.easy', label: '低难度汤面字数',
          default: 20, min: 10, max: 60, step: 1, help: '低难度（easy）汤面目标字数' },
        { type: 'number', path: 'turtle_soup.surface_len.hard', label: '高难度汤面字数',
          default: 40, min: 20, max: 100, step: 1, help: '高难度（hard）汤面目标字数' },
    ] });
    panel('flux_painter', '绘画', '工具箱', { advanced: false, render: () => Config.fluxPainter() });
    panel('flux_painter_service', '绘画·服务', '工具箱', render(() => Config.fluxPainterService()));
    panel('flux_painter_model', '绘画·模型', '工具箱', render(() => Config.fluxPainterModel()));
    panel('flux_painter_prompt', '绘画·提示词', '工具箱', render(() => Config.fluxPainterPrompt()));
    panel('flux_painter_workflow', '绘画·工作流', '工具箱', render(() => Config.fluxPainterWorkflow()));
})();
