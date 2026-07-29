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

    basic() {
        return this._text('AI名称', 'AiName', '喵呜') +
            this._check('启用翻译', 'translate.switch', false) +
            `<div class="form-group"><label>弹幕源</label>
            <select data-path="danmaku.source">
                <option value="blivedm" ${this._val('danmaku.source', 'blivedm') === 'blivedm' ? 'selected' : ''}>blivedm</option>
                <option value="biive" ${this._val('danmaku.source') === 'biive' ? 'selected' : ''}>biive</option>
                <option value="api" ${this._val('danmaku.source') === 'api' ? 'selected' : ''}>api</option>
            </select></div>` +
            this._text('直播间号', 'danmaku.blivedm.room_id', '', 'B站直播间房间号') +
            this._text('SESSDATA', 'danmaku.blivedm.sessdata', '') +
            this._text('ACCESS_KEY_ID', 'danmaku.blivedm.ACCESS_KEY_ID', '') +
            this._password('ACCESS_KEY_SECRET', 'danmaku.blivedm.ACCESS_KEY_SECRET', '') +
            this._text('APP_ID', 'danmaku.blivedm.APP_ID', '') +
            this._text('ROOM_OWNER_AUTH_CODE', 'danmaku.blivedm.ROOM_OWNER_AUTH_CODE', '');
    },

    llm() {
        const type = this._val('llm.local_llm_type', 'ollama');
        let h = `<div class="form-group"><label>LLM类型</label>
            <select data-path="llm.local_llm_type">
                <option value="ollama" ${type === 'ollama' ? 'selected' : ''}>Ollama</option>
                <option value="aliyun" ${type === 'aliyun' ? 'selected' : ''}>阿里云</option>
                <option value="bigmodel" ${type === 'bigmodel' ? 'selected' : ''}>智谱</option>
                <option value="deepseek" ${type === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
            </select></div>`;

        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="ollama">Ollama</button>
            <button class="modal-tab" data-tab="aliyun">阿里云</button>
            <button class="modal-tab" data-tab="bigmodel">智谱</button>
            <button class="modal-tab" data-tab="deepseek">DeepSeek</button>
        </div>`;

        h += `<div class="tab-content active" data-tab-content="ollama">` +
            this._text('Ollama URL', 'llm.ollama.ollama_url', 'http://localhost:11434') +
            this._text('本地模型', 'llm.ollama.model_local', 'cydonia') +
            this._text('云端模型', 'llm.ollama.model_cloud', 'deepseek-v3.1:671b-cloud') +
            this._num('温度', 'llm.ollama.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.ollama.max_tokens', 256, 1, 4096, 16) +
            this._check('使用云端模型', 'llm.ollama.use_cloud', false) +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="aliyun">` +
            this._password('API Key', 'llm.aliyun.api_key', '') +
            this._text('模型', 'llm.aliyun.model', 'qwen3-max') +
            this._num('温度', 'llm.aliyun.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.aliyun.max_tokens', 1024, 1, 8192, 16) +
            this._check('启用思考模式', 'llm.aliyun.enable_thinking', true) +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="bigmodel">` +
            this._password('API Key', 'llm.bigmodel.api_key', '') +
            this._text('模型', 'llm.bigmodel.model', 'glm-4.7-flash') +
            this._num('温度', 'llm.bigmodel.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.bigmodel.max_tokens', 1024, 1, 8192, 16) +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="deepseek">` +
            this._password('API Key', 'llm.deepseek.api_key', '') +
            this._text('Base URL', 'llm.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'llm.deepseek.model', 'deepseek-chat') +
            this._num('温度', 'llm.deepseek.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.deepseek.max_tokens', 1024, 1, 8192, 16) +
            this._num('Top P', 'llm.deepseek.top_p', 0.9, 0, 1, 0.05) +
            this._check('启用流式输出', 'llm.deepseek.stream', true) +
            `</div>`;

        h += this._text('分割符', 'llm.split_flag', ',|，|。|!|！|?|？|\n') +
            this._num('最小分段长度', 'llm.split_limit', 6, 1, 100, 1);
        return h;
    },

    memory() {
        return this._check('共享记忆', 'llm.memory.shared', false) +
            this._check('启用摘要存储', 'llm.memory.enable_summary', true) +
            this._num('短期记忆轮数', 'llm.memory.short_term_rounds', 3, 1, 20, 1) +
            this._num('触发存储轮数', 'llm.memory.max_pending_rounds', 10, 1, 50, 1) +
            this._select('嵌入模型级别', 'llm.memory.model_level', [{value:'small',label:'small'},{value:'large',label:'large'}], 'small') +
            this._text('长期记忆目录', 'llm.memory.long_term_dir', './chatrecords') +
            this._check('启用个性记忆 (mem0)', 'llm.memory.enable_mem0', true) +
            this._check('启用聊天记录检索', 'llm.memory.enable_chat_record_retrieval', true) +
            this._num('聊天记录检索天数', 'llm.memory.chat_record_days', 7, 1, 30, 1) +
            this._num('聊天记录检索数量', 'llm.memory.chat_record_top_k', 3, 1, 10, 1);
    },

    vision() {
        const enabled = this._val('vision.qwen.enabled', true);
        return this._check('启用 Qwen 视觉', 'vision.qwen.enabled', true) +
            this._password('API Key', 'vision.qwen.api_key', '') +
            this._text('Base URL', 'vision.qwen.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'vision.qwen.model', 'qwen-vl-max') +
            this._text('提示词', 'vision.qwen.prompt', '描述一下图片内容，简洁精准') +
            this._num('触发冷却(秒)', 'vision.qwen.cooldown', 10, 0, 60, 1) +
            this._num('最大输出 tokens', 'vision.qwen.max_tokens', 200, 50, 500, 10) +
            this._num('温度', 'vision.qwen.temperature', 0.6, 0, 2, 0.1) +
            this._check('启用定时自动截图', 'vision.qwen.timer_enabled', false) +
            this._num('定时间隔(秒)', 'vision.qwen.timer_interval', 300, 10, 3600, 10);
    },

    search() {
        return `<h4>图片搜索</h4>` +
            this._num('图片数量', 'searchImg.imageNum', 10, 1, 50, 1) +
            this._num('图片宽度', 'searchImg.width', 600, 100, 4096, 10) +
            this._num('图片高度', 'searchImg.height', 800, 100, 4096, 10) +
            this._text('图片保存路径', 'searchImg.physical_save_folder', '') +
            `<h4>网页搜索</h4>` +
            this._num('搜索结果数量', 'searchWeb.searchNum', 8, 1, 20, 1) +
            this._num('最大结果数', 'searchWeb.max_results', 5, 1, 20, 1) +
            this._text('缓存目录', 'searchWeb.cache_dir', 'searchresult') +
            this._check('使用关键词提取', 'searchWeb.use_keyword_extract', true) +
            this._check('启用语义搜索', 'searchWeb.semantic_search.enabled', true);
    },

    response() {
        return this._num('超时秒数', 'response.timeout_seconds', 5, 1, 30, 1) +
            this._num('空闲分钟数', 'response.idle_minutes', 10, 1, 60, 1) +
            this._text('空闲消息', 'response.idle_message', '主人10分钟没跟你说话了');
    },

    obs() {
        return this._check('启用OBS控制', 'obs.switch', true) +
            this._text('WebSocket地址', 'obs.url', '127.0.0.1') +
            this._num('端口', 'obs.port', 4455, 1, 65535, 1) +
            this._password('密码', 'obs.password', '') +
            this._text('唱歌背景', 'obs.song_background', '') +
            this._text('跳舞视频目录', 'obs.dance_path', '') +
            this._text('表情视频目录', 'obs.emote_path', '') +
            this._text('表情字幕字体', 'obs.emote_font', '');
    },

    vtuber() {
        return this._check('启用 VTuber 控制', 'emote.switch', false) +
            this._text('WebSocket 地址', 'emote.vtuber_websocket', '127.0.0.1:8001') +
            this._text('插件名称', 'emote.vtuber_pluginName', '') +
            this._text('插件开发者', 'emote.vtuber_pluginDeveloper', '') +
            this._text('认证令牌', 'emote.vtuber_authenticationToken', '');
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
            this._num('句子合并延迟(秒)', 'sensevoice.merge_delay', 1.5, 0, 5, 0.1) +
            this._num('静音阈值(秒)', 'sensevoice.silence_threshold', 2.0, 0, 5, 0.1);
    },

    agent() {
        return this._check('启用 Agent 模式', 'agent.enabled', false) +
            this._num('主动发言间隔(秒)', 'agent.interval_seconds', 600, 30, 3600, 30) +
            this._num('冷却时间(秒)', 'agent.cooldown_seconds', 120, 10, 600, 10) +
            this._text('目标用户 UID', 'agent.target_uid', 'littleYGZ') +
            this._text('角色卡路径', 'agent.character_path', './character/[cute]MiaoWu.yaml');
    },

    minecraft() {
        return this._check('启用 Minecraft 日志读取', 'minecraft.enabled', false) +
            this._text('日志文件路径', 'minecraft.log_path', '') +
            this._text('编码', 'minecraft.encoding', 'utf-8') +
            this._num('检查间隔（秒）', 'minecraft.check_interval', 5, 1, 30, 1) +
            this._check('使用玩家名作为 UID', 'minecraft.use_player_uid', false);
    },

    character() {
        const cards = this._val('character_cards', []);
        let h = '<p style="color:#888;font-size:13px;margin-bottom:12px;">角色卡文件存放在 ./character 目录下</p>';
        cards.forEach((card, i) => {
            h += `<div style="border:1px solid var(--pink-soft);border-radius:12px;padding:12px;margin-bottom:12px;">
                <strong>${card.file || '未知'}</strong>
                <div class="form-group" style="margin-top:8px;">
                    <label>触发关键词（逗号分隔）</label>
                    <input type="text" data-path="character_cards.${i}.keywords" value="${(card.keywords || []).join(', ')}">
                </div>
                <div class="form-group">
                    <label>权重</label>
                    <input type="number" data-path="character_cards.${i}.weight" value="${card.weight || 1}" min="0.1" max="10" step="0.1">
                </div>
                <div class="form-group">
                    <label>Token策略</label>
                    <select data-path="character_cards.${i}.token_strategy">
                        <option value="chat" ${card.token_strategy === 'chat' ? 'selected' : ''}>chat</option>
                        <option value="smart" ${card.token_strategy === 'smart' ? 'selected' : ''}>smart</option>
                        <option value="normal" ${card.token_strategy === 'normal' ? 'selected' : ''}>normal</option>
                    </select>
                </div>
            </div>`;
        });
        return h;
    },

    sing() {
        return `<p style="color:#888;font-size:13px;margin-bottom:12px;">配置唱歌模块的触发关键词</p>`;
    },

    tts() {
        return Sovits.renderPanel();
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
            if (path.startsWith('character_cards.') && last === 'keywords' && typeof value === 'string') {
                current[last] = value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
            } else {
                current[last] = value;
            }
        }
    }
};
