/**
 * API 平台（汇总）
 *
 * 做两件事：
 *   1) 汇总面板：把散在各卡片里的 API Key / Base URL 集中到「基本设置」一页填写。
 *      每个条目写的仍然是它自己的配置路径 —— 只汇总，不做 fan-out，各节点可不同。
 *   2) 去重：包装 Config._text / Config._password，凡是渲染 `.api_key` / `.base_url`
 *      这两个字段的，一律返回空 —— 这样各卡片里就不再出现重复的 Key 输入框，
 *      不必去逐个改 js/config/*.js（那些文件被工具标记为敏感目录）。
 *
 * 依赖：必须在 js/config/*.js 之后、任何面板渲染之前加载。
 */
(function () {
    if (typeof Config === 'undefined') return;
    // 幂等：本文件若被重复引入/重复执行，第二次直接返回。
    if (Config.__apiPlatformsInstalled) {
        console.warn('[api_platforms] duplicate load detected and skipped');
        return;
    }
    Config.__apiPlatformsInstalled = true;
    const BUILD = 'v37';
    try { console.log('[api_platforms] ' + BUILD + ' ready'); } catch (e) { }

    // 原始渲染函数：优先用 core.js 在定义处钉死的引用（不受重复加载/拦截顺序影响）
    const origText = Config._baseText || Config._text;
    const origPassword = Config._basePassword || Config._password;

    // 插件配置卡片要绕过下面的「去重」拦截，直接拿原始渲染函数
    Config._rawText = origText;
    Config._rawPassword = origPassword;

    // ---------------- 1. 平台 → 各引用点 ----------------
    Config.API_PLATFORMS = [
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
                ['原则词', 'rulebreak.deepseek']
            ]
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
                ['B站视觉 (主动回复)', 'llm_active.vision']
            ]
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
                ['B站视觉 (主动回复)', 'llm_active.vision.gemini']
            ]
        },
        {
            title: 'SiliconFlow（仅向量化）',
            url: 'https://api.siliconflow.cn/v1',
            nodes: [
                ['知识库向量化', 'database.store.embedding.siliconflow']
            ]
        }
    ];

    /** 渲染汇总面板（挂到「基本设置」页尾）
     *  这里自己拼 HTML，不调用 Config._text / Config._password：
     *  那两个函数被本文件的「去重」逻辑包过，只要捕获时机或加载次数有一点偏差，
     *  行就会变成空字符串（面板看起来像空壳）。自己拼 HTML 则完全不受影响。
     */
    Config.apiPlatforms = function () {
        try {
            return this._apiPlatformsImpl();
        } catch (e) {
            try { console.error('[api_platforms] impl failed', e); } catch (e2) { }
            return '<div class="form-section"><h4>API 平台 · ' + BUILD + '</h4></div>' +
                '<div class="help-text" style="color:#c62828;font-weight:600">' +
                'DEBUG impl-failed: ' + (e && e.message ? e.message : e) +
                ' · BUILD=' + BUILD + '</div>';
        }
    };

    Config._apiPlatformsImpl = function () {
        const esc = (s) => (typeof U !== 'undefined' && U.escAttr)
            ? U.escAttr(s == null ? '' : s) : String(s == null ? '' : s);
        const field = (label, path, value, isPassword, help) =>
            '<div class="form-group"><label>' + esc(label) + '</label>' +
            '<input type="' + (isPassword ? 'password' : 'text') + '"' +
            ' data-path="' + esc(path) + '" value="' + esc(value) + '">' +
            (help ? '<div class="help-text">' + esc(help) + '</div>' : '') +
            '</div>';
        // 插件卡片（config/plugins.js）复用同一份"直接拼 HTML"，同样绕开拦截器
        Config._rawField = field;

        let h = this._section('API 平台') +
            '<div class="help-text">' +
            this._t('这里集中填写各平台的 API Key 与 Base URL；「模型」仍在各自卡片里单独设置') +
            '<br>' +
            this._t('插件自己的 API Key / Base URL 在对应插件卡片里填写，不在这里汇总') +
            '</div>';
        this.API_PLATFORMS.forEach(p => {
            let rows = '';
            try {
                rows = p.nodes.map(([label, base]) => {
                    const name = this._t(label);
                    const keyPath = base + '.api_key';
                    const urlPath = base + '.base_url';
                    return field(name + ' · ' + this._t('API Key'), keyPath,
                                 this._val(keyPath, ''), true, '') +
                           field(name + ' · ' + this._t('Base URL'), urlPath,
                                 this._val(urlPath, p.url), false, '');
                }).join('');
            } catch (e) {
                rows = '';
                try { console.error('[api_platforms] build rows failed', e); } catch (e2) { }
            }
            // 自诊断：行是空的就把原因印在面板里，别再让人对着空白猜
            if (!rows) {
                rows = '<div class="help-text" style="color:#c62828;font-weight:600">' +
                       'DEBUG rows-empty: nodes=' + p.nodes.length +
                       ' · rawField=' + (typeof Config._rawField) +
                       ' · _val=' + (typeof this._val) +
                       ' · _fold=' + (typeof this._fold) +
                       ' · BUILD=' + BUILD +
                       '</div>';
            }
            const title = this._t(p.title) + '（' + p.nodes.length + ' ' + this._t('处') + '）';
            // 默认展开：点进页签就能看到输入框，不用再逐个点开折叠
            h += this._fold(title, rows, true);
        });
        return h;
    };

    // ---------------- 2. 各卡片不再渲染 API Key / Base URL ----------------
    // 只拦这两个字段；其它以 _url 结尾的（server_url / netease_url / rvc_url / ws_url…）
    // 和「数据来源」的自定义编辑器不受影响。
    const CRED_SUFFIX = ['.api_key', '.base_url'];

    function isCredField(path) {
        if (!path) return false;
        if (String(path).indexOf('database.search.sites.') === 0) return false;   // 站点地址不是凭据
        return CRED_SUFFIX.some(s => String(path).slice(-s.length) === s);
    }

    Config._text = function (label, path, def, help) {
        // 插件卡片渲染期间放行（见 config/plugins.js 的 _pluginMode）
        if (Config._pluginMode) return origText.apply(this, arguments);
        if (isCredField(path)) return '';
        return origText.apply(this, arguments);
    };
    Config._password = function (label, path, def, help) {
        if (Config._pluginMode) return origPassword.apply(this, arguments);
        if (isCredField(path)) return '';
        return origPassword.apply(this, arguments);
    };
})();
