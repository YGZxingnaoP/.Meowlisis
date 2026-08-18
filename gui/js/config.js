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

    _select(label, path, options, def, help) {
        const v = this._val(path, def);
        const opts = options.map(o => `<option value="${o.value}" ${String(o.value) === String(v) ? 'selected' : ''}>${o.label}</option>`).join('');
        return `<div class="form-group"><label>${label}</label>
            <select data-path="${path}">${opts}</select>
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

    _section(title) {
        return `<div class="form-section"><h4>${title}</h4></div>`;
    },

    _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },

    // ============ 基本设置（根级 + app） ============
    basic() {
        return this._section('基础信息') +
            this._text('AI名称', 'AiName', '喵呜') +
            this._list('运行模式（api / blivedm，逗号分隔）', 'app.mode', ['api']) +
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
            this._text('用户名', 'sensevoice.username', 'YGZ醒脑片') +
            this._select('语言', 'sensevoice.language', [
                {value:'auto',label:'auto'},{value:'zh',label:'zh'},{value:'en',label:'en'},
                {value:'yue',label:'yue'},{value:'ja',label:'ja'},{value:'ko',label:'ko'}
            ], 'auto') +
            this._check('启用标点与逆文本正则化', 'sensevoice.itn', true) +
            this._num('说话人判定阈值', 'sensevoice.speaker_threshold', 0.2, 0, 1, 0.05) +
            this._list('目标说话人（逗号分隔）', 'sensevoice.target_speakers', []) +
            this._list('热词（逗号分隔，每项: 词 权重...）', 'sensevoice.hotwords', []) +
            this._num('VAD 能量阈值', 'sensevoice.vad_energy_threshold', 400, 0, 5000, 50) +
            this._num('句子合并延迟(秒)', 'sensevoice.merge_delay', 1.0, 0, 5, 0.1) +
            this._num('静音阈值(秒)', 'sensevoice.silence_threshold', 2.0, 0, 5, 0.1) +
            this._num('心跳间隔(秒)', 'sensevoice.ping_interval', 20, 1, 120, 1) +
            this._num('心跳超时(秒)', 'sensevoice.ping_timeout', 60, 1, 300, 1) +
            this._num('最大重连次数', 'sensevoice.max_reconnect_attempts', 5, 0, 50, 1);
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
    llm(frontPrompt) {
        const type = this._val('llm.local_llm_type', 'deepseek');
        const fp = frontPrompt || '';
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

        // 前置词模块（单独保存到 character/front/prompt.json）
        h += this._section('前置词') +
            `<div class="form-group"><label>前置词（system prompt 最前面）</label>
                <textarea id="frontPromptInput" class="auto-grow" rows="3" placeholder="请输入前置词">${this._esc(fp)}</textarea>
                <div class="help-text">该内容会在每次对话的 system prompt 最前面拼接</div>
            </div>`;

        return h;
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
        return this._section('B站弹幕 (blivedm)') +
            this._text('直播间号', 'danmaku.blivedm.room_id', '') +
            this._text('SESSDATA', 'danmaku.blivedm.sessdata', '') +
            this._text('ACCESS_KEY_ID', 'danmaku.blivedm.ACCESS_KEY_ID', '') +
            this._password('ACCESS_KEY_SECRET', 'danmaku.blivedm.ACCESS_KEY_SECRET', '') +
            this._text('APP_ID', 'danmaku.blivedm.APP_ID', '') +
            this._text('ROOM_OWNER_AUTH_CODE', 'danmaku.blivedm.ROOM_OWNER_AUTH_CODE', '');
    },

    // ============ VTuber (emote 节点) ============
    vtuber() {
        return this._section('VTuber / VTube Studio') +
            this._check('启用 VTuber 控制', 'emote.switch', false) +
            this._text('WebSocket 地址', 'emote.vtuber_websocket', '127.0.0.1:8001') +
            this._text('插件名称', 'emote.vtuber_pluginName', '') +
            this._text('插件开发者', 'emote.vtuber_pluginDeveloper', '') +
            this._text('认证令牌', 'emote.vtuber_authenticationToken', '');
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

    // ============ OBS ============
    obs() {
        return this._section('OBS 直播控制') +
            this._check('启用OBS控制', 'obs.switch', false) +
            this._text('WebSocket地址', 'obs.url', '127.0.0.1') +
            this._num('端口', 'obs.port', 4455, 1, 65535, 1) +
            this._password('密码', 'obs.password', '') +
            this._text('唱歌背景（场景名=音乐路径，JSON格式）', 'obs.song_background', '');
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

    // 收集 TTS 模型配置
    collectTtsModel() {
        const result = { custom: {} };
        const customKeys = ['device', 'is_half', 't2s_weights_path', 'vits_weights_path', 'version'];
        document.querySelectorAll('#ttsModelPanel [data-tts-model]').forEach(el => {
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
                path === 'minecraft.filter_players'
            )) {
                current[last] = value.split(/[,，\n]/).map(s => s.trim()).filter(Boolean);
            } else {
                current[last] = value;
            }
        }
    }
};
