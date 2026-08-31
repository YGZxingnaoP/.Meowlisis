/**
 * 配置面板生成器 - db 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
    db_search() {
        const type = this._val('database.search.llm_type', 'deepseek');
        let h = this._section('搜索学习 (database.search)') +
            this._num('搜索 LLM 温度', 'database.search.temperature', 0.7, 0, 2, 0.1,
                '搜索模块独立 LLM，temperature 默认 0.7') +
            this._llmTypeSelect('搜索 LLM 类型', 'database.search.llm_type', type);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="db_search_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="db_search_aliyun">阿里云</button>
        </div>`;
        h += `<div class="tab-content active" data-tab-content="db_search_ds">` +
            this._password('API Key', 'database.search.deepseek.api_key', '') +
            this._text('Base URL', 'database.search.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'database.search.deepseek.model', 'deepseek-chat') +
            this._num('max_tokens', 'database.search.deepseek.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="db_search_aliyun">` +
            this._password('API Key', 'database.search.aliyun.api_key', '') +
            this._text('Base URL', 'database.search.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'database.search.aliyun.model', 'qwen-plus') +
            this._num('max_tokens', 'database.search.aliyun.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += this._section('搜索 Agent') +
            this._num('工具循环最大轮数', 'database.search.agent.max_rounds', 5, 1, 50, 1,
                '单任务 AI 调用工具的最大轮数，达到后强制结束') +
            this._num('visit_url 正文截断长度', 'database.search.agent.visit_max_chars', 8000, 500, 50000, 500,
                'visit_url 单次回传给 AI 的正文字符数上限') +
            this._section('聊天记录滚动') +
            this._num('滚动触发条数', 'database.record.max_messages', 50, 1, 1000, 1,
                '累计多少条 user 消息滚动一轮（触发核心搜索决策）') +
            this._num('保留轮数', 'database.record.rounds', 2, 1, 10, 1,
                'last / past_1 / ... 保留轮数');
        return h;
    },
    db_store() {
        const provider = this._val('database.store.embedding.provider', 'siliconflow');
        let h = this._section('知识存储与检索 (database.store)') +
            `<div class="form-group"><label>向量平台</label>
            <select data-path="database.store.embedding.provider">
                <option value="aliyun" ${provider === 'aliyun' ? 'selected' : ''}>阿里云</option>
                <option value="siliconflow" ${provider === 'siliconflow' ? 'selected' : ''}>硅基流动</option>
            </select>
            <div class="help-text">选择文本向量化（embedding）平台，两个平台独立配置 API Key</div></div>`;

        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="embed_aliyun">阿里云</button>
            <button class="modal-tab" data-tab="embed_sf">硅基流动</button>
        </div>`;

        h += `<div class="tab-content active" data-tab-content="embed_aliyun">` +
            this._password('API Key', 'database.store.embedding.aliyun.api_key', '') +
            this._text('Base URL', 'database.store.embedding.aliyun.base_url', 'https://dashscope.aliyuncs.com/api/v1') +
            this._text('模型', 'database.store.embedding.aliyun.model', 'qwen3.7-text-embedding') +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="embed_sf">` +
            this._password('API Key', 'database.store.embedding.siliconflow.api_key', '') +
            this._text('Base URL', 'database.store.embedding.siliconflow.base_url', 'https://api.siliconflow.cn/v1') +
            this._text('模型', 'database.store.embedding.siliconflow.model', 'BAAI/bge-m3') +
            `</div>`;

        h += this._select('向量维度', 'database.store.embedding.dimension', [
            {value:'2560',label:'2560'},{value:'2048',label:'2048'},{value:'1536',label:'1536'},
            {value:'1024',label:'1024'},{value:'768',label:'768'},{value:'512',label:'512'},
            {value:'256',label:'256'}
        ], '1024', '仅阿里云 qwen3.7-text-embedding 支持指定维度；改维度后需重新预填充') +
            this._num('默认检索条数', 'database.store.top_k', 5, 1, 50, 1,
                '每条消息提取 keys 后检索的知识库条数') +
            this._num('关键词触发检索条数', 'database.store.keyword_top_k', 15, 1, 50, 1,
                '命中"知道/了解"关键词时检索的知识库条数') +
            this._text('向量库目录', 'database.store.db_dir', '.DataBase',
                'ChromaDB 持久化目录（项目根目录）');
        return h;
    },

    // ============ 数据库预填充（一键预填）子球 ============,
    db_prefill(data) {
        const sites = (data && data.sites) || {};
        const siteKeys = Object.keys(sites);
        if (!siteKeys.length) {
            return this._section('知识库预填充') +
                `<div class="help-text">未读取到预填充配置（gui/tools/prefill_seed.json），请检查文件是否存在。</div>`;
        }
        let h = this._section('知识库预填充') +
            `<div class="help-text">选择数据来源站点并添加搜索词条（回车添加、点击 × 删除），点击「一键预填」后将模拟现有 search 模块：搜索 → 抓详情页正文 → 分块 → 向量化 → 入库。源文件归档到 .DataBase/raw_seed。</div>`;

        siteKeys.forEach(site => {
            const cfg = sites[site] || {};
            const label = cfg.label || site;
            const keywords = cfg.keywords || [];
            h += `<div class="char-card">
                <div class="checkbox-group"><input type="checkbox" class="db-prefill-site" data-site="${this._escAttr(site)}" checked><label>${this._esc(label)}（${this._esc(site)}）</label></div>
                ${this._keywordTagEditor(site, keywords)}
            </div>`;
        });

        h += `<div class="checkbox-group"><input type="checkbox" id="dbPrefillReset" checked><label>清空已有预填数据后再写入</label></div>
            <div class="speaker-actions">
                <button type="button" class="btn btn-primary" id="dbPrefillStartBtn">一键预填</button>
            </div>
            <div id="dbPrefillStatus" class="help-text" style="margin-top:8px;"></div>`;
        return h;
    },

    // 词条 tag 编辑器（借鉴 LLM 分隔符编辑器：每个词条单独一个 tag）,
    _keywordTagEditor(site, keywords) {
        const list = (keywords || []).filter(k => k != null && String(k).trim());
        const tags = list.map(k =>
            `<span class="split-tag" data-keyword="${this._escAttr(k)}">${this._esc(k)}<button type="button" class="split-tag-remove">&times;</button></span>`
        ).join('');
        return `<div class="form-group"><label>搜索词条</label>
            <div class="split-flag-editor" data-keyword-editor="${this._escAttr(site)}">
                <div class="split-tags">${tags}</div>
                <div class="split-add-row">
                    <input type="text" class="split-add-input" placeholder="输入词条后回车添加">
                </div>
            </div>
            <div class="help-text">每个词条单独一条，回车添加，点击 × 删除</div>
        </div>`;
    },

    // ============ 数据库来源（sites）子球 ============,
    db_source() {
        const sites = this._val('database.search.sites', {}) || {};
        const keys = Object.keys(sites);
        let h = this._section('网页数据来源 (database.search.sites)') +
            `<div id="sourceSiteList">`;
        if (!keys.length) {
            h += `<div class="help-text">暂无站点，点击下方按钮添加</div>`;
        } else {
            keys.forEach(k => { h += this.sourceSiteRow(k, sites[k] || {}); });
        }
        h += `</div>`;
        h += `<button class="btn btn-secondary" id="addSourceSiteBtn">添加站点</button>` +
            `<div class="help-text">策略：http=网页解析、api=JSON接口、direct=直连详情页。search_url 用 {q} 占位搜索关键词。</div>`;
        return h;
    },
    sourceSiteRow(key, cfg) {
        cfg = cfg || {};
        const label = cfg.label != null ? cfg.label : key;
        const description = cfg.description || '';
        const enabled = cfg.enabled !== false;
        const strategy = cfg.strategy || 'http';
        const count = cfg.count != null ? cfg.count : 5;
        const baseUrl = cfg.base_url || '';
        const searchUrl = cfg.search_url || '';
        const interval = cfg.interval != null ? cfg.interval : 2;
        return `<div class="char-card" data-source-site="${this._esc(key)}">
            <div class="char-card-title source-site-toggle" style="cursor:pointer;">
                <span class="source-toggle-arrow">▾</span>
                ${this._esc(label)} <span class="help-text">(${this._esc(key)})</span>
            </div>
            <div class="source-site-body">
                <div class="form-group"><label>站点标识</label>
                    <input type="text" data-source-field="key" value="${this._esc(key)}" placeholder="如 mcmod"></div>
                <div class="form-group"><label>显示名</label>
                    <input type="text" data-source-field="label" value="${this._esc(label)}" placeholder="如 MC百科"></div>
                <div class="form-group"><label>适用场景</label>
                    <input type="text" data-source-field="description" value="${this._esc(description)}" placeholder="如 Minecraft 相关知识检索"></div>
                <div class="checkbox-group"><input type="checkbox" data-source-field="enabled" ${enabled ? 'checked' : ''}><label>启用</label></div>
                <div class="form-group"><label>策略</label>
                    <select data-source-field="strategy">
                        <option value="http" ${strategy === 'http' ? 'selected' : ''}>http</option>
                        <option value="api" ${strategy === 'api' ? 'selected' : ''}>api</option>
                        <option value="direct" ${strategy === 'direct' ? 'selected' : ''}>direct</option>
                    </select></div>
                <div class="form-group"><label>每站爬取条数</label>
                    <input type="number" data-source-field="count" value="${count}" min="1" max="50" step="1"></div>
                <div class="form-group"><label>站点主页</label>
                    <input type="text" data-source-field="base_url" value="${this._esc(baseUrl)}" placeholder="https://..."></div>
                <div class="form-group"><label>搜索 URL 模板</label>
                    <input type="text" data-source-field="search_url" value="${this._esc(searchUrl)}" placeholder="https://...?q={q}"></div>
                <div class="form-group"><label>请求间隔(秒)</label>
                    <input type="number" data-source-field="interval" value="${interval}" min="0" max="60" step="0.5"></div>
                <div class="source-verify-row">
                    <button type="button" class="btn btn-secondary source-verify-btn">验证</button>
                    <button type="button" class="btn btn-secondary source-remove-btn">删除</button>
                </div>
                <div class="source-verify-result help-text"></div>
            </div>
        </div>`;
    },

    // ============ 角色卡（配置部分 + JSON 字段） ============
    // 角色卡 JSON 字段由 App.onPlanetClick 异步填充,
});
