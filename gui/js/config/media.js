/**
 * 配置面板生成器 - media 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
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

    // ============ VTuber / VTS 子球：配置（连接 + 身体 + 嘴部） ============,
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

    // ============ 桌宠子球：配置（连接 + 身体 + 嘴部 + 表情） ============,
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

    // ============ VTuber / VTS 子球：表情绑定（左右：左id右内容） ============,
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

    // ============ VTuber / VTS 子球：参数查询 ============,
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

    // ============ NapCat（QQ 机器人）子球 ============,
});
