/**
 * Configuration panel generators
 * 与 config.yml 节点一一对应
 */
const Config = {
    cfg: null,

    setConfig(c) { this.cfg = c; },

    _val(path, def) {
        const parts = path.split('.');
        let v = this.cfg;
        for (const p of parts) {
            v = v?.[p];
            if (v === undefined) return def;
        }
        return v;
    },

    _text(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <input type="text" data-path="${path}" value="${v == null ? '' : v}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _num(label, path, def, min, max, step, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <input type="number" data-path="${path}" value="${v == null ? '' : v}" min="${min}" max="${max}" step="${step}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _check(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><div class="checkbox-group">
            <input type="checkbox" data-path="${path}" ${v ? 'checked' : ''}>
            <label>${label}</label></div>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _select(label, path, options, def, help, extraAttr) {
        const v = this._val(path, def);
        const opts = options.map(o => `<option value="${o.value}" ${String(o.value) === String(v) ? 'selected' : ''}>${o.label}</option>`).join('');
        return `<div class="form-group"><label>${label}</label>
            <select data-path="${path}" ${extraAttr || ''}>${opts}</select>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _password(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <input type="password" data-path="${path}" value="${v == null ? '' : v}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _list(label, path, def, help) {
        const v = this._val(path, def) || [];
        const text = Array.isArray(v) ? v.join(', ') : v;
        return `<div class="form-group"><label>${label}</label>
            <input type="text" data-path="${path}" data-list="1" value="${text}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _area(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <textarea class="auto-grow" rows="3" data-path="${path}">${this._esc(v == null ? '' : v)}</textarea>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _wordTagEditor(label, path, def, help, placeholder) {
        const list = (this._val(path, def) || []).filter(x => x != null && String(x).trim());
        const tags = list.map(w =>
            `<span class="split-tag" data-word="${this._escAttr(w)}">${this._esc(w)}<button type="button" class="split-tag-remove">&times;</button></span>`
        ).join('');
        const json = JSON.stringify(list);
        return `<div class="form-group"><label>${label}</label>
            <div class="split-flag-editor" data-word-tag-editor="${path}">
                <div class="split-tags">${tags}</div>
                <div class="split-add-row">
                    <input type="text" class="split-add-input" placeholder="${placeholder || '输入后回车添加'}">
                </div>
                <input type="hidden" data-path="${path}" value='${this._escAttr(json)}'>
            </div>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    // ============ 键值对（dict）可视化编辑器 ============
    _dictHidden(path, obj) {
        const json = JSON.stringify(obj || {});
        const safe = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, '&#39;');
        return `<input type="hidden" data-path="${path}" value='${safe}'>`;
    },

    // 简单键值对编辑器（名 → QQ号），用于 group_bots
    _kvDictEditor(label, path, help, keyLabel, valueLabel) {
        const obj = this._val(path, {}) || {};
        const rows = Object.keys(obj).map(k => this._kvRow(k, obj[k], keyLabel, valueLabel)).join('');
        return `<div class="form-group"><label>${label}</label>
            <div class="kv-editor" data-kv-editor="${path}" data-kv-key-label="${keyLabel}" data-kv-value-label="${valueLabel}">
                ${rows || '<div class="help-text">暂无条目，点击下方按钮添加</div>'}
            </div>
            <button type="button" class="btn btn-secondary" data-kv-add="${path}">添加条目</button>
            ${this._dictHidden(path, obj)}
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _kvRow(key, value, keyLabel, valueLabel) {
        return `<div class="kv-row">
            <input type="text" data-kv-key value="${this._esc(key || '')}" placeholder="${keyLabel}">
            <input type="text" data-kv-value value="${this._esc(value || '')}" placeholder="${valueLabel}">
            <button type="button" class="kv-remove" title="删除">&times;</button>
        </div>`;
    },

    // 每群配置编辑器（群号 → 触发基数 / pass 次数），用于 group_per_group
    _groupConfigEditor(label, path, help) {
        const obj = this._val(path, {}) || {};
        const rows = Object.keys(obj).map(gid => this._groupConfigRow(gid, obj[gid])).join('');
        return `<div class="form-group"><label>${label}</label>
            <div class="kv-editor" data-gc-editor="${path}">
                ${rows || '<div class="help-text">暂无条目，点击下方按钮添加</div>'}
            </div>
            <button type="button" class="btn btn-secondary" data-gc-add="${path}">添加群配置</button>
            ${this._dictHidden(path, obj)}
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _groupConfigRow(gid, cfg) {
        cfg = cfg || {};
        const base = cfg.reply_base != null ? cfg.reply_base : '';
        const pass = cfg.pass_rounds != null ? cfg.pass_rounds : '';
        return `<div class="kv-row kv-row-3">
            <input type="text" data-gc-group value="${this._esc(gid || '')}" placeholder="群号">
            <input type="number" data-gc-base value="${base}" placeholder="触发基数(默认6)">
            <input type="number" data-gc-pass value="${pass}" placeholder="pass次数(默认1)">
            <button type="button" class="kv-remove" title="删除">&times;</button>
        </div>`;
    },

    _section(title) {
        return `<div class="form-section"><h4>${title}</h4></div>`;
    },

    _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },

    _escAttr(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    // ============ 基本设置（根级 + app） ============
    basic() {
        return this._section('基础信息') +
            this._text('AI名称', 'AiName', '喵呜') +
            this._num('API 端口', 'app.port', 1800, 1, 65535, 1);
    },

    // ============ SenseVoice ============
    sensevoice() {
        return this._section('SenseVoice 识别服务') +
            this._check('启用 SenseVoice', 'sensevoice.enabled', false) +
            this._text('WebSocket 服务器地址', 'sensevoice.server_url', 'ws://127.0.0.1:10095/') +
            this._select('识别模式', 'sensevoice.mode', [
                {value:'2pass',label:'2pass'},{value:'offline',label:'offline'},{value:'online',label:'online'}
            ], '2pass') +
            this._num('分块大小(ms)', 'sensevoice.chunk_size_ms', 300, 50, 500, 10) +
            this._select('语言', 'sensevoice.language', [
                {value:'auto',label:'auto'},{value:'zh',label:'zh'},{value:'en',label:'en'},
                {value:'yue',label:'yue'},{value:'ja',label:'ja'},{value:'ko',label:'ko'}
            ], 'auto') +
            this._check('启用标点与逆文本正则化', 'sensevoice.itn', true) +
            this._num('说话人判定阈值', 'sensevoice.speaker_threshold', 0.2, 0, 1, 0.05) +
            this._list('目标说话人（逗号分隔）', 'sensevoice.target_speakers', []) +
            this._list('热词（逗号分隔，每项: 词 权重...）', 'sensevoice.hotwords', []) +
            this._num('VAD 能量阈值', 'sensevoice.vad_energy_threshold', 400, 0, 5000, 50,
                '说话判断阈值（判断是否有语音活动）') +
            this._num('打断阈值', 'sensevoice.interrupt_threshold', 800, 0, 5000, 50,
                '触发 TTS 打断的能量阈值，应比 VAD 阈值更严格（更高），避免轻微噪音误打断') +
            this._num('句子合并延迟(秒)', 'sensevoice.merge_delay', 1.0, 0, 5, 0.1) +
            this._num('静音阈值(秒)', 'sensevoice.silence_threshold', 2.0, 0, 5, 0.1) +
            this._num('心跳间隔(秒)', 'sensevoice.ping_interval', 20, 1, 120, 1) +
            this._num('心跳超时(秒)', 'sensevoice.ping_timeout', 60, 1, 300, 1) +
            this._section('易错词替换（上=正确词，下=错误词）') +
            `<div id="replaceRulesList"></div>
            <button class="btn btn-secondary" id="addReplaceRuleBtn">添加规则</button>`;
    },

    // 易错词替换编辑器：正确词 -> 多个错误词
    replaceRulesPanel(data) {
        const rules = data || {};
        let h = '';
        Object.keys(rules).forEach(correct => {
            const wrongs = Array.isArray(rules[correct]) ? rules[correct] : [];
            h += this.replaceRuleRow(correct, wrongs);
        });
        if (!Object.keys(rules).length) {
            h += `<div class="help-text">暂无替换规则，点击下方按钮添加</div>`;
        }
        return h;
    },

    replaceRuleRow(correct, wrongs) {
        const wrongTags = (wrongs || []).map(w =>
            `<span class="split-tag" data-wrong="${this._esc(w)}">${this._esc(w)}<button type="button" class="split-tag-remove">&times;</button></span>`
        ).join('');
        return `<div class="replace-rule-row">
            <div class="form-group"><label>正确词</label>
                <input type="text" data-replace-correct value="${this._esc(correct || '')}"></div>
            <div class="form-group"><label>错误词（回车添加，点击 × 删除）</label>
                <div class="split-flag-editor replace-wrong-editor">
                    <div class="split-tags replace-wrong-tags">${wrongTags}</div>
                    <div class="split-add-row">
                        <input type="text" class="split-add-input replace-wrong-input" placeholder="输入错误词后回车添加" maxlength="20">
                    </div>
                </div>
            </div>
        </div>`;
    },

    collectReplaceRules() {
        const result = {};
        document.querySelectorAll('#replaceRulesList .replace-rule-row').forEach(row => {
            const correct = row.querySelector('[data-replace-correct]').value.trim();
            if (!correct) return;
            const wrongs = [];
            row.querySelectorAll('.replace-wrong-tags .split-tag').forEach(t => {
                const w = t.dataset.wrong;
                if (w) wrongs.push(w);
            });
            result[correct] = wrongs;
        });
        return result;
    },

    // ============ 声纹管理面板 ============
    speakerManager() {
        return `<div class="form-section"><h4>声纹管理</h4></div>
            <div id="speakerList" class="speaker-list"><div class="help-text">加载中...</div></div>
            <div class="speaker-actions">
                <button class="btn btn-primary" id="speakerBuildBtn">一键生成所有声纹</button>
                <button class="btn btn-secondary" id="speakerCreateBtn">新建用户</button>
            </div>
            <div id="speakerBuildProgress" class="help-text" style="margin-top:8px;"></div>`;
    },

    // ============ LLM ============
    llm_model() {
        const type = this._val('llm.local_llm_type', 'deepseek');
        let h = this._section('LLM 大模型') +
            `<div class="form-group"><label>LLM类型</label>
            <select data-path="llm.local_llm_type">
                <option value="deepseek" ${type === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                <option value="aliyun" ${type === 'aliyun' ? 'selected' : ''}>阿里云</option>
            </select></div>`;

        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="deepseek">DeepSeek</button>
            <button class="modal-tab" data-tab="aliyun">阿里云</button>
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
            `<div class="form-group"><label>前置词（行为约束，system prompt 最前）</label>
                <textarea id="frontPromptInput" class="auto-grow" rows="3" placeholder="一次回复不要一次性解决复杂问题...">${this._esc(frontPrompt)}</textarea>
                <div class="help-text">放在 system prompt 最前面，约束本次回复行为</div>
            </div>` +
            `<div class="form-group"><label>主动回复前置词</label>
                <textarea id="activeFrontPromptInput" class="auto-grow" rows="2" placeholder="一次回复不要一次性解决复杂问题...">${this._esc(activeFront)}</textarea>
                <div class="help-text">主动找话题时的行为约束</div>
            </div>` +
            `<div class="form-group"><label>NapCat 前置词</label>
                <textarea id="napcatFrontPromptInput" class="auto-grow" rows="2" placeholder="一次回复不要一次性解决复杂问题...">${this._esc(napcatFront)}</textarea>
                <div class="help-text">QQ 回复时的行为约束</div>
            </div>` +
            `<div class="form-group"><label>后置词（人设，system prompt 最后）</label>
                <textarea id="postPromptInput" class="auto-grow" rows="2" placeholder="你是...，大家都叫你...">${this._esc(postPrompt)}</textarea>
                <div class="help-text">放在 system prompt 最后，描述角色身份</div>
            </div>`;
    },

    _narrationFormula() {
        return `<div class="formula-box">
            <div class="formula-box-title">计算公式</div>
            <div class="formula-block">
                <div class="formula-row">
                    <span class="formula-name">水词密度分</span>
                    <span class="formula-expr">Density = 100 − ( W / L × 100 )</span>
                    <span class="formula-cond">若 W / L ≥ θ 则 Density = 0</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">超长惩罚</span>
                    <span class="formula-expr">Penalty = 0，当 L ≤ L<sub>0</sub></span>
                    <span class="formula-expr">Penalty = min( P<sub>cap</sub>, ( L − L<sub>0</sub> ) × r )，当 L &gt; L<sub>0</sub></span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">原始得分</span>
                    <span class="formula-expr">Raw<sub>t</sub> = max( 0, Density − Penalty )</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">平滑得分</span>
                    <span class="formula-expr">S<sub>t</sub> = λ · S<sub>t−1</sub> + ( 1 − λ ) · Raw<sub>t</sub></span>
                    <span class="formula-cond">λ = 0.75（下降）/ 0.55（上升）/ 0.70（相等）</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">清洗档位</span>
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

    // 分割符编辑器：每个符号单独展示为小块，隐藏 input 保存 | 分隔的字符串
    splitFlagEditor(path) {
        const raw = this._val(path, ',|，|。|!|！|?|？');
        const chars = String(raw || '').split('|').filter(c => c !== '');
        const tags = chars.map(c =>
            `<span class="split-tag" data-char="${c}">${c}<button type="button" class="split-tag-remove">&times;</button></span>`
        ).join('');
        return `<div class="form-group"><label>分割符（点击 × 删除）</label>
            <div class="split-flag-editor" data-split-flag-editor="${path}">
                <div class="split-tags">${tags}</div>
                <div class="split-add-row">
                    <input type="text" class="split-add-input" placeholder="输入一个符号后回车添加" maxlength="2">
                </div>
                <input type="hidden" data-path="${path}" value="${raw}">
            </div>
            <div class="help-text">每个符号单独作为一个分段点，例如逗号、句号、感叹号</div>
        </div>`;
    },

    // ============ CatBrain 子模块（四球分别打开） ============
    // 长期记忆
    catbrain_ltmem() {
        return this._section('长期记忆 (long_term_mem)') +
            this._num('长期记忆回溯天数', 'catbrain.long_term_mem.memory_days', 300, 1, 3650, 1);
    },

    // 记忆摘要
    catbrain_abstract() {
        const ab = this._val('catbrain.abstract_mem.llm_type', 'deepseek');
        let h = this._section('记忆摘要 (abstract_mem)');
        h += this._num('摘要触发条数', 'catbrain.abstract_mem.summary_rounds', 30, 1, 500, 1,
            '这里指单条消息数（user/assistant 各算一条），与短期记忆的"轮数"不同：短期记忆一轮 = 用户 + AI 两条') +
            this._num('摘要检索条数上限', 'catbrain.abstract_mem.summary_top_limit', 20, 1, 200, 1) +
            this._num('话题更新间隔(秒)', 'catbrain.abstract_mem.topic_update_interval', 60, 1, 3600, 1);
        h += this._llmTypeSelect('摘要 LLM 类型', 'catbrain.abstract_mem.llm_type', ab);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="abstract_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="abstract_aliyun">阿里云</button>
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
        return h;
    },

    // 价值观
    catbrain_values() {
        const cv = this._val('catbrain.cat_values.llm_type', 'deepseek');
        let h = this._section('价值观 (cat_values)');
        h += this._llmTypeSelect('价值观 LLM 类型', 'catbrain.cat_values.llm_type', cv);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="values_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="values_aliyun">阿里云</button>
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
        h += this._num('价值观 max_tokens', 'catbrain.cat_values.max_tokens', 8192, 1, 65536, 16) +
            this._num('工具调用最大轮数', 'catbrain.cat_values.max_tool_rounds', 100, 1, 1000, 1) +
            this._num('计时检查间隔(秒)', 'catbrain.cat_values.timer_check_seconds', 300, 1, 86400, 1) +
            this._num('更新触发间隔(小时)', 'catbrain.cat_values.update_interval_hours', 12, 1, 720, 1) +
            this._num('哲思触发冷却(分钟)', 'catbrain.cat_values.philosophy_cooldown_minutes', 30, 1, 1440, 1);
        h += this._check('启用二次审查', 'catbrain.cat_values.second_review.enabled', false);
        h += `<div class="form-group"><label>二次审查 LLM 类型</label>
            <select data-path="catbrain.cat_values.second_review.llm_type">
                <option value="deepseek" ${this._val('catbrain.cat_values.second_review.llm_type','aliyun') === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                <option value="aliyun" ${this._val('catbrain.cat_values.second_review.llm_type','aliyun') === 'aliyun' ? 'selected' : ''}>阿里云</option>
            </select></div>`;
        return h;
    },

    // 用户记忆
    catbrain_usermem() {
        const um = this._val('catbrain.user_memory.llm_type', 'deepseek');
        let h = this._section('用户记忆 (user_memory)');
        h += this._num('用户信息更新轮数', 'catbrain.user_memory.update_rounds', 50, 1, 1000, 1);
        h += this._llmTypeSelect('用户记忆 LLM 类型', 'catbrain.user_memory.llm_type', um);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="usermem_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="usermem_aliyun">阿里云</button>
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
        h += this._num('用户记忆温度', 'catbrain.user_memory.temperature', 0.7, 0, 2, 0.1) +
            this._num('用户记忆 max_tokens', 'catbrain.user_memory.max_tokens', 2048, 1, 32768, 16);
        return h;
    },

    _llmTypeSelect(label, path, current) {
        return `<div class="form-group"><label>${label}</label>
            <select data-path="${path}">
                <option value="deepseek" ${current === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                <option value="aliyun" ${current === 'aliyun' ? 'selected' : ''}>阿里云</option>
            </select></div>`;
    },

    // ============ TTS（含 SoVITS 服务端 + 参考音频 + 模型配置） ============
    tts() {
        return this._section('TTS 语音合成') +
            this._select('语音合成引擎', 'tts.select', [{value:'gpt-sovits',label:'GPT-SoVITS'}], 'gpt-sovits') +
            this._text('GPT-SoVITS 服务地址', 'tts.gpt-sovits.gpt_sovits_url', 'http://127.0.0.1:9880') +
            this._text('输出目录', 'tts.output_dir', './output') +
            this._num('音量', 'tts.volume', 1.0, 0, 2, 0.1) +
            this._num('合成线程数', 'tts.synth_workers', 2, 1, 8, 1) +
            this._select('打断模式', 'tts.interrupt.mode', [
                {value:'pipeline',label:'pipeline'},{value:'keyboard',label:'keyboard'},{value:'off',label:'off'}
            ], 'pipeline') +
            this._text('打断按键', 'tts.interrupt.key', 'f8') +
            this._num('打断轮询间隔(秒)', 'tts.interrupt.poll_interval', 0.1, 0.01, 1, 0.01) +
            `<div id="refAudioPanel"></div><div id="ttsModelPanel"></div>`;
    },

    // ============ TTS 子球：模型配置（参考音频 + 模型权重） ============
    tts_model_panel(data, models) {
        const c = data || {};
        const ckpts = (models && models.ckpt) || [];
        const pths = (models && models.pth) || [];
        let h = this._section('参考音频配置（按角色名绑定）');
        h += `<div id="refAudioPanel"></div>`;
        h += this._section('GPT-SoVITS 模型权重 (tts_infer.yaml)');
        h += `<div class="form-group"><label>版本</label>
            <select data-tts-model="version">
                <option value="v2" ${c.version === 'v2' ? 'selected' : ''}>v2</option>
                <option value="v2Pro" ${c.version !== 'v2' ? 'selected' : ''}>v2Pro</option>
            </select></div>`;
        h += this._modelSelect('GPT 权重 (ckpt)', 't2s_weights_path', ckpts, c.t2s_weights_path);
        h += this._modelSelect('SoVITS 权重 (pth)', 'vits_weights_path', pths, c.vits_weights_path);
        h += `<div class="form-group"><label>设备</label>
            <select data-tts-model="device">
                <option value="cuda" ${c.device === 'cuda' ? 'selected' : ''}>cuda</option>
                <option value="cpu" ${c.device === 'cpu' ? 'selected' : ''}>cpu</option>
            </select></div>`;
        h += `<div class="checkbox-group"><input type="checkbox" data-tts-model="is_half" ${c.is_half !== false ? 'checked' : ''}><label>半精度</label></div>`;
        return h;
    },

    // ============ TTS 子球：参数配置（合成参数 + 流式参数 + 播放） ============
    tts_params_panel(data) {
        const d = data || {};
        let h = this._section('合成参数 (tts_infer.yaml)');
        h += `<div class="form-group"><label>语速</label>
            <input type="number" data-tts-model="speed_factor" value="${d.speed_factor != null ? d.speed_factor : 1.0}" step="0.1" min="0.5" max="2"></div>`;
        h += `<div class="form-group"><label>温度</label>
            <input type="number" data-tts-model="temperature" value="${d.temperature != null ? d.temperature : 1.0}" step="0.1" min="0" max="2"></div>`;
        h += `<div class="form-group"><label>Top K</label>
            <input type="number" data-tts-model="top_k" value="${d.top_k != null ? d.top_k : 15}" step="1" min="1" max="50"></div>`;
        h += `<div class="form-group"><label>Top P</label>
            <input type="number" data-tts-model="top_p" value="${d.top_p != null ? d.top_p : 1.0}" step="0.05" min="0" max="1"></div>`;
        h += `<div class="form-group"><label>切分方式</label>
            <input type="text" data-tts-model="text_split_method" value="${d.text_split_method || 'cut5'}"></div>`;

        h += this._section('流式参数 (config.yml)');
        h += this._num('语义 token 块长度', 'tts.gpt-sovits.min_chunk_length', 12, 1, 50, 1,
            '越小首包越快，越大越流畅');
        h += this._num('块间重叠 token 数', 'tts.gpt-sovits.overlap_length', 2, 0, 10, 1,
            '越大块间衔接越自然');
        h += this._num('输出采样率', 'tts.gpt-sovits.sample_rate', 32000, 8000, 48000, 1000,
            'v2Pro 流式输出固定 32000');

        h += this._section('播放与合成 (config.yml)');
        h += this._num('音量', 'tts.volume', 1.0, 0, 2, 0.1);
        h += this._num('合成线程数', 'tts.synth_workers', 2, 1, 8, 1);
        return h;
    },

    // ============ TTS 子球：配置（打断 + 流式开关 + 服务引擎） ============
    tts_config_panel() {
        return this._section('流式开关') +
            this._select('流式模式', 'tts.gpt-sovits.streaming_mode', [
                { value: '0', label: '关闭（整段合成）' },
                { value: '2', label: '智能流式（静音点切分）' },
                { value: '3', label: '定长流式（响应更快）' }
            ], '2', '2=按静音点切分听感连贯，3=定长切分响应更快') +
            this._select('媒体类型', 'tts.gpt-sovits.media_type', [
                { value: 'raw', label: 'raw（裸 PCM）' },
                { value: 'wav', label: 'wav（带 wav 头）' }
            ], 'raw', '流式推荐 raw，避免每块 wav 头解析') +
            this._num('段尾静音(秒)', 'tts.gpt-sovits.fragment_interval', 0, 0, 2, 0.1,
                '流式下必须为 0，否则段尾会有静音') +
            this._select('合成文本语言', 'tts.gpt-sovits.text_lang', [
                { value: 'zh', label: '中文 zh（最稳，可读短英文词）' },
                { value: 'auto', label: '自动 auto（中英混合，可能误判成日文）' },
                { value: 'en', label: '英文 en' }
            ], 'zh', '中文为主建议 zh，避免 auto 误判成日语出现伪日文') +
            this._check('整段语言自动切换', 'tts.gpt-sovits.lang_judge_enabled', true,
                '仅当整段是英文/日文时自动切换语言，其余仍用上方默认语言') +
            this._section('打断') +
            this._select('打断模式', 'tts.interrupt.mode', [
                { value: 'pipeline', label: 'pipeline（说话打断）' },
                { value: 'keyboard', label: 'keyboard（按键打断）' },
                { value: 'off', label: 'off（关闭）' }
            ], 'pipeline') +
            this._text('打断按键', 'tts.interrupt.key', 'f8') +
            this._num('打断轮询间隔(秒)', 'tts.interrupt.poll_interval', 0.1, 0.01, 1, 0.01) +
            this._section('服务与引擎') +
            this._select('语音合成引擎', 'tts.select', [{ value: 'gpt-sovits', label: 'GPT-SoVITS' }], 'gpt-sovits') +
            this._text('GPT-SoVITS 服务地址', 'tts.gpt-sovits.gpt_sovits_url', 'http://127.0.0.1:9880') +
            this._text('输出目录', 'tts.output_dir', './output');
    },

    // 参考音频配置面板（异步加载 ref_audio/config.json 后填充）
    refAudioPanel(data) {
        const map = data || {};
        let h = this._section('参考音频配置（按角色名绑定）');
        Object.keys(map).forEach(name => {
            const item = map[name] || {};
            h += `<div class="char-card">
                <div class="char-card-title">${name}</div>
                <div class="form-group"><label>音频路径</label>
                    <input type="text" data-ref-audio-name="${name}" data-ref-audio-field="audio" value="${item.audio || ''}"></div>
                <div class="form-group"><label>参考文本</label>
                    <textarea class="auto-grow" rows="2" data-ref-audio-name="${name}" data-ref-audio-field="text">${this._esc(item.text || '')}</textarea></div>
                <div class="form-group"><label>语言</label>
                    <input type="text" data-ref-audio-name="${name}" data-ref-audio-field="lang" value="${item.lang || 'zh'}"></div>
            </div>`;
        });
        if (!Object.keys(map).length) {
            h += `<div class="help-text">暂无参考音频配置</div>`;
        }
        return h;
    },

    // TTS 模型配置面板（异步加载 tts_infer.yaml 后填充，扁平结构）
    ttsModelPanel(data, models) {
        const c = data || {};
        const ckpts = (models && models.ckpt) || [];
        const pths = (models && models.pth) || [];
        let h = this._section('GPT-SoVITS 模型配置 (tts_infer.yaml)');
        h += `<div class="form-group"><label>版本</label>
            <select data-tts-model="version">
                <option value="v2" ${c.version === 'v2' ? 'selected' : ''}>v2</option>
                <option value="v2Pro" ${c.version !== 'v2' ? 'selected' : ''}>v2Pro</option>
            </select></div>`;
        h += this._modelSelect('GPT 权重 (ckpt)', 't2s_weights_path', ckpts, c.t2s_weights_path);
        h += this._modelSelect('SoVITS 权重 (pth)', 'vits_weights_path', pths, c.vits_weights_path);
        h += `<div class="form-group"><label>设备</label>
            <select data-tts-model="device">
                <option value="cuda" ${c.device === 'cuda' ? 'selected' : ''}>cuda</option>
                <option value="cpu" ${c.device === 'cpu' ? 'selected' : ''}>cpu</option>
            </select></div>`;
        h += `<div class="checkbox-group"><input type="checkbox" data-tts-model="is_half" ${c.is_half !== false ? 'checked' : ''}><label>半精度</label></div>`;
        h += `<div class="form-group"><label>语速</label>
            <input type="number" data-tts-model="speed_factor" value="${data.speed_factor != null ? data.speed_factor : 1.0}" step="0.1" min="0.5" max="2"></div>`;
        h += `<div class="form-group"><label>温度</label>
            <input type="number" data-tts-model="temperature" value="${data.temperature != null ? data.temperature : 1.0}" step="0.1" min="0" max="2"></div>`;
        h += `<div class="form-group"><label>Top K</label>
            <input type="number" data-tts-model="top_k" value="${data.top_k != null ? data.top_k : 15}" step="1" min="1" max="50"></div>`;
        h += `<div class="form-group"><label>Top P</label>
            <input type="number" data-tts-model="top_p" value="${data.top_p != null ? data.top_p : 1.0}" step="0.05" min="0" max="1"></div>`;
        h += `<div class="form-group"><label>切分方式</label>
            <input type="text" data-tts-model="text_split_method" value="${data.text_split_method || 'cut5'}"></div>`;
        return h;
    },

    _modelSelect(label, field, options, current) {
        let opts = `<option value="">（不选择）</option>`;
        options.forEach(o => {
            opts += `<option value="${o}" ${o === current ? 'selected' : ''}>${o}</option>`;
        });
        return `<div class="form-group"><label>${label}</label>
            <select data-tts-model="${field}">${opts}</select></div>`;
    },

    // ============ 弹幕 ============
    danmaku() {
        const sessdata = this._val('danmaku.blivedm.sessdata', '');
        return this._section('B站弹幕（连接）') +
            this._check('启用弹幕模块', 'danmaku.blivedm.enabled', false,
                '开启后独立后台线程连接直播间，默认走开放平台，SESSDATA 作为兜底') +
            this._text('直播间号', 'danmaku.blivedm.room_id', '') +
            `<div class="form-group"><label>SESSDATA（兜底通道）</label>
                <div class="verify-row">
                    <input type="text" data-path="danmaku.blivedm.sessdata" value="${this._esc(sessdata)}">
                    <button type="button" class="btn btn-secondary sessdata-verify-btn">验证</button>
                    <button type="button" class="btn btn-primary bili-login-btn" data-target="danmaku">扫码登录</button>
                </div>
                <div class="sessdata-verify-result help-text"></div>
            </div>` +
            this._text('bili_jct', 'danmaku.blivedm.bili_jct', '',
                '发弹幕/表情必需的 csrf 令牌，登录 bilibili.com → F12 → Cookies 中复制') +
            this._text('ACCESS_KEY_ID', 'danmaku.blivedm.ACCESS_KEY_ID', '') +
            this._password('ACCESS_KEY_SECRET', 'danmaku.blivedm.ACCESS_KEY_SECRET', '') +
            this._text('APP_ID', 'danmaku.blivedm.APP_ID', '') +
            this._text('ROOM_OWNER_AUTH_CODE', 'danmaku.blivedm.ROOM_OWNER_AUTH_CODE', '') +
            this._section('弹幕朗读与回复') +
            this._check('朗读弹幕', 'danmaku.read_aloud_enabled', true,
                '回复前先朗读弹幕原文，与 AI 回复串成同一连续任务') +
            this._select('朗读模板', 'danmaku.read_aloud_mode', [
                { value: 'random', label: '随机' },
                { value: 'template1', label: '{username}说:{内容}' },
                { value: 'template2', label: '{内容}，来自{username}' },
                { value: 'template3', label: '我来看看，{username}说：{内容}' }
            ], 'random') +
            this._check('SC 也走 LLM 回复', 'danmaku.sc_llm_reply_enabled', false,
                '默认关闭，SC 仅朗读；开启后 SC 朗读 + LLM 回复') +
            this._select('多条弹幕策略', 'danmaku.multi_danmaku_strategy', [
                { value: 'longest', label: '选最长一条' },
                { value: 'newest', label: '选最新一条' },
                { value: 'all', label: '全部统一回复' },
                { value: 'random', label: '随机方案' }
            ], 'random') +
            this._num('全部回复字符上限', 'danmaku.multi_danmaku_char_limit', 200, 1, 2000, 10,
                'all 策略总字符数超过该值时自动回退到选最长一条') +
            this._section('弹幕记忆') +
            this._num('弹幕短期记忆上限(条)', 'danmaku.memory_short_limit', 40, 1, 500, 1,
                '弹幕专属短期记忆，按条计数，超出删最旧') +
            this._check('弹幕长期记忆', 'danmaku.ltmem_enabled', true,
                '关闭后弹幕不写长期记忆与摘要缓存（用户记忆不受影响）') +
            this._section('礼物与主动发送') +
            this._check('礼物/舰长感谢', 'danmaku.gift_thanks_enabled', true,
                '收到礼物/舰长时由 AI 拟感谢词并语音播报') +
            this._check('主动发弹幕', 'danmaku.active_send.enabled', true,
                '允许 AI 主动在直播间发弹幕（触发型工具）') +
            this._num('主动发弹幕冷却(秒)', 'danmaku.active_send.cooldown', 60, 0, 600, 1);
    },

    // ============ VTuber / VTS 子球：配置（连接 + 身体 + 嘴部） ============
    vts_config() {
        let h = this._section('VTuber / VTube Studio 连接') +
            this._check('启用 VTuber 控制', 'emote.switch', false) +
            this._text('WebSocket 地址', 'emote.vtuber_websocket', '127.0.0.1:8001') +
            this._text('插件名称', 'emote.vtuber_pluginName', '') +
            this._text('插件开发者', 'emote.vtuber_pluginDeveloper', '') +
            this._text('认证令牌', 'emote.vtuber_authenticationToken', '');

        h += this._section('身体左右摆动（说话时随机抖动，活泼跳跃感）') +
            this._check('启用身体摆动', 'emote.body_sway.enabled', true) +
            this._text('摆动参数名', 'emote.body_sway.parameter', 'FaceAngleX') +
            this._num('基准值', 'emote.body_sway.base', 0.0, -1, 1, 0.01) +
            this._num('常规幅度', 'emote.body_sway.amplitude', 0.18, 0, 1, 0.01) +
            this._num('跳跃峰值幅度', 'emote.body_sway.jump_amplitude', 0.6, 0, 1, 0.01) +
            this._num('跳跃概率(0~1)', 'emote.body_sway.jump_probability', 0.2, 0, 1, 0.05) +
            this._num('刷新周期(ms)', 'emote.body_sway.interval_ms', 100, 20, 500, 10);

        h += this._section('嘴部同步（仅由 TTS 播放器驱动）') +
            this._check('启用嘴部同步', 'emote.mouth_sync.enabled', true) +
            this._text('嘴部参数名', 'emote.mouth_sync.parameter', 'MouthOpen') +
            this._num('张嘴下限', 'emote.mouth_sync.min', 0.25, 0, 1, 0.01) +
            this._num('张嘴上限', 'emote.mouth_sync.max', 1.0, 0, 1, 0.01) +
            this._num('闭嘴值', 'emote.mouth_sync.close', 0.0, 0, 1, 0.01) +
            this._num('刷新周期(ms)', 'emote.mouth_sync.interval_ms', 90, 20, 500, 10);

        return h;
    },

    // ============ 桌宠子球：配置（连接 + 身体 + 嘴部 + 表情） ============
    desktopet_config() {
        let h = this._section('桌宠连接（Live2D 桌宠，复用 VTS 协议）') +
            this._check('启用桌宠控制', 'desktopet_emote.switch', false) +
            this._text('WebSocket 地址', 'desktopet_emote.vtuber_websocket', '127.0.0.1:8002') +
            this._text('插件名称', 'desktopet_emote.vtuber_pluginName', '') +
            this._text('插件开发者', 'desktopet_emote.vtuber_pluginDeveloper', '') +
            this._text('认证令牌', 'desktopet_emote.vtuber_authenticationToken', '');

        h += this._section('身体左右摆动（说话时随机抖动，活泼跳跃感）') +
            this._check('启用身体摆动', 'desktopet_emote.body_sway.enabled', true) +
            this._text('摆动参数名', 'desktopet_emote.body_sway.parameter', 'FaceAngleX') +
            this._num('基准值', 'desktopet_emote.body_sway.base', 0.0, -1, 1, 0.01) +
            this._num('常规幅度', 'desktopet_emote.body_sway.amplitude', 0.18, 0, 1, 0.01) +
            this._num('跳跃峰值幅度', 'desktopet_emote.body_sway.jump_amplitude', 0.6, 0, 1, 0.01) +
            this._num('跳跃概率(0~1)', 'desktopet_emote.body_sway.jump_probability', 0.2, 0, 1, 0.05) +
            this._num('刷新周期(ms)', 'desktopet_emote.body_sway.interval_ms', 100, 20, 500, 10);

        h += this._section('嘴部同步（仅由 TTS 播放器驱动）') +
            this._check('启用嘴部同步', 'desktopet_emote.mouth_sync.enabled', true) +
            this._text('嘴部参数名', 'desktopet_emote.mouth_sync.parameter', 'MouthOpen') +
            this._num('张嘴下限', 'desktopet_emote.mouth_sync.min', 0.25, 0, 1, 0.01) +
            this._num('张嘴上限', 'desktopet_emote.mouth_sync.max', 1.0, 0, 1, 0.01) +
            this._num('闭嘴值', 'desktopet_emote.mouth_sync.close', 0.0, 0, 1, 0.01) +
            this._num('刷新周期(ms)', 'desktopet_emote.mouth_sync.interval_ms', 90, 20, 500, 10);

        const slots = this._val('desktopet_emote.emotion_slots', {}) || {};
        const emotions = ['happy', 'sad', 'call', 'angry', 'blush', 'approve', 'sweat', 'blood', 'love', 'wordless'];
        const tiers = [
            { key: 'weak', label: '弱' },
            { key: 'strong', label: '强' }
        ];
        let rows = '';
        emotions.forEach(emo => {
            tiers.forEach(tier => {
                const key = `${emo}_${tier.key}`;
                rows += this._desktopetEmotionSlotRow(key, slots[key]);
            });
        });
        h += this._section('表情绑定（左：槽位ID，右：桌宠热键ID）') +
            '<div class="emotion-slots">' +
                '<div class="emotion-slots-head"><span>槽位 ID</span><span>桌宠热键 ID</span></div>' +
                rows +
            '</div>' +
            '<div class="help-text">槽位 id = 情绪 + 强度档；强度固定 &lt;3=weak、≥3=strong。右侧填桌宠（模型 vtube.json）里配置的热键 ID。</div>';

        return h;
    },

    _desktopetEmotionSlotRow(key, val) {
        return `<div class="emotion-slot-row">
            <span class="emotion-slot-id">${key}</span>
            <input type="text" data-path="desktopet_emote.emotion_slots.${key}" value="${this._esc(val || '')}" placeholder="桌宠 hotkeyID">
        </div>`;
    },

    // ============ VTuber / VTS 子球：表情绑定（左右：左id右内容） ============
    vts_emotion() {
        const slots = this._val('emote.emotion_slots', {}) || {};
        const emotions = ['happy', 'sad', 'call', 'angry', 'blush', 'approve', 'sweat', 'blood', 'love', 'wordless'];
        const tiers = [
            { key: 'weak', label: '弱' },
            { key: 'strong', label: '强' }
        ];
        let rows = '';
        emotions.forEach(emo => {
            tiers.forEach(tier => {
                const key = `${emo}_${tier.key}`;
                rows += this._emotionSlotRow(key, slots[key]);
            });
        });
        return this._section('表情绑定（左：槽位ID，右：VTS 热键ID）') +
            '<div class="emotion-slots">' +
                '<div class="emotion-slots-head"><span>槽位 ID</span><span>VTS 热键 ID</span></div>' +
                rows +
            '</div>' +
            '<div class="help-text">槽位 id = 情绪 + 强度档；强度固定 &lt;3=weak、≥3=strong。右侧填 VTS 里配置的热键 ID。</div>';
    },

    _emotionSlotRow(key, val) {
        return `<div class="emotion-slot-row">
            <span class="emotion-slot-id">${key}</span>
            <input type="text" data-path="emote.emotion_slots.${key}" value="${this._esc(val || '')}" placeholder="VTS hotkeyID">
        </div>`;
    },

    // ============ VTuber / VTS 子球：参数查询 ============
    vts_params() {
        return this._section('VTS 模型参数查询') +
            '<div class="vts-params-toolbar">' +
                '<button type="button" class="btn btn-primary" data-vts-query>查询模型参数</button>' +
            '</div>' +
            '<div class="vts-params-result" data-vts-params-result>' +
                '<div class="help-text">点击上方按钮查询 VTS 当前模型的可用输入参数（含嘴部、身体角度等）。</div>' +
            '</div>';
    },

    _vtsParamsTable(data, params) {
        const model = (data && data.model_name) || '未知模型';
        const live2d = (params && params.live2d_parameters) || [];
        const tracking = (params && params.tracking_parameters) || [];
        const row = (p, source) => {
            const val = p.value != null ? p.value : '-';
            const min = p.min != null ? p.min : '-';
            const max = p.max != null ? p.max : '-';
            const def = p.default != null ? p.default : '-';
            return `<tr><td>${this._esc(p.name)}</td><td>${this._esc(source)}</td><td>${this._esc(val)}</td><td>${this._esc(min)}</td><td>${this._esc(max)}</td><td>${this._esc(def)}</td></tr>`;
        };
        const rows = live2d.map(p => row(p, 'Live2D模型')).join('') +
                     tracking.map(p => row(p, '追踪参数')).join('');
        return `<div class="vts-params-model">模型：${this._esc(model)}（Live2D参数 ${live2d.length} 个，追踪参数 ${tracking.length} 个）</div>
            <table class="vts-params-table">
                <thead><tr><th>参数名</th><th>来源</th><th>当前值</th><th>最小值</th><th>最大值</th><th>默认值</th></tr></thead>
                <tbody>${rows || '<tr><td colspan="6">未返回参数</td></tr>'}</tbody>
            </table>`;
    },

    // ============ NapCat（QQ 机器人）子球 ============
    napcat() {
        // 总览（向后兼容，实际由四个子球分别配置）
        return this.napcat_account() + this.napcat_private() + this.napcat_group() + this.napcat_send();
    },

    napcat_account() {
        return this._section('NapCat 连接与角色名') +
            this._check('启用 NapCat', 'napcat.enabled', false) +
            this._text('WebSocket 地址', 'napcat.ws_url', 'ws://127.0.0.1:3001') +
            this._password('Access Token（可空）', 'napcat.access_token', '') +
            this._text('角色名（群内 @ 该昵称触发立即回复）', 'napcat.self_nickname', '喵利呜西斯') +
            this._check('调试：原始事件落盘', 'napcat.debug_event_dump', false,
                '开启后把 NapCat 原始事件写入 .temp/napcat_raw_events.jsonl（用于拿群机器人消息样本）');
    },

    napcat_private() {
        return this._section('NapCat 私聊回复') +
            this._check('启用私聊回复', 'napcat.private_reply_enabled', true) +
            this._num('拉取历史条数', 'napcat.history_limit', 30, 1, 200, 1,
                '向上获取的聊天记录条数，作为 napcat 私聊回复的短期记忆') +
            this._num('短期记忆轮数', 'napcat.short_mem_rounds', 30, 1, 200, 1,
                'qq_response 类型短期记忆保留轮数（1 轮 = 用户 + AI），不成对的孤立消息按条数兜底裁剪') +
            this._check('启用短期记忆', 'napcat.short_mem_enabled', true) +
            this._check('启用长期记忆', 'napcat.ltmem_enabled', false) +
            this._select('深度思考级别', 'napcat.thinking_level', [
                { value: 'off', label: '关闭' },
                { value: 'low', label: '低' },
                { value: 'medium', label: '中' },
                { value: 'high', label: '高' }
            ], 'medium', 'DeepSeek/Aliyun 当前仅支持开/关，medium 及以上均开启思考') +
            this._num('回复字数', 'napcat.reply_word_count', 10, 1, 100, 1,
                '每次回复约该字数，严格上限 = 该值 + 10') +
            this._check('启用表情发送', 'napcat.emote_enabled', true) +
            this._num('表情触发概率(%)', 'napcat.emote_probability', 30, 0, 100, 1,
                '最终概率 = 配置概率 + 用户好感度') +
            this._text('表情文件目录', 'napcat.emote_dir', '.NapCat/EmoteLab');
    },

    napcat_group() {
        return this._section('NapCat 群聊回复') +
            this._check('启用群聊回复', 'napcat.group_reply_enabled', true) +
            this._list('群聊名称黑名单（逗号分隔，空=不拦截）', 'napcat.group_blacklist', []) +
            this._num('群聊历史拉取条数', 'napcat.group_history_limit', 50, 1, 500, 1,
                'get_group_record 向上获取的群聊历史条数（content 标注【用户名】:内容）') +
            this._num('群聊短期记忆容纳条数', 'napcat.group_memory_limit', 10, 1, 200, 1,
                'qq_groupchat 类型仅存 assistant 消息，最多容纳条数') +
            this._kvDictEditor('群机器人映射（机器人名 → QQ号）', 'napcat.group_bots', {},
                '识别群机器人，如 幻梦 → 3889006601', '机器人名', 'QQ号') +
            this._section('群聊主动插话（按消息数判断）') +
            this._check('启用群聊主动插话', 'napcat.group_active_enabled', true) +
            this._num('触发基数（更新 N 次后判断）', 'napcat.group_reply_base', 6, 1, 100, 1,
                '群聊消息累计该次数后由 AI 判断是否插话') +
            this._num('触发抖动比例(±)', 'napcat.group_reply_jitter', 0.2, 0, 0.5, 0.05,
                '实际阈值 = 基数 ± 该比例，取整随机') +
            this._num('pass 允许连续次数', 'napcat.group_pass_rounds', 1, 0, 20, 1,
                'AI 连续输出 pass 的次数，超过后必须发送') +
            this._groupConfigEditor('每群单独配置（群号 → 触发基数/pass次数）', 'napcat.group_per_group',
                '留空则使用上面的全局配置；仅填写的字段覆盖全局') +
            this._section('群性质概括 (group_info)') +
            this._num('概括间隔（AI 发送条数）', 'napcat.group_info_interval', 100, 1, 10000, 1) +
            this._num('概括最近条数', 'napcat.group_info_recent', 50, 1, 500, 1) +
            this._num('概括采样范围（最近条数之外）', 'napcat.group_info_sample_range', 200, 1, 2000, 1);
    },

    napcat_send() {
        return this._section('NapCat 主动发送（触发型工具）') +
            this._check('启用主动发送', 'napcat.active_sender.enabled', true,
                'AI 主动给好友/群发消息、文件、链接（受 toolcalls 控制）') +
            this._num('冷却时间(秒)', 'napcat.active_sender.cooldown', 60, 0, 3600, 1,
                '两次主动发送的最小间隔');
    },

    // ============ Minecraft ============
    minecraft() {
        return this._section('Minecraft 日志读取') +
            this._check('启用 Minecraft 日志读取', 'minecraft.enabled', false) +
            this._text('日志文件路径', 'minecraft.log_path', '') +
            this._text('编码', 'minecraft.encoding', 'utf-8') +
            this._num('检查间隔（秒）', 'minecraft.check_interval', 30, 1, 60, 1) +
            this._check('使用玩家名作为 UID', 'minecraft.use_player_name', false) +
            this._text('固定用户名', 'minecraft.username_fixed', 'YGZ醒脑片') +
            this._check('在提示词中包含玩家名', 'minecraft.include_player_name_in_prompt', true) +
            this._list('玩家白名单（逗号分隔，空=不过滤）', 'minecraft.filter_players', []) +
            this._check('忽略自己发送的消息', 'minecraft.ignore_self_messages', false);
    },

    // ============ 角色主动回复 (llm_active) ============
    llm_active() {
        return this._section('角色主动回复 (llm_active)') +
            this._num('空闲冷却时间(秒)', 'llm_active.cold_time', 90, 1, 3600, 1,
                '空闲后触发主动回复的基础等待时间，实际等待 = 该值 × 随机(0.8~1.2)') +
            this._num('连续触发阈值 n', 'llm_active.n', 1, 0, 100, 1,
                '连续空闲触发次数 ≤ n 使用继承话题策略，> n 使用创造话题策略') +
            this._num('摘要检索条数上限', 'llm_active.origin_summary_limit', 30, 1, 200, 1,
                '创造话题策略时检索记忆摘要的最大条数') +
            this._num('最近说话人数量', 'llm_active.origin_speaker_limit', 3, 1, 3, 1,
                '创造话题策略时读取最近说话人档案的数量（最多3个）') +
            this._num('主动回复插播记忆上限(条)', 'llm_active.active_mem_limit', 50, 1, 500, 1,
                '主动回复单条消息在短期记忆中的兜底保留条数（尾部无后续对话时按此裁剪）');
    },

    // ============ B站浏览配置（视觉模型 + 内容收集） ============
    webBrowseConfig() {
        let h = this._section('B站浏览视觉模型 (llm_active.vision)') +
            this._password('API Key', 'llm_active.vision.api_key', '',
                '独立于 MeowVision，仅用于 B站视频截图的内容理解') +
            this._text('Base URL', 'llm_active.vision.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'llm_active.vision.model', 'qwen3.7-flash') +
            this._num('温度', 'llm_active.vision.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm_active.vision.max_tokens', 600, 1, 8192, 16,
                '内容描述(≤300字) + 话题 + tags 的输出预算') +
            this._num('Top P', 'llm_active.vision.top_p', 0.9, 0, 1, 0.05);

        h += this._section('B站内容收集 (llm_active.web_browse)') +
            this._check('启用 B站内容收集', 'llm_active.web_browse.enabled', true,
                '开启后后台线程定时抓取账号首页视频，抽帧 → 视觉概括 → 作为主动回复素材') +
            this._num('采集间隔(秒)', 'llm_active.web_browse.interval', 600, 30, 86400, 10,
                '每隔多久尝试补一个视频（默认 10 分钟）') +
            this._num('缓存上限', 'llm_active.web_browse.max_cache', 5, 1, 20, 1,
                '缓存达到该数量后暂停补货，消费后自动补') +
            this._num('抽帧数', 'llm_active.web_browse.frames', 5, 1, 10, 1,
                '视频 n 等分，每段随机抽 1 帧，压缩到 720p') +
            this._list('允许主题（逗号分隔）', 'llm_active.web_browse.allow_topics', ['二次元', '科普', '游戏'],
                '过滤视频的主题，空=随机') +
            this._select('严格程度', 'llm_active.web_browse.strictness', [
                { value: 'strict', label: 'strict（只允许列表内主题）' },
                { value: 'loose', label: 'loose（允许其它主题）' }
            ], 'strict') +
            this._check('禁止抽象视频', 'llm_active.web_browse.forbid_abstract', true,
                'LLM 语义判断，默认禁止抽象/整活类视频') +
            this._num('UP主 mid', 'llm_active.web_browse.mid', 0, 0, 999999999, 1,
                '0=自动用登录态抓自己账号首页视频；也可手动填指定 UP 主 mid') +
            this._text('SESSDATA', 'llm_active.web_browse.sessdata', '',
                'B站登录态，可点下方「B站扫码登录」自动获取；与弹幕兜底通道独立') +
            this._text('bili_jct', 'llm_active.web_browse.bili_jct', '',
                'B站 csrf 令牌，扫码登录自动写入');
        return h;
    },

    // ============ B站内容浏览面板 ============
    webBrowsePanel(status, cache, collected) {
        const caches = cache || [];
        const collecteds = collected || [];

        let h = this.webBrowseConfig();

        h += `<div class="speaker-actions">
            <button type="button" class="btn btn-secondary webbrowse-refresh-btn">刷新列表</button>
            <button type="button" class="btn btn-primary bili-login-btn" data-target="web_browse">B站扫码登录</button>
        </div>`;

        h += this._section('待使用缓存（' + caches.length + '）');
        h += `<div id="webBrowseCacheList">` + this._videoList(caches, false) + `</div>`;

        h += this._section('已收藏（' + collecteds.length + '）');
        h += `<div id="webBrowseCollectedList">` + this._videoList(collecteds, true) + `</div>`;
        return h;
    },

    _videoList(items, isCollected) {
        if (!items || !items.length) {
            return isCollected
                ? `<div class="help-text">暂无已收藏视频。主动回复使用过的视频会移动到此处。</div>`
                : `<div class="help-text">暂无缓存视频，等待后台采集或先扫码登录并配置视觉 API Key。</div>`;
        }
        return items.map(v => this._videoCard(v, isCollected)).join('');
    },

    _videoCard(v, isCollected) {
        v = v || {};
        const tags = (v.tags || []).map(t => `<span class="webbrowse-tag">${this._esc(t)}</span>`).join('');
        const urlHtml = (v.url && isCollected)
            ? `<a class="webbrowse-link" href="${this._escAttr(v.url)}" target="_blank" rel="noopener">打开视频 ↗</a>`
            : '';
        return `<div class="char-card">
            <div class="char-card-title">${this._esc(v.title || '(无标题)')}</div>
            <div class="webbrowse-meta">
                <span>UP：${this._esc(v.uploader || '-')}</span>
                <span>时长：${this._esc(v.len || '-')}</span>
                <span>话题：${this._esc(v.topic || '-')}</span>
                ${urlHtml}
            </div>
            ${tags ? `<div class="webbrowse-tags">${tags}</div>` : ''}
            <div class="webbrowse-content">${this._esc(v.content || '')}</div>
        </div>`;
    },

    // ============ 字幕 ============
    subtitle() {
        return this._section('字幕模块') +
            `<div class="help-text">浏览器字幕模块：TTS 播放字幕与歌词字幕统一输出（HTTP 8080 / WebSocket 8765，暂无配置项）。</div>`;
    },

    // ============ Toolbox 父级模型 ============
    toolbox() {
        const type = this._val('toolbox.llm_type', 'deepseek');
        let h = this._section('Toolbox 父级模型') +
            this._llmTypeSelect('父级 LLM 类型', 'toolbox.llm_type', type);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="toolbox_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="toolbox_aliyun">阿里云</button>
        </div>`;
        h += `<div class="tab-content active" data-tab-content="toolbox_ds">` +
            this._password('API Key', 'toolbox.deepseek.api_key', '') +
            this._text('Base URL', 'toolbox.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'toolbox.deepseek.model', 'deepseek-chat') +
            this._num('温度', 'toolbox.deepseek.temperature', 0.7, 0, 2, 0.1) +
            this._num('max_tokens', 'toolbox.deepseek.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="toolbox_aliyun">` +
            this._password('API Key', 'toolbox.aliyun.api_key', '') +
            this._text('Base URL', 'toolbox.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'toolbox.aliyun.model', 'qwen-plus') +
            this._num('温度', 'toolbox.aliyun.temperature', 0.7, 0, 2, 0.1) +
            this._num('max_tokens', 'toolbox.aliyun.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += this._section('excuse 通用询问链路') +
            this._check('启用 excuse 询问', 'toolbox.excuse_enabled', true,
                'AI 有疑问时以角色口吻语音询问，并阻塞等待用户文本输入补充需求') +
            this._num('excuse 等待超时(秒)', 'toolbox.excuse_timeout', 60, 1, 600, 1);
        return h;
    },

    // ============ MeowVision 视觉模块 ============
    meowvision() {
        return this._section('MeowVision 视觉理解（阿里云 qvq）') +
            this._password('API Key', 'meowvision.api_key', '') +
            this._text('Base URL', 'meowvision.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'meowvision.model', 'qvq-plus') +
            this._num('温度', 'meowvision.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'meowvision.max_tokens', 512, 1, 8192, 16,
                '视觉回复最大 token，默认 512') +
            this._num('Top P', 'meowvision.top_p', 0.9, 0, 1, 0.05) +
            this._text('图片缓存目录', 'meowvision.cache_dir', './.temp/vision_cache',
                '截图/裁切/编码结果统一缓存目录；NapCat 收到的图片也会先落到此目录避免直接用 url') +
            this._section('Watching 长期观察') +
            this._check('启用 Watching（长期观察屏幕）', 'meowvision.watching.enabled', true,
                'AI 判断用户有「陪打游戏 / 陪看屏幕」意图时才进入长期观察流程') +
            this._num('变化检测相似阈值', 'meowvision.watching.change_similarity_threshold', 0.85, 0, 1, 0.05,
                '前后两帧相似度达到该值判定为「无变化」，无变化时本轮不传视觉模型') +
            this._num('窗口消失确认秒数', 'meowvision.watching.window_gone_confirm_seconds', 5, 1, 60, 1,
                '绑定游戏窗口消失后，连续多少秒未检测到才判定强制结束');
    },

    // ============ 待办提醒 (calendar) ============
    calendarPanel() {
        return `<div class="calendar-panel">
            <div class="calendar-toolbar">
                <input type="text" id="newBacklogUserInput" placeholder="输入用户名">
                <button type="button" class="btn btn-primary" id="addBacklogUserBtn">新建用户</button>
            </div>
            <div id="backlogUserList"></div>
        </div>`;
    },

    // ============ 天气查询 (weather) ============
    weather() {
        return this._section('天气查询（触发型工具）') +
            this._check('启用天气查询', 'weather.enabled', true,
                'AI 根据用户天气询问触发查询并播报，数据来自中国天气网（受 toolcalls 控制）');
    },

    // ============ 新闻查询 (news) ============
    news() {
        return this._section('新闻查询（触发型工具）') +
            this._check('启用新闻查询', 'news.enabled', true,
                'AI 根据用户新闻/热点询问触发爬取并概括，数据来自 Readhub（受 toolcalls 控制）') +
            this._num('爬取条数', 'news.top_n', 3, 1, 10, 1,
                '每次爬取并概括的新闻条数（默认 3，最多 10）');
    },

    // ============ 新建待办提醒 (add_backlog) ============
    addBacklog() {
        return this._section('新建待办（触发型工具）') +
            this._check('启用新建待办', 'add_backlog.enabled', true,
                'AI 根据用户「记一下 / 提醒我几点做什么」触发，深度思考后写入 character/backlog（受 toolcalls 控制）') +
            this._check('QQ 对接', 'add_backlog.qq_enabled', true,
                '开启后 QQ 私聊 / 群聊@ 也可触发新建待办，且待办 qq 提醒强制开启');
    },

    // ============ 歌曲（meowsinger）子球 ============
    meowsingerModel() {
        const type = this._val('meowsinger.llm_type', 'deepseek');
        let h = this._section('点歌翻唱 LLM 模型') +
            this._check('启用点歌翻唱', 'meowsinger.enabled', true) +
            this._llmTypeSelect('LLM 类型', 'meowsinger.llm_type', type);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="meowsinger_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="meowsinger_aliyun">阿里云</button>
        </div>`;
        h += `<div class="tab-content active" data-tab-content="meowsinger_ds">` +
            this._password('API Key', 'meowsinger.deepseek.api_key', '') +
            this._text('Base URL', 'meowsinger.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'meowsinger.deepseek.model', 'deepseek-chat') +
            this._num('max_tokens', 'meowsinger.deepseek.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="meowsinger_aliyun">` +
            this._password('API Key', 'meowsinger.aliyun.api_key', '') +
            this._text('Base URL', 'meowsinger.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'meowsinger.aliyun.model', 'qwen-plus') +
            this._num('max_tokens', 'meowsinger.aliyun.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += this._section('回复引导词') +
            this._area('回复引导词', 'meowsinger.prompt.reply', '',
                '用于把「不会唱这首歌/没找到歌名」等内部信息转成角色口吻回复，{content}=内部信息');
        return h;
    },

    meowsingerSong() {
        const mode = this._val('meowsinger.song.trigger_mode', 'both');
        let h = this._section('点歌模块') +
            this._check('启用点歌', 'meowsinger.song.enabled', true) +
            this._select('触发模式', 'meowsinger.song.trigger_mode', [
                { value: 'both', label: '前缀优先 + 意图兜底' },
                { value: 'prefix', label: '仅前缀触发' },
                { value: 'intent', label: '仅意图触发' },
            ], 'both', '选择触发方式：both=两者都要，prefix=意图不生效，intent=前缀不生效',
                'data-trigger-mode="meowsinger.song"');
        if (mode !== 'intent') {
            h += `<div class="trigger-mode-group" data-mode-group="meowsinger.song" data-mode-show="prefix">` +
                this._wordTagEditor('前缀触发词（大小写敏感，必须最前）', 'meowsinger.song.prefix', ['Meowlisis点歌'],
                    '消息以该词开头时直接进入点歌，回车添加、点击 × 删除') +
                `</div>`;
        }
        if (mode !== 'prefix') {
            h += `<div class="trigger-mode-group" data-mode-group="meowsinger.song" data-mode-show="intent">` +
                this._wordTagEditor('意图触发词', 'meowsinger.song.intent', ['点歌', '放歌', '放首歌'],
                    '消息包含该词时结合歌名意图分析，回车添加、点击 × 删除') +
                `</div>`;
        }
        h += this._text('网易云服务地址', 'meowsinger.song.netease_url', 'http://127.0.0.1:5000');
        return h;
    },

    meowsingerCover(models, indices) {
        models = models || [];
        indices = indices || [];
        const modelOpts = models.map(m => ({ value: m, label: m }));
        if (modelOpts.length === 0) {
            modelOpts.push({ value: 'kikiV1.pth', label: 'kikiV1.pth' });
        }
        const indexOpts = [{ value: '', label: '（不使用索引）' }].concat(
            indices.map(i => ({ value: i, label: i }))
        );
        const mode = this._val('meowsinger.cover.trigger_mode', 'both');
        let h = this._section('翻唱模块') +
            this._check('启用翻唱', 'meowsinger.cover.enabled', true) +
            this._select('触发模式', 'meowsinger.cover.trigger_mode', [
                { value: 'both', label: '前缀优先 + 意图兜底' },
                { value: 'prefix', label: '仅前缀触发' },
                { value: 'intent', label: '仅意图触发' },
            ], 'both', '选择触发方式：both=两者都要，prefix=意图不生效，intent=前缀不生效',
                'data-trigger-mode="meowsinger.cover"');
        if (mode !== 'intent') {
            h += `<div class="trigger-mode-group" data-mode-group="meowsinger.cover" data-mode-show="prefix">` +
                this._wordTagEditor('前缀触发词（大小写敏感，必须最前）', 'meowsinger.cover.prefix', ['Meowlisis唱歌'],
                    '消息以该词开头时直接进入翻唱，回车添加、点击 × 删除') +
                `</div>`;
        }
        if (mode !== 'prefix') {
            h += `<div class="trigger-mode-group" data-mode-group="meowsinger.cover" data-mode-show="intent">` +
                this._wordTagEditor('意图触发词', 'meowsinger.cover.intent', ['唱首歌', '唱歌'],
                    '消息包含该词时结合歌名意图分析，回车添加、点击 × 删除') +
                `</div>`;
        }
        h += this._text('RVC 服务地址', 'meowsinger.cover.rvc_url', 'http://127.0.0.1:7865') +
            this._select('RVC 模型', 'meowsinger.cover.rvc_model', modelOpts, 'kikiV1.pth',
                '从 .RVC/assets/weights 目录读取') +
            this._select('RVC 索引', 'meowsinger.cover.rvc_index', indexOpts, '',
                '从 .RVC/assets/indices 目录读取，留空则自动匹配') +
            this._select('学歌模式', 'meowsinger.cover.learn_mode', [
                {value:'idle', label:'空闲时学习'}, {value:'immediate', label:'立刻学习'}
            ], 'idle') +
            this._wordTagEditor('学歌授权用户', 'meowsinger.cover.learn_users', [],
                '仅这些用户发送学歌指令可触发，回车添加、点击 × 删除') +
            this._text('学歌触发语', 'meowsinger.cover.learn_trigger', '喵利呜西斯，可以开始学歌啦') +
            this._section('停止') +
            this._wordTagEditor('停止触发词', 'meowsinger.stop.keywords', ['停止唱歌', '停停停'],
                '消息包含任一触发词即停止唱歌，回车添加、点击 × 删除');
        return h;
    },

    meowsingerSentiment() {
        return this._section('唱歌感想') +
            this._check('启用感想', 'meowsinger.sentiment.enabled', true,
                '完整唱完一首歌后，AI 结合歌词与歌曲信息发表感想') +
            this._num('感想 max_tokens', 'meowsinger.sentiment.max_tokens', 2048, 1, 32768, 16,
                '感想生成的最大 token 数') +
            this._num('感想字数', 'meowsinger.sentiment.word_count', 300, 50, 2000, 10,
                '感想引导词中要求的字数（默认 300）') +
            this._area('感想引导词', 'meowsinger.sentiment.prompt', '',
                '唱完整首歌后生成感想的引导词，{verb}/{song_title}/{lrc}/{result_text}/{word_count}=占位符') +
            this._area('汇总回复引导词', 'meowsinger.prompt.summary', '',
                '唱歌期间收到的观众消息汇总后统一回复的引导词，{lines}=观众消息列表') +
            this._area('歌曲搜索引导词', 'meowsinger.search.prompt', '',
                '唱歌开始/结束时搜索歌曲资料的引导词，{song_title}=歌名');
    },

    // ============ 即兴哼唱（meowsongs） ============
    _humDetectFormula() {
        return `<div class="formula-box">
            <div class="formula-box-title">哼唱检测算法</div>
            <div class="formula-block">
                <div class="formula-row">
                    <span class="formula-name">有效语音</span>
                    <span class="formula-expr">RMS ≥ 能量阈值，持续 ≥ 7 秒</span>
                    <span class="formula-cond">静音 ≥ 2 秒判段结束（阈值读 SenseVoice）</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">音高发声占比</span>
                    <span class="formula-expr">voiced_ratio = 有声帧 / 总帧 ≥ 0.6</span>
                    <span class="formula-cond">pyin 提取 F0，过滤清辅音与停顿</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">稳定帧占比</span>
                    <span class="formula-expr">stable_ratio = ( 相邻帧 |Δ半音| &lt; 0.5 ) 帧占比 ≥ 0.6</span>
                    <span class="formula-cond">哼唱音符内稳定；说话音高连续乱飘</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">音符数量</span>
                    <span class="formula-expr">unique_notes ≥ 3</span>
                    <span class="formula-cond">过滤单调拖长音</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">最终判定</span>
                    <span class="formula-expr">三项同时满足 → 判为哼唱</span>
                    <span class="formula-cond">通过后才进入 QBH 歌曲匹配</span>
                </div>
            </div>
            <div class="formula-params">
                voiced_ratio 过滤纯语音；stable_ratio 区分哼唱与说话；unique_notes 过滤单调音。
                判为哼唱后，再用 QBH 余弦相似度匹配歌曲（match_threshold）。
            </div>
        </div>`;
    },

    meowsongs() {
        return this._section('即兴哼唱（触发型工具）') +
            this._check('启用即兴哼唱', 'meowsongs.enabled', true,
                'AI 根据用户消息判断是否即兴哼唱已学歌曲片段（不带伴奏，只播放翻唱人声）') +
            this._num('播放长度上限（秒）', 'meowsongs.max_duration', 180, 1, 600, 1,
                '单次即兴哼唱的最长播放秒数，默认 180（整首歌）') +
            this._section('听歌识曲接龙') +
            this._humDetectFormula() +
            this._check('启用听歌识曲接龙', 'meowsongs.pass_the_baton.enabled', false,
                '用户哼唱一段后，AI 识别歌曲并接着往下唱（依赖哼唱检测与本地曲库）') +
            this._num('往后唱几句', 'meowsongs.pass_the_baton.hum_lines', 2, 1, 10, 1,
                '识别命中后接着唱的歌词句数，默认 2') +
            this._num('哼唱能量阈值', 'meowsongs.pass_the_baton.energy_threshold', 300, 0, 2000, 10,
                '判定哼唱的最小 RMS 能量，默认 300') +
            this._num('音高发声占比', 'meowsongs.pass_the_baton.f0_voiced_ratio', 0.6, 0.1, 1, 0.05,
                'pyin 有声帧占比阈值，越高要求哼唱越稳定') +
            this._num('稳定帧占比', 'meowsongs.pass_the_baton.f0_stable_ratio', 0.6, 0.1, 1, 0.05,
                '相邻帧音高差小于稳定半音阈值的帧占比，越高要求哼唱越稳定') +
            this._num('稳定帧半音差', 'meowsongs.pass_the_baton.f0_stable_half_step', 0.5, 0.1, 3, 0.05,
                '相邻帧音高差小于此半音数视为稳定帧') +
            this._num('有效语音累积时长（秒）', 'meowsongs.pass_the_baton.hum_collect_sec', 7.0, 3, 30, 0.5,
                '持续有效语音达到该时长才开始判断哼唱（静音/触发阈值读 SenseVoice 配置）') +
            this._num('最少不同音符数', 'meowsongs.pass_the_baton.f0_unique_notes', 3, 1, 10, 1,
                '哼唱至少出现的不同半音数量（过滤单调拖长音）') +
            this._num('匹配得分阈值', 'meowsongs.pass_the_baton.match_threshold', 0.55, 0.1, 1, 0.05,
                'QBH 匹配最低得分，默认 0.55') +
            this._num('缓存时长（秒）', 'meowsongs.pass_the_baton.cache_seconds', 30, 5, 120, 1,
                '哼唱检测环形缓冲时长，默认 30') +
            this._area('匹配失败询问引导词', 'meowsongs.pass_the_baton.ask_prompt', '',
                '哼唱匹配不到歌曲时，用于让 AI 问用户是不是在唱歌的引导词') +
            this._area('接龙感想引导词', 'meowsongs.pass_the_baton.feeling_prompt', '',
                '接龙命中后发表感想的引导词，{title}=歌名、{lyric}=歌词');
    },

    // ============ 数据库（database）子球 ============
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

    // ============ 数据库预填充（一键预填）子球 ============
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

    // 词条 tag 编辑器（借鉴 LLM 分隔符编辑器：每个词条单独一个 tag）
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

    // ============ 数据库来源（sites）子球 ============
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
    // 角色卡 JSON 字段由 App.onPlanetClick 异步填充
    characterCardConfig(files) {
        let h = this._section('角色卡选择');
        const cur = this._val('character_card.card_file', 'prompt');
        const opts = (files || []).map(f => {
            const v = f.replace(/\.json$/, '');
            return `<option value="${v}" ${v === cur ? 'selected' : ''}>${v}</option>`;
        }).join('');
        h += `<div class="form-group"><label>角色卡文件</label>
            <select data-path="character_card.card_file" id="cardFileSelect">${opts || '<option value="prompt">prompt</option>'}</select></div>`;
        h += this._text('当前选中角色名', 'character_card.select', '');
        h += `<div class="speaker-actions">
            <button class="btn btn-secondary" id="newCardBtn">新建角色卡</button>
        </div>`;
        return h;
    },

    characterCardData(data) {
        const chars = (data && data.characters) || [];
        let h = this._section('角色卡内容');
        if (!chars.length) {
            h += `<div class="help-text">暂无角色数据，请点击下方新建</div>`;
            return h;
        }
        const c = chars[0];

        // 共用字段
        h += this._charText('角色名称', 'name', c.name) +
            this._charText('昵称', 'nickname', c.nickname) +
            this._charText('外貌', 'appearance', c.appearance) +
            this._charText('生日', 'birthday', c.birthday) +
            this._charText('身份证号', 'id_card', c.id_card) +
            this._charText('QQ号', 'qq', c.qq) +
            this._charText('手机号', 'phone', c.phone) +
            this._charText('MBTI', 'mbti', c.mbti) +
            this._charText('最喜欢的东西', 'favorite', c.favorite) +
            this._charText('爱好', 'hobbies', c.hobbies) +
            this._charText('讨厌的东西', 'dislikes', c.dislikes) +
            this._charText('人际关系', 'relationships', c.relationships);

        // 设定（字典，多条）
        h += this._section('角色设定（多条）');
        h += `<div id="settingList">`;
        const setting = c.setting || {};
        if (setting && typeof setting === 'object') {
            Object.keys(setting).forEach((k, i) => {
                h += this._settingRow(i, k, setting[k]);
            });
        }
        h += `</div>`;
        h += `<button class="btn btn-secondary" id="addSettingBtn">添加设定</button>`;

        // 性格（字典，多条）
        h += this._section('角色性格（多条，每条含提示词）');
        h += `<div id="personalityList">`;
        const personality = c.personality || {};
        if (personality && typeof personality === 'object') {
            Object.keys(personality).forEach((k, i) => {
                h += this._personalityRow(i, k, personality[k]);
            });
        }
        h += `</div>`;
        h += `<button class="btn btn-secondary" id="addPersonalityBtn">新建性格</button>`;
        return h;
    },

    _charText(label, field, value) {
        return `<div class="form-group"><label>${label}</label>
            <textarea class="auto-grow" rows="2" data-char-field="${field}">${this._esc(value)}</textarea>
        </div>`;
    },

    _settingRow(index, key, value) {
        return `<div class="dict-row" data-dict-index="${index}">
            <div class="form-group"><label>设定名</label>
                <input type="text" data-setting-key value="${key == null ? '' : key}"></div>
            <div class="form-group"><label>设定内容</label>
                <textarea class="auto-grow" rows="2" data-setting-value>${this._esc(value)}</textarea></div>
        </div>`;
    },

    _personalityRow(index, key, value) {
        return `<div class="dict-row" data-dict-index="${index}">
            <div class="form-group"><label>性格名</label>
                <input type="text" data-personality-key value="${key == null ? '' : key}"></div>
            <div class="form-group"><label>性格提示词</label>
                <textarea class="auto-grow" rows="2" data-personality-value>${this._esc(value)}</textarea></div>
        </div>`;
    },

    collectValues() {
        const inputs = document.querySelectorAll('#modalBody [data-path]');
        const updates = [];
        inputs.forEach(el => {
            const path = el.dataset.path;
            let value;
            if (el.type === 'checkbox') value = el.checked;
            else if (el.type === 'number') value = parseFloat(el.value);
            else value = el.value;
            updates.push({ path, value });
        });
        return updates;
    },

    // 收集数据库来源站点（sites 编辑器）
    collectSources() {
        const result = {};
        document.querySelectorAll('#sourceSiteList [data-source-site]').forEach(card => {
            const get = (field) => {
                const el = card.querySelector(`[data-source-field="${field}"]`);
                if (!el) return undefined;
                if (el.type === 'checkbox') return el.checked;
                if (el.type === 'number') return parseFloat(el.value);
                return el.value;
            };
            const key = (get('key') || '').trim();
            if (!key) return;
            result[key] = {
                label: get('label') || key,
                description: get('description') || '',
                enabled: get('enabled') !== false,
                strategy: get('strategy') || 'http',
                count: get('count') || 5,
                base_url: get('base_url') || '',
                search_url: get('search_url') || '',
                interval: get('interval') || 2,
            };
        });
        return result;
    },

    // 收集新结构角色卡（共用字段 + setting 字典 + personality 字典）
    collectCharacterCard() {
        const obj = {};
        document.querySelectorAll('#modalBody [data-char-field]').forEach(el => {
            obj[el.dataset.charField] = el.value;
        });
        const setting = {};
        document.querySelectorAll('#settingList .dict-row').forEach(row => {
            const key = row.querySelector('[data-setting-key]').value.trim();
            const value = row.querySelector('[data-setting-value]').value;
            if (key) setting[key] = value;
        });
        obj.setting = setting;
        const personality = {};
        document.querySelectorAll('#personalityList .dict-row').forEach(row => {
            const key = row.querySelector('[data-personality-key]').value.trim();
            const value = row.querySelector('[data-personality-value]').value;
            if (key) personality[key] = value;
        });
        obj.personality = personality;
        return { characters: [obj] };
    },

    // 收集参考音频配置
    collectRefAudio() {
        const result = {};
        document.querySelectorAll('#refAudioPanel [data-ref-audio-name]').forEach(el => {
            const name = el.dataset.refAudioName;
            const field = el.dataset.refAudioField;
            if (!result[name]) result[name] = {};
            result[name][field] = el.value;
        });
        return result;
    },

    // 收集 TTS 模型配置（从当前 modal 面板收集 data-tts-model 字段）
    collectTtsModel() {
        const result = { custom: {} };
        const customKeys = ['device', 'is_half', 't2s_weights_path', 'vits_weights_path', 'version'];
        document.querySelectorAll('#modalBody [data-tts-model]').forEach(el => {
            const key = el.dataset.ttsModel;
            let value;
            if (el.type === 'checkbox') value = el.checked;
            else if (el.type === 'number') value = parseFloat(el.value);
            else value = el.value;
            if (customKeys.includes(key)) {
                result.custom[key] = value;
            } else {
                result[key] = value;
            }
        });
        return result;
    },

    applyUpdates(updates, target) {
        for (const { path, value } of updates) {
            const parts = path.split('.');
            let current = target;
            for (let i = 0; i < parts.length - 1; i++) {
                const p = parts[i];
                const nextP = parts[i + 1];
                if (!(p in current)) {
                    current[p] = (!isNaN(parseInt(nextP)) && !isNaN(Number(nextP))) ? [] : {};
                }
                current = current[p];
            }
            const last = parts[parts.length - 1];
            // 列表类型字段：逗号/换行分隔后存为数组
            if (typeof value === 'string' && (
                path === 'app.mode' ||
                path === 'sensevoice.target_speakers' ||
                path === 'sensevoice.hotwords' ||
                path === 'minecraft.filter_players' ||
                path === 'napcat.group_blacklist' ||
                path === 'llm_active.web_browse.allow_topics'
            )) {
                current[last] = value.split(/[,，\n]/).map(s => s.trim()).filter(Boolean);
            } else if (typeof value === 'string' && (
                path === 'meowsinger.song.prefix' ||
                path === 'meowsinger.song.intent' ||
                path === 'meowsinger.cover.prefix' ||
                path === 'meowsinger.cover.intent' ||
                path === 'meowsinger.cover.learn_users' ||
                path === 'meowsinger.stop.keywords'
            )) {
                try { current[last] = JSON.parse(value); }
                catch (e) { current[last] = value.split(/\n/).map(s => s.trim()).filter(Boolean); }
            } else if (path === 'napcat.group_bots' || path === 'napcat.group_per_group') {
                // dict 编辑器：隐藏 input 存 JSON 字符串，这里解析回对象
                try { current[last] = JSON.parse(value); }
                catch (e) { current[last] = {}; }
            } else {
                current[last] = value;
            }
        }
    }
};
