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

    // 原始渲染函数：汇总页自己要用它们（见下方 apiPlatforms）
    const origText = Config._text;
    const origPassword = Config._password;

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

    /** 渲染汇总面板（挂到「基本设置」页尾） */
    Config.apiPlatforms = function () {
        let h = this._section('API 平台') +
            '<div class="help-text">' +
            this._t('这里集中填写各平台的 API Key 与 Base URL；「模型」仍在各自卡片里单独设置') +
            '</div>';
        this.API_PLATFORMS.forEach(p => {
            const rows = p.nodes.map(([label, base]) => {
                const name = this._t(label);
                // 用"原始"渲染函数：本页要显示的正是 .api_key / .base_url，
                // 不能走下面那条"拦截重复项"的包装。
                return origPassword.call(this, name + ' · ' + this._t('API Key'), base + '.api_key', '') +
                       origText.call(this, name + ' · ' + this._t('Base URL'), base + '.base_url', p.url);
            }).join('');
            const title = this._t(p.title) + '（' + p.nodes.length + ' ' + this._t('处') + '）';
            h += this._fold(title, rows);
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
        if (isCredField(path)) return '';
        return origText.apply(this, arguments);
    };
    Config._password = function (label, path, def, help) {
        if (isCredField(path)) return '';
        return origPassword.apply(this, arguments);
    };
})();
