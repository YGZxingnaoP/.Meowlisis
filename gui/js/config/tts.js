/**
 * 配置面板生成器 - tts 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
    tts() {
        let h = this._section('TTS 语音合成') +
            this._select('语音合成引擎', 'tts.select', [{value:'gpt-sovits',label:'GPT-SoVITS'}], 'gpt-sovits') +
            this._text('GPT-SoVITS 服务地址', 'tts.gpt-sovits.gpt_sovits_url', 'http://127.0.0.1:9880') +
            this._text('输出目录', 'tts.output_dir', './output') +
            this._num('音量', 'tts.volume', 1.0, 0, 2, 0.1) +
            this._num('合成线程数', 'tts.synth_workers', 2, 1, 8, 1) +
            this._select('打断模式', 'tts.interrupt.mode', [
                {value:'pipeline',label:'pipeline'},{value:'keyboard',label:'keyboard'},{value:'off',label:'off'}
            ], 'pipeline') +
            this._text('打断按键', 'tts.interrupt.key', 'f8') +
            this._num('打断轮询间隔(秒)', 'tts.interrupt.poll_interval', 0.1, 0.01, 1, 0.01);
        h += `<div id="refAudioPanel"></div><div id="ttsModelPanel"></div>`;
        return h;
    },

    // ============ TTS 子球：模型配置（参考音频 + 模型权重） ============,
    tts_model_panel(data, models) {
        const c = data || {};
        const ckpts = (models && models.ckpt) || [];
        const pths = (models && models.pth) || [];
        let h = this._section('参考音频配置（按角色名绑定）');
        h += `<div id="refAudioPanel"></div>`;
        h += this.emotionParamsPanel();
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

    // ============ TTS 子球：参数配置（合成参数 + 流式参数 + 播放） ============,
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

    // ============ TTS 子球：配置（打断 + 流式开关 + 服务引擎） ============,
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

    // 情绪采样参数配置面板（emotion_params，每个情绪可覆盖基础采样参数）,
    emotionParamsPanel() {
        const emotions = ['happy', 'sad', 'call', 'angry', 'blush', 'approve', 'sweat', 'blood', 'love', 'wordless'];
        const labels = { happy: '开心', sad: '难过', call: '呼唤', angry: '生气', blush: '害羞', approve: '认可', sweat: '尴尬', blood: '震惊', love: '撒娇', wordless: '无语' };
        const fields = [
            { key: 'speed', label: '语速', step: 0.05, min: 0.5, max: 2.0 },
            { key: 'temperature', label: '温度', step: 0.05, min: 0, max: 2.0 },
            { key: 'noise_scale', label: '噪声缩放', step: 0.05, min: 0, max: 2.0 },
            { key: 'top_k', label: 'Top K', step: 1, min: 1, max: 50 },
            { key: 'top_p', label: 'Top P', step: 0.05, min: 0, max: 1.0 },
            { key: 'repetition_penalty', label: '重复惩罚', step: 0.05, min: 1.0, max: 2.0 }
        ];
        let h = this._section('情绪采样参数（留空 = 继承基础采样参数）');
        emotions.forEach((emo, i) => {
            h += `<details class="ref-fold ref-fold-emotion"${i === 0 ? ' open' : ''}>
                <summary class="ref-fold-summary"><span class="emotion-tag">${emo}</span><span class="emotion-cn">${labels[emo] || ''}</span><span class="ref-fold-arrow">▾</span></summary>
                <div class="ref-fold-body emotion-param-grid">`;
            fields.forEach(f => {
                const path = `tts.gpt-sovits.emotion_params.${emo}.${f.key}`;
                const v = this._val(path, '');
                const shown = (v === '' || v == null) ? '' : v;
                h += `<div class="form-group"><label>${f.label}</label>
                    <input type="number" data-path="${path}" value="${shown}" step="${f.step}" min="${f.min}" max="${f.max}" placeholder="继承基础值"></div>`;
            });
            h += `</div></details>`;
        });
        return h;
    },

    // 参考音频配置面板（异步加载 ref_audio/config.json 后填充）
    // 支持多情绪格式：{角色名: {情绪: {audio, text, lang}}}，兼容旧单条格式 {角色名: {audio, text, lang}},
    refAudioPanel(data) {
        const map = data || {};
        let h = this._section('参考音频配置（按角色名绑定 · 多情绪）');
        if (!Object.keys(map).length) {
            h += `<div class="help-text">暂无参考音频配置</div>`;
            return h;
        }
        Object.keys(map).forEach((name, i) => {
            const item = map[name] || {};
            // 判断是否多情绪格式：任意 value 是含 audio 字段的对象
            const isMulti = Object.values(item).some(v => v && typeof v === 'object' && 'audio' in v);
            const subCount = isMulti ? Object.keys(item).length : 1;
            h += `<details class="ref-fold"${i === 0 ? ' open' : ''}>
                <summary class="ref-fold-summary"><span class="ref-fold-name">${this._esc(name)}</span><span class="ref-fold-meta">${subCount} 个情绪</span><span class="ref-fold-arrow">▾</span></summary>
                <div class="ref-fold-body">`;
            if (isMulti) {
                Object.keys(item).forEach(emotion => {
                    const e = item[emotion] || {};
                    h += `<details class="ref-fold ref-fold-emotion">
                        <summary class="ref-fold-summary ref-fold-sub"><span class="emotion-tag">${this._esc(emotion)}</span><span class="ref-fold-arrow">▾</span></summary>
                        <div class="ref-fold-body">
                            <div class="form-group"><label>音频路径</label>
                                <input type="text" data-ref-audio-name="${this._escAttr(name)}" data-ref-audio-emotion="${this._escAttr(emotion)}" data-ref-audio-field="audio" value="${this._escAttr(e.audio || '')}"></div>
                            <div class="form-group"><label>参考文本</label>
                                <textarea class="auto-grow" rows="2" data-ref-audio-name="${this._escAttr(name)}" data-ref-audio-emotion="${this._escAttr(emotion)}" data-ref-audio-field="text">${this._esc(e.text || '')}</textarea></div>
                            <div class="form-group"><label>语言</label>
                                <input type="text" data-ref-audio-name="${this._escAttr(name)}" data-ref-audio-emotion="${this._escAttr(emotion)}" data-ref-audio-field="lang" value="${this._escAttr(e.lang || 'zh')}"></div>
                        </div>
                    </details>`;
                });
            } else {
                // 旧单条格式兼容
                h += `<div class="form-group"><label>音频路径</label>
                    <input type="text" data-ref-audio-name="${this._escAttr(name)}" data-ref-audio-field="audio" value="${this._escAttr(item.audio || '')}"></div>
                <div class="form-group"><label>参考文本</label>
                    <textarea class="auto-grow" rows="2" data-ref-audio-name="${this._escAttr(name)}" data-ref-audio-field="text">${this._esc(item.text || '')}</textarea></div>
                <div class="form-group"><label>语言</label>
                    <input type="text" data-ref-audio-name="${this._escAttr(name)}" data-ref-audio-field="lang" value="${this._escAttr(item.lang || 'zh')}"></div>`;
            }
            h += `</div></details>`;
        });
        return h;
    },

    // TTS 模型配置面板（异步加载 tts_infer.yaml 后填充，扁平结构）,
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

    // ============ 弹幕 ============,
});
