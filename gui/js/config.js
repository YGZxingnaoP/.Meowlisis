/**
 * Configuration panel generators
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
            <input type="text" data-path="${path}" value="${v || ''}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _num(label, path, def, min, max, step, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <input type="number" data-path="${path}" value="${v}" min="${min}" max="${max}" step="${step}">
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
        const opts = options.map(o => `<option value="${o.value}" ${o.value === v ? 'selected' : ''}>${o.label}</option>`).join('');
        return `<div class="form-group"><label>${label}</label>
            <select data-path="${path}">${opts}</select>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _password(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <input type="password" data-path="${path}" value="${v || ''}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    _list(label, path, def, help) {
        const v = this._val(path, def) || [];
        const text = Array.isArray(v) ? v.join(', ') : v;
        return `<div class="form-group"><label>${label}</label>
            <input type="text" data-path="${path}" data-list="1" value="${text}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    basic() {
        return this._text('AI名称', 'AiName', '喵呜') +
            this._text('直播间号', 'danmaku.blivedm.room_id', '', 'B站直播间房间号') +
            this._text('SESSDATA', 'danmaku.blivedm.sessdata', '') +
            this._text('ACCESS_KEY_ID', 'danmaku.blivedm.ACCESS_KEY_ID', '') +
            this._password('ACCESS_KEY_SECRET', 'danmaku.blivedm.ACCESS_KEY_SECRET', '') +
            this._text('APP_ID', 'danmaku.blivedm.APP_ID', '') +
            this._text('ROOM_OWNER_AUTH_CODE', 'danmaku.blivedm.ROOM_OWNER_AUTH_CODE', '');
    },

    llm() {
        const type = this._val('llm.local_llm_type', 'deepseek');
        let h = `<div class="form-group"><label>LLM类型</label>
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
            this._text('分割符', 'llm.split_flag', ',|，|。|!|！|?|？') +
            this._num('最小分段长度', 'llm.split_limit', 6, 1, 100, 1);
        return h;
    },

    sensevoice() {
        return this._check('启用 SenseVoice', 'sensevoice.enabled', true) +
            this._text('WebSocket 服务器地址', 'sensevoice.server_url', 'ws://127.0.0.1:10095/') +
            this._select('识别模式', 'sensevoice.mode', [{value:'2pass',label:'2pass'},{value:'offline',label:'offline'},{value:'online',label:'online'}], '2pass') +
            this._num('分块大小(ms)', 'sensevoice.chunk_size_ms', 300, 50, 500, 10) +
            this._text('UID', 'sensevoice.uid', 'littleYGZ') +
            this._text('用户名', 'sensevoice.username', 'YGZ醒脑片') +
            this._select('语言', 'sensevoice.language', [{value:'auto',label:'auto'},{value:'zh',label:'zh'},{value:'en',label:'en'},{value:'yue',label:'yue'},{value:'ja',label:'ja'},{value:'ko',label:'ko'}], 'auto') +
            this._check('启用标点与逆文本正则化', 'sensevoice.itn', true) +
            this._num('说话人判定阈值', 'sensevoice.speaker_threshold', 0.2, 0, 1, 0.05) +
            this._list('目标说话人（逗号分隔）', 'sensevoice.target_speakers', []) +
            this._list('热词（逗号分隔，每项: 词 权重...）', 'sensevoice.hotwords', []) +
            this._num('VAD 能量阈值', 'sensevoice.vad_energy_threshold', 400, 0, 5000, 50) +
            this._num('打断能量阈值', 'sensevoice.interrupt_energy_threshold', 600, 0, 5000, 50) +
            this._check('启用语音打断', 'sensevoice.interrupt_enabled', false) +
            this._num('打断冷却(秒)', 'sensevoice.interrupt_cooldown', 1.0, 0, 10, 0.1) +
            this._num('句子合并延迟(秒)', 'sensevoice.merge_delay', 1.0, 0, 5, 0.1) +
            this._num('静音阈值(秒)', 'sensevoice.silence_threshold', 2.0, 0, 5, 0.1) +
            this._num('心跳间隔(秒)', 'sensevoice.ping_interval', 20, 1, 120, 1) +
            this._num('心跳超时(秒)', 'sensevoice.ping_timeout', 60, 1, 300, 1) +
            this._num('最大重连次数', 'sensevoice.max_reconnect_attempts', 5, 0, 50, 1);
    },

    obs() {
        return this._check('启用OBS控制', 'obs.switch', true) +
            this._text('WebSocket地址', 'obs.url', '127.0.0.1') +
            this._num('端口', 'obs.port', 4455, 1, 65535, 1) +
            this._password('密码', 'obs.password', '') +
            this._text('唱歌背景（场景名=音乐路径，JSON格式）', 'obs.song_background', '');
    },

    vtuber() {
        return this._check('启用 VTuber 控制', 'emote.switch', false) +
            this._text('WebSocket 地址', 'emote.vtuber_websocket', '127.0.0.1:8001') +
            this._text('插件名称', 'emote.vtuber_pluginName', '') +
            this._text('插件开发者', 'emote.vtuber_pluginDeveloper', '') +
            this._text('认证令牌', 'emote.vtuber_authenticationToken', '');
    },

    minecraft() {
        return this._check('启用 Minecraft 日志读取', 'minecraft.enabled', false) +
            this._text('日志文件路径', 'minecraft.log_path', '') +
            this._text('编码', 'minecraft.encoding', 'utf-8') +
            this._num('检查间隔（秒）', 'minecraft.check_interval', 5, 1, 60, 1) +
            this._check('使用玩家名作为 UID', 'minecraft.use_player_uid', false) +
            this._text('固定 UID', 'minecraft.uid_fixed', 'littleYGZ') +
            this._text('固定用户名', 'minecraft.username_fixed', 'YGZ醒脑片') +
            this._check('在提示词中包含玩家名', 'minecraft.include_player_name_in_prompt', true) +
            this._list('玩家白名单（逗号分隔，空=不过滤）', 'minecraft.filter_players', []) +
            this._check('忽略自己发送的消息', 'minecraft.ignore_self_messages', false);
    },

    tts() {
        return this._select('语音合成引擎', 'speech.select', [{value:'gpt-sovits',label:'GPT-SoVITS'}], 'gpt-sovits') +
            this._text('GPT-SoVITS 服务地址', 'speech.gpt-sovits.gpt_sovits_url', 'http://127.0.0.1:9880') +
            this._text('输出目录', 'speech.output_dir', './output') +
            this._num('音量', 'speech.volume', 1.0, 0, 2, 0.1) +
            this._num('合成线程数', 'speech.synth_workers', 2, 1, 8, 1) +
            this._select('打断模式', 'speech.interrupt.mode', [{value:'pipeline',label:'pipeline'},{value:'keyboard',label:'keyboard'},{value:'off',label:'off'}], 'pipeline') +
            this._text('打断按键', 'speech.interrupt.key', 'f8') +
            this._num('打断轮询间隔(秒)', 'speech.interrupt.poll_interval', 0.1, 0.01, 1, 0.01) +
            Sovits.renderPanel();
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

    applyUpdates(updates, target) {
        for (const { path, value } of updates) {
            const parts = path.split('.');
            let current = target;
            for (let i = 0; i < parts.length - 1; i++) {
                const p = parts[i];
                const nextP = parts[i + 1];
                if (!(p in current)) {
                    current[p] = !isNaN(parseInt(nextP)) && !isNaN(Number(nextP)) ? [] : {};
                }
                current = current[p];
            }
            const last = parts[parts.length - 1];
            // 列表类型字段：逗号/换行分隔后存为数组
            if (typeof value === 'string' && (
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
