/**
 * 配置面板生成器 - llm 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
    llm_model() {
        const type = this._val('llm.local_llm_type', 'deepseek');
        let h = this._section('LLM 大模型') +
            `<div class="form-group"><label>${this._t('LLM类型')}</label>
            <select data-path="llm.local_llm_type">
                <option value="deepseek" ${type === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                <option value="aliyun" ${type === 'aliyun' ? 'selected' : ''}>${this._t('阿里云')}</option>
                <option value="gemini" ${type === 'gemini' ? 'selected' : ''}>Gemini</option>
            </select></div>`;

        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="deepseek">DeepSeek</button>
            <button class="modal-tab" data-tab="aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab" data-tab="gemini">Gemini</button>
        </div>`;

        h += `<div class="tab-content active" data-tab-content="deepseek">` +
            this._password('API Key', 'llm.deepseek.api_key', '') +
            this._text('Base URL', 'llm.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'llm.deepseek.model', 'deepseek-chat') +
            this._num('温度', 'llm.deepseek.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.deepseek.max_tokens', 1024, 1, 8192, 16) +
            this._num('Top P', 'llm.deepseek.top_p', 0.9, 0, 1, 0.05) +
            this._check('启用流式输出', 'llm.deepseek.stream', true) +
            this._check('启用思考模式', 'llm.deepseek.enable_thinking', false) +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="aliyun">` +
            this._password('API Key', 'llm.aliyun.api_key', '') +
            this._text('Base URL', 'llm.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'llm.aliyun.model', 'qwen-plus') +
            this._num('温度', 'llm.aliyun.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.aliyun.max_tokens', 1024, 1, 8192, 16) +
            this._num('Top P', 'llm.aliyun.top_p', 0.9, 0, 1, 0.05) +
            this._check('启用流式输出', 'llm.aliyun.stream', true) +
            this._check('启用思考模式', 'llm.aliyun.enable_thinking', false) +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="gemini">` +
            this._password('API Key', 'llm.gemini.api_key', '') +
            this._text('Base URL', 'llm.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'llm.gemini.model', 'gemini-3.6-flash') +
            this._num('温度', 'llm.gemini.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.gemini.max_tokens', 1024, 1, 8192, 16) +
            this._num('Top P', 'llm.gemini.top_p', 0.9, 0, 1, 0.05) +
            this._check('启用流式输出', 'llm.gemini.stream', true) +
            this._check('启用思考模式', 'llm.gemini.enable_thinking', false) +
            `</div>`;

        h += this._num('短期记忆轮数', 'llm.short_term_rounds', 5, 1, 60, 1) +
            this.splitFlagEditor('llm.split_flag') +
            this._num('最小分段长度', 'llm.split_limit', 6, 1, 100, 1);
        return h;
    },
    llm_prompt(front) {
        const f = front || {};
        const frontPrompt = f.prompt || '';
        const activeFront = f.prompt_active || '';
        const napcatFront = f.prompt_napcat || '';
        const postPrompt = f.post_prompt || '';
        return this._section('提示词（前置词放最前，后置词放最后）') +
            `<div class="form-group"><label>${this._t('前置词（行为约束，system prompt 最前）')}</label>
                <textarea id="frontPromptInput" class="auto-grow" rows="3" placeholder="${this._t('一次回复不要一次性解决复杂问题...')}">${this._esc(frontPrompt)}</textarea>
                <div class="help-text">${this._t('放在 system prompt 最前面，约束本次回复行为')}</div>
            </div>` +
            `<div class="form-group"><label>${this._t('主动回复前置词')}</label>
                <textarea id="activeFrontPromptInput" class="auto-grow" rows="2" placeholder="${this._t('一次回复不要一次性解决复杂问题...')}">${this._esc(activeFront)}</textarea>
                <div class="help-text">${this._t('主动找话题时的行为约束')}</div>
            </div>` +
            `<div class="form-group"><label>${this._t('NapCat 前置词')}</label>
                <textarea id="napcatFrontPromptInput" class="auto-grow" rows="2" placeholder="${this._t('一次回复不要一次性解决复杂问题...')}">${this._esc(napcatFront)}</textarea>
                <div class="help-text">${this._t('QQ 回复时的行为约束')}</div>
            </div>` +
            `<div class="form-group"><label>${this._t('后置词（人设，system prompt 最后）')}</label>
                <textarea id="postPromptInput" class="auto-grow" rows="2" placeholder="${this._t('你是...，大家都叫你...')}">${this._esc(postPrompt)}</textarea>
                <div class="help-text">${this._t('放在 system prompt 最后，描述角色身份')}</div>
            </div>`;
    },
    _narrationFormula() {
        return `<div class="formula-box">
            <div class="formula-box-title">${this._t('计算公式')}</div>
            <div class="formula-block">
                <div class="formula-row">
                    <span class="formula-name">${this._t('水词密度分')}</span>
                    <span class="formula-expr">Density = 100 − ( W / L × 100 )</span>
                    <span class="formula-cond">${this._t('若 W / L ≥ θ 则 Density = 0')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('超长惩罚')}</span>
                    <span class="formula-expr">${this._t('Penalty = 0，当 L ≤ L')}<sub>0</sub></span>
                    <span class="formula-expr">Penalty = min( P<sub>cap</sub>, ( L − L<sub>0</sub> ) × r )，当 L &gt; L<sub>0</sub></span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('原始得分')}</span>
                    <span class="formula-expr">Raw<sub>t</sub> = max( 0, Density − Penalty )</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('平滑得分')}</span>
                    <span class="formula-expr">S<sub>t</sub> = λ · S<sub>t−1</sub> + ( 1 − λ ) · Raw<sub>t</sub></span>
                    <span class="formula-cond">${this._t('λ = 0.75（下降）/ 0.55（上升）/ 0.70（相等）')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('清洗档位')}</span>
                    <span class="formula-expr">S ≥ 60 不清洗；30 ≤ S &lt; 60 清部分；S &lt; 30 全清</span>
                </div>
            </div>
            <div class="formula-params">
                W = 命中水词字符数，L = 回复总字符数，θ = 密度阈值，L<sub>0</sub> = 超长阈值，
                r = 惩罚系数，P<sub>cap</sub> = 惩罚封顶，λ = 惯性系数
            </div>
        </div>`;
    },
    llm_algorithm() {
        return this._narrationFormula() +
            this._section('回复丰富性算法 (narration)') +
            this._check('启用清洗算法', 'llm.narration.enabled', true,
                '关闭后不做水词清洗，也不更新平滑得分') +
            this._check('分数记录', 'llm.narration.score_log_enabled', false,
                '开启后把每次对话的原始/平滑得分按启动时间分组写入 character/memory/llm_response_score.json') +
            this._section('平滑得分（EWMA）') +
            this._num('初始得分 S0', 'llm.narration.initial_score', 70, 0, 100, 1) +
            this._num('下降惯性系数 λ_down', 'llm.narration.lambda_down', 0.75, 0, 1, 0.05,
                'Raw < S 时使用，越大下降越慢') +
            this._num('上升惯性系数 λ_up', 'llm.narration.lambda_up', 0.55, 0, 1, 0.05,
                'Raw > S 时使用，越小上升越快') +
            this._num('相等惯性系数 λ_equal', 'llm.narration.lambda_equal', 0.70, 0, 1, 0.05) +
            this._section('原始得分（Raw）') +
            this._num('水词密度阈值', 'llm.narration.density_threshold', 0.8, 0, 1, 0.05,
                '水词占比 ≥ 该值时 DensityScore 直接为 0') +
            this._num('超长阈值 L', 'llm.narration.length_threshold', 30, 1, 500, 1,
                '回复字符数超过该值开始惩罚') +
            this._num('超长惩罚系数', 'llm.narration.length_penalty_rate', 0.4, 0, 5, 0.1,
                'Penalty = (L - 阈值) × 系数') +
            this._num('超长惩罚封顶', 'llm.narration.length_penalty_cap', 20, 0, 100, 1) +
            this._section('清洗档位') +
            this._num('部分清洗上限', 'llm.narration.part_level_upper', 60, 0, 100, 1,
                'S ≥ 该值完全不清洗') +
            this._num('部分清洗下限', 'llm.narration.part_level_lower', 30, 0, 100, 1,
                '该值 ≤ S < 上限时清洗口头禅/连接词/重复短句；S < 该值全清');
    },

    // 分割符编辑器：每个符号单独展示为小块，隐藏 input 保存 | 分隔的字符串,
    splitFlagEditor(path) {
        const raw = this._val(path, ',|，|。|!|！|?|？');
        const chars = String(raw || '').split('|').filter(c => c !== '');
        const tags = chars.map(c =>
            `<span class="split-tag" data-char="${c}">${c}<button type="button" class="split-tag-remove">&times;</button></span>`
        ).join('');
        return `<div class="form-group"><label>${this._t('分割符（点击 × 删除）')}</label>
            <div class="split-flag-editor" data-split-flag-editor="${path}">
                <div class="split-tags">${tags}</div>
                <div class="split-add-row">
                    <input type="text" class="split-add-input" placeholder="${this._t('输入一个符号后回车添加')}" maxlength="2">
                </div>
                <input type="hidden" data-path="${path}" value="${raw}">
            </div>
            <div class="help-text">${this._t('每个符号单独作为一个分段点，例如逗号、句号、感叹号')}</div>
        </div>`;
    },

    // ============ CatBrain 子模块（四球分别打开） ============
    // 长期记忆,
    catbrain_ltmem() {
        return this._section('长期记忆 (long_term_mem)') +
            this._num('长期记忆回溯天数', 'catbrain.long_term_mem.memory_days', 300, 1, 3650, 1);
    },

    // 记忆摘要,
    catbrain_abstract() {
        const ab = this._val('catbrain.abstract_mem.llm_type', 'deepseek');
        let h = this._section('记忆摘要 (abstract_mem)');
        h += this._num('摘要触发条数', 'catbrain.abstract_mem.summary_rounds', 30, 1, 500, 1,
            '这里指单条消息数（user/assistant 各算一条），与短期记忆的"轮数"不同：短期记忆一轮 = 用户 + AI 两条') +
            this._num('摘要检索条数上限', 'catbrain.abstract_mem.summary_top_limit', 20, 1, 200, 1) +
            this._num('话题更新间隔(秒)', 'catbrain.abstract_mem.topic_update_interval', 60, 1, 3600, 1);
        h += this._fold('证据分数 (evidence)',
            this._num('强化值半衰期(天)', 'catbrain.abstract_mem.evidence.rein_half_life_days', 30, 1, 3650, 1) +
            this._num('质疑值半衰期(天)', 'catbrain.abstract_mem.evidence.disp_half_life_days', 180, 1, 3650, 1) +
            this._num('confirmed 阈值', 'catbrain.abstract_mem.evidence.confirmed_threshold', 1.0, -10, 10, 0.1) +
            this._num('归档候选阈值', 'catbrain.abstract_mem.evidence.archive_threshold', -2.0, -10, 10, 0.1) +
            this._num('负分持续天数后归档', 'catbrain.abstract_mem.evidence.archive_days', 14, 1, 365, 1) +
            this._num('same 强化增量', 'catbrain.abstract_mem.evidence.same_delta', 0.5, 0, 10, 0.1) +
            this._num('opposite 质疑增量', 'catbrain.abstract_mem.evidence.opposite_delta', 1.0, 0, 10, 0.1)
        );
        h += this._llmTypeSelect('摘要 LLM 类型', 'catbrain.abstract_mem.llm_type', ab);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="abstract_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="abstract_aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab" data-tab="abstract_gemini">Gemini</button>
        </div>`;
        h += `<div class="tab-content active" data-tab-content="abstract_ds">` +
            this._password('API Key', 'catbrain.abstract_mem.deepseek.api_key', '') +
            this._text('Base URL', 'catbrain.abstract_mem.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'catbrain.abstract_mem.deepseek.model', 'deepseek-chat') +
            this._num('温度', 'catbrain.abstract_mem.deepseek.temperature', 0.7, 0, 2, 0.1) +
            this._num('max_tokens', 'catbrain.abstract_mem.deepseek.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="abstract_aliyun">` +
            this._password('API Key', 'catbrain.abstract_mem.aliyun.api_key', '') +
            this._text('Base URL', 'catbrain.abstract_mem.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'catbrain.abstract_mem.aliyun.model', 'qwen-plus') +
            this._num('温度', 'catbrain.abstract_mem.aliyun.temperature', 0.7, 0, 2, 0.1) +
            this._num('max_tokens', 'catbrain.abstract_mem.aliyun.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="abstract_gemini">` +
            this._password('API Key', 'catbrain.abstract_mem.gemini.api_key', '') +
            this._text('Base URL', 'catbrain.abstract_mem.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'catbrain.abstract_mem.gemini.model', 'gemini-3.6-flash') +
            this._num('温度', 'catbrain.abstract_mem.gemini.temperature', 0.7, 0, 2, 0.1) +
            this._num('max_tokens', 'catbrain.abstract_mem.gemini.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        return h;
    },

    // 价值观,
    catbrain_values() {
        const cv = this._val('catbrain.cat_values.llm_type', 'deepseek');
        let h = this._section('价值观 (cat_values)');
        h += this._llmTypeSelect('价值观 LLM 类型', 'catbrain.cat_values.llm_type', cv);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="values_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="values_aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab" data-tab="values_gemini">Gemini</button>
        </div>`;
        h += `<div class="tab-content active" data-tab-content="values_ds">` +
            this._password('API Key', 'catbrain.cat_values.deepseek.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'catbrain.cat_values.deepseek.model', 'deepseek-chat') +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="values_aliyun">` +
            this._password('API Key', 'catbrain.cat_values.aliyun.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'catbrain.cat_values.aliyun.model', 'qwen-plus') +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="values_gemini">` +
            this._password('API Key', 'catbrain.cat_values.gemini.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'catbrain.cat_values.gemini.model', 'gemini-3.6-flash') +
            `</div>`;
        h += this._num('价值观 max_tokens', 'catbrain.cat_values.max_tokens', 8192, 1, 65536, 16) +
            this._num('工具调用最大轮数', 'catbrain.cat_values.max_tool_rounds', 100, 1, 1000, 1) +
            this._num('计时检查间隔(秒)', 'catbrain.cat_values.timer_check_seconds', 300, 1, 86400, 1) +
            this._num('更新触发间隔(小时)', 'catbrain.cat_values.update_interval_hours', 12, 1, 720, 1) +
            this._num('哲思触发冷却(分钟)', 'catbrain.cat_values.philosophy_cooldown_minutes', 30, 1, 1440, 1);
        h += this._check('启用二次审查', 'catbrain.cat_values.second_review.enabled', false);
        h += `<div class="form-group"><label>${this._t('二次审查 LLM 类型')}</label>
            <select data-path="catbrain.cat_values.second_review.llm_type">
                <option value="deepseek" ${this._val('catbrain.cat_values.second_review.llm_type','aliyun') === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                <option value="aliyun" ${this._val('catbrain.cat_values.second_review.llm_type','aliyun') === 'aliyun' ? 'selected' : ''}>${this._t('阿里云')}</option>
                <option value="gemini" ${this._val('catbrain.cat_values.second_review.llm_type','aliyun') === 'gemini' ? 'selected' : ''}>Gemini</option>
            </select></div>`;
        return h;
    },

    // 用户记忆,
    catbrain_usermem() {
        const um = this._val('catbrain.user_memory.llm_type', 'deepseek');
        let h = this._section('用户记忆 (user_memory)');
        h += this._num('用户信息更新轮数', 'catbrain.user_memory.update_rounds', 50, 1, 1000, 1);
        h += this._llmTypeSelect('用户记忆 LLM 类型', 'catbrain.user_memory.llm_type', um);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="usermem_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="usermem_aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab" data-tab="usermem_gemini">Gemini</button>
        </div>`;
        h += `<div class="tab-content active" data-tab-content="usermem_ds">` +
            this._password('API Key', 'catbrain.user_memory.deepseek.api_key', '') +
            this._text('Base URL', 'catbrain.user_memory.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'catbrain.user_memory.deepseek.model', 'deepseek-chat') +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="usermem_aliyun">` +
            this._password('API Key', 'catbrain.user_memory.aliyun.api_key', '') +
            this._text('Base URL', 'catbrain.user_memory.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'catbrain.user_memory.aliyun.model', 'qwen-plus') +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="usermem_gemini">` +
            this._password('API Key', 'catbrain.user_memory.gemini.api_key', '') +
            this._text('Base URL', 'catbrain.user_memory.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'catbrain.user_memory.gemini.model', 'gemini-3.6-flash') +
            `</div>`;
        h += this._num('用户记忆温度', 'catbrain.user_memory.temperature', 0.7, 0, 2, 0.1) +
            this._num('用户记忆 max_tokens', 'catbrain.user_memory.max_tokens', 2048, 1, 32768, 16);
        return h;
    },
    _llmTypeSelect(label, path, current) {
        return `<div class="form-group"><label>${label}</label>
            <select data-path="${path}">
                <option value="deepseek" ${current === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                <option value="aliyun" ${current === 'aliyun' ? 'selected' : ''}>${this._t('阿里云')}</option>
                <option value="gemini" ${current === 'gemini' ? 'selected' : ''}>Gemini</option>
            </select></div>`;
    },
    catbrain_rulesbreak(armor) {
        const a = armor || {};
        const armorPrompt = a.prompt || '';
        const armorNapcat = a.prompt_napcat || '';
        const armorNsfw = a.nsfw_personality || '';
        const armorNsfwHobby = a.nsfw_hobby || '';
        const armorNsfwFavorite = a.nsfw_favorite || '';
        const armorNsfwWordNorm = a.nsfw_word_norm || '';
        let h = this._section('原则词（破甲词）');
        h += this._check('QQ 启用', 'rulebreak.enabled_qq', true) +
            this._check('主线程启用', 'rulebreak.enabled_msg', false) +
            this._num('触发好感度下限', 'rulebreak.affinity_min', 3, -10, 10, 1,
                '仅好感度大于该值的用户才允许触发原则词注入');
        h += `<div class="form-group"><label>${this._t('主线程原则词')}</label>
                <textarea id="armorPromptInput" class="auto-grow" rows="3" placeholder="${this._t('守底线的原则词...')}">${this._esc(armorPrompt)}</textarea>
                <div class="help-text">${this._t('主线程检测到色情内容时，插入 system prompt 顶部')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('QQ 原则词')}</label>
                <textarea id="armorNapcatPromptInput" class="auto-grow" rows="3" placeholder="${this._t('守底线的原则词...')}">${this._esc(armorNapcat)}</textarea>
                <div class="help-text">${this._t('QQ 私聊/群聊 @ 检测到色情内容时，插入 system prompt 顶部')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('NSFW 性格（触发时覆盖角色性格）')}</label>
                <textarea id="armorNsfwInput" class="auto-grow" rows="3" placeholder="${this._t('触发破甲词时替换角色卡「角色性格」的内容...')}">${this._esc(armorNsfw)}</textarea>
                <div class="help-text">${this._t('检测到色情内容触发破甲词时，用此内容替换角色卡「角色性格」行，消除调皮/生气等性格冲突')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('NSFW 爱好（触发时覆盖角色爱好）')}</label>
                <textarea id="armorNsfwHobbyInput" class="auto-grow" rows="2" placeholder="${this._t('触发破甲词时替换角色卡「角色爱好」的内容...')}">${this._esc(armorNsfwHobby)}</textarea>
                <div class="help-text">${this._t('检测到色情内容触发破甲词时，用此内容替换角色卡「角色爱好」行')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('NSFW 最喜欢的东西（触发时覆盖）')}</label>
                <textarea id="armorNsfwFavoriteInput" class="auto-grow" rows="2" placeholder="${this._t('触发破甲词时替换角色卡「最喜欢的东西」的内容...')}">${this._esc(armorNsfwFavorite)}</textarea>
                <div class="help-text">${this._t('检测到色情内容触发破甲词时，用此内容替换角色卡「最喜欢的东西」行')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('NSFW 字数规范（触发时覆盖字数限制）')}</label>
                <textarea id="armorNsfwWordNormInput" class="auto-grow" rows="2" placeholder="${this._t('触发破甲词时替换默认字数限制，如：每次回复至少80字，详细描写...')}">${this._esc(armorNsfwWordNorm)}</textarea>
                <div class="help-text">${this._t('检测到色情内容触发破甲词时，用此内容替换「每次回复10个字左右，严格控制在20字以内」')}</div>
            </div>`;
        h += this._section('审查端口（独立 DeepSeek）') +
            this._password('API Key', 'rulebreak.deepseek.api_key', '') +
            this._text('Base URL', 'rulebreak.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'rulebreak.deepseek.model', 'deepseek-chat') +
            this._num('温度', 'rulebreak.deepseek.temperature', 0.3, 0, 2, 0.1) +
            this._num('max_tokens', 'rulebreak.deepseek.max_tokens', 512, 1, 4096, 16);
        return h;
    },

    // ============ TTS（含 SoVITS 服务端 + 参考音频 + 模型配置） ============,
});
