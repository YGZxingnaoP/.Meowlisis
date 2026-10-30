/**
 * API 平台 / 凭据注册表
 *
 * - 普通面板遇到 .api_key / .base_url 时自动隐藏（由 Config._text/_password 查表）；
 * - 「基本设置 → API」只从这一份数据生成输入框；
 * - 插件配置仍走 Config._rawField，不受隐藏规则影响。
 */
(function () {
    const ConfigRef = (typeof Config !== 'undefined') ? Config : window.Config;
    if (!ConfigRef) throw new Error('credentials.js requires config/core.js');

    const PLATFORMS = [
        {
            title: 'DeepSeek',
            url: 'https://api.deepseek.com/v1',
            nodes: [
                ['主模型 (LLM)', 'llm.deepseek'],
                ['工具箱父级', 'toolbox.deepseek'],
                ['点歌翻唱', 'meowsinger.deepseek'],
                ['记忆摘要', 'catbrain.abstract_mem.deepseek'],
                ['价值观', 'catbrain.cat_values.deepseek'],
                ['价值观·二次审查', 'catbrain.cat_values.second_review.deepseek'],
                ['用户记忆', 'catbrain.user_memory.deepseek'],
                ['搜索学习', 'database.search.deepseek'],
                ['绘画提示词', 'flux_painter.deepseek'],
                ['原则词', 'rulebreak.deepseek'],
            ],
        },
        {
            title: '阿里云 DashScope',
            url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            nodes: [
                ['主模型 (LLM)', 'llm.aliyun'],
                ['工具箱父级', 'toolbox.aliyun'],
                ['点歌翻唱', 'meowsinger.aliyun'],
                ['记忆摘要', 'catbrain.abstract_mem.aliyun'],
                ['价值观', 'catbrain.cat_values.aliyun'],
                ['价值观·二次审查', 'catbrain.cat_values.second_review.aliyun'],
                ['用户记忆', 'catbrain.user_memory.aliyun'],
                ['搜索学习', 'database.search.aliyun'],
                ['知识库向量化', 'database.store.embedding.aliyun'],
                ['绘画提示词', 'flux_painter.aliyun'],
                ['视觉 (MeowVision)', 'meowvision'],
                ['B站视觉 (主动回复)', 'llm_active.vision'],
            ],
        },
        {
            title: 'Gemini',
            url: 'https://generativelanguage.googleapis.com/v1beta/openai/',
            nodes: [
                ['主模型 (LLM)', 'llm.gemini'],
                ['工具箱父级', 'toolbox.gemini'],
                ['点歌翻唱', 'meowsinger.gemini'],
                ['记忆摘要', 'catbrain.abstract_mem.gemini'],
                ['价值观', 'catbrain.cat_values.gemini'],
                ['价值观·二次审查', 'catbrain.cat_values.second_review.gemini'],
                ['用户记忆', 'catbrain.user_memory.gemini'],
                ['视觉 (MeowVision)', 'meowvision.gemini'],
                ['B站视觉 (主动回复)', 'llm_active.vision.gemini'],
            ],
        },
        {
            title: '记忆审查（独立）',
            url: '',
            nodes: [
                ['记忆审查（留空复用摘要后端）', 'catbrain.abstract_mem.review'],
            ],
        },
        {
            title: 'SiliconFlow（仅向量化）',
            url: 'https://api.siliconflow.cn/v1',
            nodes: [
                ['知识库向量化', 'database.store.embedding.siliconflow'],
            ],
        },
    ];

    const CRED_SUFFIX = ['.api_key', '.base_url'];

    function isCredential(path) {
        if (!path) return false;
        if (String(path).indexOf('database.search.sites.') === 0) return false;
        return CRED_SUFFIX.some(s => String(path).slice(-s.length) === s);
    }

    function esc(v) {
        return (typeof U !== 'undefined' && U.escAttr)
            ? U.escAttr(v == null ? '' : v)
            : String(v == null ? '' : v);
    }

    /** 直接拼字段，绕开 Config._text/_password 的隐藏规则 */
    function rawField(label, path, value, isPassword, help) {
        return '<div class="form-group"><label>' + esc(label) + '</label>' +
            '<input type="' + (isPassword ? 'password' : 'text') + '"' +
            ' data-path="' + esc(path) + '" value="' + esc(value) + '">' +
            (help ? '<div class="help-text">' + esc(help) + '</div>' : '') +
            '</div>';
    }

    function render() {
        const C = ConfigRef;
        let h = C._section('API 平台') +
            '<div class="help-text">' +
            C._t('这里集中填写各平台的 API Key 与 Base URL；「模型」仍在各自卡片里单独设置') +
            '<br>' +
            C._t('插件自己的 API Key / Base URL 在对应插件卡片里填写，不在这里汇总') +
            '</div>';
        PLATFORMS.forEach(p => {
            const rows = p.nodes.map(([label, base]) => {
                const name = C._t(label);
                const keyPath = base + '.api_key';
                const urlPath = base + '.base_url';
                return rawField(name + ' · ' + C._t('API Key'), keyPath,
                    C._val(keyPath, ''), true, '') +
                    rawField(name + ' · ' + C._t('Base URL'), urlPath,
                        C._val(urlPath, p.url), false, '');
            }).join('');
            const title = C._t(p.title) + '（' + p.nodes.length + ' ' + C._t('处') + '）';
            h += C._fold(title, rows, true);
        });
        return h;
    }

    const Credentials = {
        PLATFORMS,
        isCredential,
        isHidden: isCredential,
        render,
        rawField,
    };

    window.Credentials = Credentials;
    ConfigRef.API_PLATFORMS = PLATFORMS;
    ConfigRef.isCredential = isCredential;
    ConfigRef.apiPlatforms = render;
    ConfigRef._rawField = rawField;
    ConfigRef._rawText = ConfigRef._text;
    ConfigRef._rawPassword = ConfigRef._password;
})();
