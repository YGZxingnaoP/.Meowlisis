/**
 * 配置面板生成器 - song 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
    meowsingerModel() {
        const type = this._val('meowsinger.llm_type', 'deepseek');
        let h = this._section('点歌翻唱 LLM 模型') +
            this._check('启用点歌翻唱', 'meowsinger.enabled', true) +
            this._llmTypeSelect('LLM 类型', 'meowsinger.llm_type', type);
        h += `<div class="modal-tabs">
            <button class="modal-tab${type === 'deepseek' ? ' active' : ''}" data-tab="meowsinger_ds">DeepSeek</button>
            <button class="modal-tab${type === 'aliyun' ? ' active' : ''}" data-tab="meowsinger_aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab${type === 'gemini' ? ' active' : ''}" data-tab="meowsinger_gemini">Gemini</button>
        </div>`;
        h += `<div class="tab-content${type === 'deepseek' ? ' active' : ''}" data-tab-content="meowsinger_ds">` +
            this._password('API Key', 'meowsinger.deepseek.api_key', '') +
            this._text('Base URL', 'meowsinger.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'meowsinger.deepseek.model', 'deepseek-chat') +
            this._num('max_tokens', 'meowsinger.deepseek.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content${type === 'aliyun' ? ' active' : ''}" data-tab-content="meowsinger_aliyun">` +
            this._password('API Key', 'meowsinger.aliyun.api_key', '') +
            this._text('Base URL', 'meowsinger.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'meowsinger.aliyun.model', 'qwen-plus') +
            this._num('max_tokens', 'meowsinger.aliyun.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content${type === 'gemini' ? ' active' : ''}" data-tab-content="meowsinger_gemini">` +
            this._password('API Key', 'meowsinger.gemini.api_key', '') +
            this._text('Base URL', 'meowsinger.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'meowsinger.gemini.model', 'gemini-3.6-flash') +
            this._num('max_tokens', 'meowsinger.gemini.max_tokens', 2048, 1, 32768, 16) +
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
            this._section('变声参数') +
            this._select('音高提取算法', 'meowsinger.cover.f0_method', [
                {value:'rmvpe', label:'rmvpe'}, {value:'fcpe', label:'fcpe'}, {value:'pm', label:'pm'}
            ], 'rmvpe', '变调方案暂定 rmvpe，可后续在面板调整') +
            this._num('目标音高（Hz）', 'meowsinger.cover.target_f0', 325, 60, 800, 1,
                '变调目标：实测原唱 F0 后动态向该音高靠拢，不分男女') +
            this._num('音色偏移（半音）', 'meowsinger.cover.formant', 0, -12, 12, 0.1,
                '共振峰偏移：正=更细更年轻，负=更粗更成熟，0=模型原声，支持小数如 0.8') +
            this._num('索引占比', 'meowsinger.cover.index_rate', 0.75, 0, 1, 0.05,
                '越高越像目标音色，越低越像原唱') +
            this._num('清辅音保护', 'meowsinger.cover.protect', 0.33, 0, 0.5, 0.01,
                '0.5=关闭保护，越低保护越强') +
            this._num('音量包络融合', 'meowsinger.cover.rms_mix_rate', 1, 0, 1, 0.05,
                '1=不融合，有爆音可调 0.5~0.9') +
            this._select('输出采样率', 'meowsinger.cover.resample_sr', [
                {value:0, label:'0（模型默认）'}, {value:44100, label:'44100'}, {value:48000, label:'48000'}
            ], 0, '一般保持 0') +
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
    // ============ 即兴哼唱（meowsongs） ============,
    _humDetectFormula() {
        const pbt = (p, d) => this._val('meowsongs.pass_the_baton.' + p, d);
        const h = this._val('sensevoice.vad_energy_threshold', 400);
        const tSil = this._val('sensevoice.silence_threshold', 2.0);
        const collect = pbt('hum_collect_sec', 7.0);
        const rv = pbt('f0_voiced_ratio', 0.55);
        const rs = pbt('f0_stable_ratio', 0.6);
        const hs = pbt('f0_stable_half_step', 0.5);
        const notes = pbt('f0_unique_notes', 3);
        const match = pbt('match_threshold', 0.55);
        const margin = pbt('min_margin', 0.04);
        return `<div class="formula-box">
            <div class="formula-box-title">${this._t('哼唱检测算法')}</div>
            <div class="formula-block">
                <div class="formula-row">
                    <span class="formula-name">${this._t('分段')}</span>
                    <span class="formula-expr">e ≥ H → ${this._t('起段')}，silence ≥ T → ${this._t('收段')}</span>
                    <code>H=${h} T=${tSil}s</code>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('判定时机')}</span>
                    <span class="formula-expr">Σt ≥ C → judge once</span>
                    <code>C = ${collect} s</code>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('有声帧')}</span>
                    <span class="formula-expr">v = V / F ≥ R<sub>v</sub></span>
                    <code>pyin 65~800Hz, p&gt;0.3</code>
                    <code>R<sub>v</sub> = ${rv}</code>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('稳定帧')}</span>
                    <span class="formula-expr">s = mean(|Δmidi| &lt; h) ≥ R<sub>s</sub></span>
                    <code>h=${hs} R<sub>s</sub>=${rs}</code>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('音符数')}</span>
                    <span class="formula-expr">n = |unique(round(midi))| ≥ N</span>
                    <code>N = ${notes}</code>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('判定')}</span>
                    <span class="formula-expr">hum ⟺ v ∧ s ∧ n</span>
                    <code>V ≥ 3</code>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('匹配')}</span>
                    <span class="formula-expr">score = max<sub>w</sub> cos(ref[w:w+|q|], q)</span>
                    <code>M = ${match}</code>
                    <code>margin = ${margin}</code>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('接唱')}</span>
                    <span class="formula-expr">offset = w* · hop / SR</span>
                    <code>hop 256 / SR 16k</code>
                </div>
            </div>
            <div class="formula-params">${this._t('F0 转半音后去均值再滑窗余弦；未锁定或分差不足按歧义处理，交给角色自己确认。')}</div>
        </div>`;
    },
    meowsongs() {
        return this._section('即兴哼唱（触发型工具）') +
            this._check('启用即兴哼唱', 'meowsongs.enabled', true,
                'AI 根据用户消息判断是否即兴哼唱已学歌曲片段（不带伴奏，只播放翻唱人声）') +
            this._section('清唱静音压缩') +
            this._check('启用清唱静音压缩', 'meowsongs.squeeze.enabled', true,
                '清唱时把长于阈值的伴奏空档压掉，只保留换气间隔（不改动曲库文件）') +
            this._num('最短切割间隔（秒）', 'meowsongs.squeeze.min_gap_sec', 4.8, 2, 30, 0.1,
                '连续静音超过该秒数才切，避免把正常换气或小声唱当成空档') +
            this._num('切口前保留（秒）', 'meowsongs.squeeze.head_keep_sec', 0.9, 0, 5, 0.1,
                '切开后，前一段人声末尾保留的呼吸时长') +
            this._num('切口后保留（秒）', 'meowsongs.squeeze.tail_keep_sec', 1.1, 0, 5, 0.1,
                '切开后，后一段人声开头保留的呼吸时长') +
            this._num('静音判定阈值（低于峰值 dB）', 'meowsongs.squeeze.rel_db', 45, 20, 80, 1,
                '帧电平低于参考电平该分贝数才判静音，数值越大越保守，小声唱越不容易被误切') +
            this._num('静音绝对下限（dBFS）', 'meowsongs.squeeze.abs_db', -60, -90, -20, 1,
                '低于该电平才可能判为静音，曲库底噪偏高时可适当上调') +
            this._section('听歌识曲接龙') +
            this._humDetectFormula() +
            this._check('启用听歌识曲接龙', 'meowsongs.pass_the_baton.enabled', false,
                '用户哼唱一段后，AI 识别歌曲并接着往下唱（依赖哼唱检测与本地曲库）') +
            this._num('往后唱几句', 'meowsongs.pass_the_baton.hum_lines', 2, 1, 10, 1,
                '识别命中后接着唱的歌词句数，默认 2') +
            this._num('音高发声占比', 'meowsongs.pass_the_baton.f0_voiced_ratio', 0.55, 0.1, 1, 0.01,
                'pyin 有声帧占比阈值，越高要求哼唱越连续') +
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
            this._num('歧义分差下限', 'meowsongs.pass_the_baton.min_margin', 0.04, 0, 0.5, 0.01,
                '最佳与次优候选的分差低于该值时视为歧义，交给角色确认是否在唱') +
            this._area('接龙感想引导词', 'meowsongs.pass_the_baton.feeling_prompt', '',
                '接龙命中后发表感想的引导词，{title}=歌名、{lyric}=歌词');
    },

    // ============ 数据库（database）子球 ============,
});
