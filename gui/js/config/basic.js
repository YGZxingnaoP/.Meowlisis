/**
 * 配置面板生成器 - basic 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
    basic() {
        return this._section('基础信息') +
            this._text('AI名称', 'AiName', '喵呜') +
            this._num('API 端口', 'app.port', 1800, 1, 65535, 1);
    },

    // ============ SenseVoice ============,
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
            <button class="btn btn-secondary" id="addReplaceRuleBtn">${this._t('添加规则')}</button>`;
    },

    // ============ 音频采集（多源，分别开关） ============,
    audio() {
        return this._section('音频采集源') +
            this._check('麦克风采集', 'audio.sources.mic.enabled', true) +
            this._section('电脑扬声器行为') +
            this._check('电脑扬声器采集（需安装 pyaudiowpatch）', 'audio.sources.loopback.enabled', false) +
            this._check('允许打断', 'audio.sources.loopback.allow_interrupt', false,
                '电脑声音是否触发 TTS 打断') +
            this._check('声纹识别', 'audio.sources.loopback.speaker_verify', false,
                '关闭后跳过声纹验证，识别结果用户名用下方固定用户名') +
            this._text('固定用户名', 'audio.sources.loopback.username', '主人的电脑',
                '声纹识别关闭时使用') +
            this._section('接口注入行为') +
            this._check('接口注入采集（/audio/send）', 'audio.sources.inject.enabled', true) +
            this._check('允许打断', 'audio.sources.inject.allow_interrupt', false,
                '注入音频是否触发 TTS 打断') +
            this._check('声纹识别', 'audio.sources.inject.speaker_verify', false,
                '关闭后跳过声纹验证，识别结果用户名用下方固定用户名') +
            this._text('固定用户名', 'audio.sources.inject.username', '主人的电脑',
                '声纹识别关闭时使用') +
            this._num('采样率(Hz)', 'audio.rate', 16000, 8000, 48000, 1000) +
            this._num('声道数', 'audio.channels', 1, 1, 2, 1) +
            this._num('分块大小(ms)', 'audio.chunk_size_ms', 300, 50, 500, 10);
    },

    // ============ 静默（闭麦）配置 ============,
    silence() {
        return this._section('静默（语音触发）') +
            this._check('启用静默', 'silence.enabled', true) +
            this._wordTagEditor('唤醒词（回车添加）', 'silence.wake_phrases', [],
                '语音命中唤醒词即退出静默', '输入后回车添加') +
            this._wordTagEditor('静默词（回车添加）', 'silence.mute_phrases', [],
                '语音命中静默词即进入静默', '输入后回车添加');
    },

    // 易错词替换编辑器：正确词 -> 多个错误词,
    replaceRulesPanel(data) {
        const rules = data || {};
        let h = '';
        Object.keys(rules).forEach(correct => {
            const wrongs = Array.isArray(rules[correct]) ? rules[correct] : [];
            h += this.replaceRuleRow(correct, wrongs);
        });
        if (!Object.keys(rules).length) {
            h += `<div class="help-text">${this._t('暂无替换规则，点击下方按钮添加')}</div>`;
        }
        return h;
    },
    replaceRuleRow(correct, wrongs) {
        const wrongTags = (wrongs || []).map(w =>
            `<span class="split-tag" data-wrong="${this._esc(w)}">${this._esc(w)}<button type="button" class="split-tag-remove">&times;</button></span>`
        ).join('');
        return `<div class="replace-rule-row">
            <div class="form-group"><label>${this._t('正确词')}</label>
                <input type="text" data-replace-correct value="${this._esc(correct || '')}"></div>
            <div class="form-group"><label>${this._t('错误词（回车添加，点击 × 删除）')}</label>
                <div class="split-flag-editor replace-wrong-editor">
                    <div class="split-tags replace-wrong-tags">${wrongTags}</div>
                    <div class="split-add-row">
                        <input type="text" class="split-add-input replace-wrong-input" placeholder="${this._t('输入错误词后回车添加')}" maxlength="20">
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

    // ============ 声纹管理面板 ============,
    speakerManager() {
        return `<div class="form-section"><h4>${this._t('声纹管理')}</h4></div>
            <div id="speakerList" class="speaker-list"><div class="help-text">${this._t('加载中...')}</div></div>
            <div class="speaker-actions">
                <button class="btn btn-primary" id="speakerBuildBtn">${this._t('一键生成所有声纹')}</button>
                <button class="btn btn-secondary" id="speakerCreateBtn">${this._t('新建用户')}</button>
            </div>
            <div id="speakerBuildProgress" class="help-text" style="margin-top:8px;"></div>`;
    },

    // ============ LLM ============,
});
