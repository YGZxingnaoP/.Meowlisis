/**
 * 卡面数据层（与 card_assets/cards.json 一一对应，共 69 张）
 *
 * 图片：resource/cat_photos/{id}.png（832×1152）
 * 主题：group 字段决定渐变配色（同一主题的卡视觉成组）
 * 注意：cards.json 里的 rarity 字段前端不使用，不显示任何稀有度文案。
 */
const Cards = {
    DIR: 'resource/cat_photos/',

    /** 8 大主题配色（--a → --b 渐变，用于卡面兜底底/描边/配置面板头部） */
    THEMES: {
        core:    { a: '#9db4d6', b: '#5a7fb0' },   // 核心系统  灰蓝
        service: { a: '#5cc8ff', b: '#2a7ad6' },   // 服务启动  科技蓝
        brain:   { a: '#b07bff', b: '#6a3ad6' },   // 语言大脑  紫
        voice:   { a: '#2fd6d6', b: '#159aa8' },   // 语音音色  青
        avatar:  { a: '#ff7ec7', b: '#d63a8f' },   // 角色形象  品红
        art:     { a: '#ffc45c', b: '#d68a20' },   // 视觉创作  橙金
        social:  { a: '#ffcf6b', b: '#e0558f' },   // 社交娱乐  粉黄
        life:    { a: '#7be08a', b: '#2aa84a' }    // 生活工具  绿
    },

    /** n=显示名  g=主题  e=图片缺失时的兜底 emoji */
    META: {
        // ── 启动球 9 ──
        launcher_phone:       { n: '接口',      g: 'service', e: '📱' },
        launcher_main:        { n: '主程序',    g: 'service', e: '🖥️' },
        launcher_sovits:      { n: 'SoVITS',    g: 'voice',   e: '🎙️' },
        launcher_sensevoice:  { n: 'SenseVoice', g: 'voice',  e: '🎧' },
        launcher_painting:    { n: '绘画',      g: 'art',     e: '🎨' },
        launcher_napcat:      { n: 'NapCat',    g: 'social',  e: '🐾' },
        launcher_netease:     { n: '网易云',    g: 'social',  e: '🎵' },
        launcher_rvc:         { n: 'RVC',       g: 'voice',   e: '🎤' },
        launcher_desktopet:   { n: '桌宠',      g: 'avatar',  e: '🐱' },

        // ── 外环配置 13 ──
        basic:                { n: '基本',      g: 'core',    e: '⚙️' },
        character:            { n: '角色卡',    g: 'avatar',  e: '📇' },
        sensevoice:           { n: 'SenseVoice', g: 'voice',  e: '🎤' },
        llm:                  { n: 'LLM',       g: 'brain',   e: '🧠' },
        active:               { n: '主动回复',  g: 'brain',   e: '💤' },
        catbrain:             { n: 'CatBrain',  g: 'brain',   e: '🐾' },
        database:             { n: '数据库',    g: 'brain',   e: '🗄️' },
        tts:                  { n: 'TTS',       g: 'voice',   e: '🎙️' },
        subtitle:             { n: '字幕',      g: 'voice',   e: '💬' },
        vts:                  { n: 'VTS',       g: 'avatar',  e: '🧍' },
        toolbox:              { n: '工具箱',    g: 'core',    e: '🧰' },
        meowsinger:           { n: '歌曲',      g: 'social',  e: '🎵' },
        calendar:             { n: '待办',      g: 'life',    e: '📅' },

        // ── 工具箱 10 ──
        minecraft:            { n: 'Minecraft', g: 'life',    e: '⛏️' },
        meowvision:           { n: '视觉',      g: 'art',     e: '👁️' },
        napcat:               { n: 'NapCat',    g: 'social',  e: '💬' },
        weather:              { n: '天气',      g: 'life',    e: '🌤️' },
        news:                 { n: '新闻',      g: 'life',    e: '📰' },
        danmaku:              { n: '弹幕',      g: 'social',  e: '💭' },
        add_backlog:          { n: '提醒',      g: 'life',    e: '🔔' },
        meowsongs:            { n: '哼唱',      g: 'social',  e: '🎶' },
        turtle_soup:          { n: '海龟汤',    g: 'social',  e: '🍜' },
        flux_painter:         { n: '绘画',      g: 'art',     e: '🖌️' },

        // ── CatBrain 子卡 5 ──
        catbrain_ltmem:       { n: '长期记忆',  g: 'brain',   e: '💎' },
        catbrain_abstract:    { n: '记忆摘要',  g: 'brain',   e: '📖' },
        catbrain_rulesbreak:  { n: '原则词',    g: 'brain',   e: '🔑' },
        catbrain_values:      { n: '价值观',    g: 'brain',   e: '⚖️' },
        catbrain_usermem:     { n: '用户记忆',  g: 'brain',   e: '🫧' },

        // ── 数据库 4 ──
        db_search:            { n: '搜索',      g: 'brain',   e: '🔍' },
        db_store:             { n: '知识',      g: 'brain',   e: '📚' },
        db_source:            { n: '来源',      g: 'brain',   e: '🔗' },
        db_prefill:           { n: '预填',      g: 'brain',   e: '🫙' },

        // ── TTS 4 ──
        tts_model:            { n: '模型',      g: 'voice',   e: '💠' },
        tts_params:           { n: '参数',      g: 'voice',   e: '🎚️' },
        tts_config:           { n: '配置',      g: 'voice',   e: '🎛️' },
        tts_pause:            { n: '间隔',      g: 'voice',   e: '⏳' },

        // ── LLM 3 ──
        llm_model:            { n: '模型',      g: 'brain',   e: '🧊' },
        llm_prompt:           { n: '提示词',    g: 'brain',   e: '📜' },
        llm_algorithm:        { n: '算法',      g: 'brain',   e: '📈' },

        // ── 主动回复 2 ──
        active_config:        { n: '配置',      g: 'brain',   e: '🕐' },
        active_browse:        { n: '浏览',      g: 'brain',   e: '🖼️' },

        // ── 歌曲 4 ──
        meowsinger_model:     { n: '模型',      g: 'social',  e: '💗' },
        meowsinger_song:      { n: '歌曲',      g: 'social',  e: '📻' },
        meowsinger_cover:     { n: '翻唱',      g: 'social',  e: '🎤' },
        meowsinger_sentiment: { n: '感想',      g: 'social',  e: '💖' },

        // ── VTS 4 ──
        vts_config:           { n: '配置',      g: 'avatar',  e: '🕹️' },
        vts_emotion:          { n: '表情',      g: 'avatar',  e: '😊' },
        desktopet:            { n: '桌宠',      g: 'avatar',  e: '🐈' },
        vts_params:           { n: '参数',      g: 'avatar',  e: '🔧' },

        // ── SenseVoice 3 ──
        sensevoice_config:    { n: '识别',      g: 'voice',   e: '📡' },
        sensevoice_mic:       { n: '闭麦',      g: 'voice',   e: '🔇' },
        sensevoice_audio:     { n: '音频',      g: 'voice',   e: '🌀' },

        // ── NapCat 4 ──
        napcat_private:       { n: '私聊回复',  g: 'social',  e: '💬' },
        napcat_group:         { n: '群聊回复',  g: 'social',  e: '👥' },
        napcat_send:          { n: '主动发送',  g: 'social',  e: '✈️' },
        napcat_account:       { n: '角色名',    g: 'social',  e: '🪪' },

        // ── 绘画 Flux 4 ──
        flux_service:         { n: '服务',      g: 'art',     e: '🖥️' },
        flux_model:           { n: '模型',      g: 'art',     e: '🗂️' },
        flux_prompt:          { n: '提示词',    g: 'art',     e: '🏷️' },
        flux_workflow:        { n: '工作流',    g: 'art',     e: '🧩' }
    },

    img(id) {
        const m = this.META[id];
        if (m && m.img) return m.img;          // 插件卡面走接口（plugins/<id>/card.png）
        return this.DIR + id + '.png';
    },

    theme(id) {
        const m = this.META[id];
        return this.THEMES[(m && m.g) || 'core'] || this.THEMES.core;
    },

    emoji(id) {
        const m = this.META[id];
        return (m && m.e) || '🃏';
    },

    /** 卡面显示名；清单里没有时回落到调用方给的 label */
    name(id, label) {
        const m = this.META[id];
        return (m && m.n) || label || id;
    }
};

window.Cards = Cards;
