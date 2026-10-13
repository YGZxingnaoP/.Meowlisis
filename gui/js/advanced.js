/**
 * 精简卡片 + 高级设置
 *
 * 精简：Config.SIMPLE[卡片id] = 该卡点开只保留的配置项，其余裁掉（Modal.show 后处理）。
 * 高级设置：左侧分类 → 中间**原地渲染原面板**（把 Modal.show 重定向到中间区，
 *          面板自身的绑定/保存逻辑照旧可用，不另写一套）；另含「原始配置」全量编辑器。
 */
(function () {
    if (typeof Config === 'undefined' || typeof Modal === 'undefined') return;

    function T(s, vars) {
        if (typeof Config._t === 'function') return Config._t(s, vars);
        if (typeof window._t === 'function') return window._t(s, vars);
        return s;
    }

    // ==================== 1. 卡片精简白名单 ====================
    Config.SIMPLE = {
        'basic': ['AiName', 'app.port'],
        'sensevoice_config': ['sensevoice.enabled', 'sensevoice.server_url', 'sensevoice.mode', 'sensevoice.target_speakers', 'sensevoice.vad_energy_threshold'],
        'sensevoice_audio': ['audio.sources.mic.enabled', 'audio.sources.inject.enabled', 'audio.sources.loopback.enabled', 'audio.rate', 'audio.resample_converter'],
        'llm_model': ['llm.deepseek.model', 'llm.aliyun.model', 'llm.gemini.model', 'llm.deepseek.enable_thinking', 'llm.aliyun.enable_thinking', 'llm.gemini.enable_thinking', 'llm.short_term_rounds', 'llm.split_limit'],
        'llm_algorithm': ['llm.narration.enabled', 'llm.narration.length_threshold', 'llm.narration.density_threshold'],
        'active_config': ['llm_active.cold_time', 'llm_active.n', 'llm_active.active_mem_limit'],
        'active_browse': ['llm_active.web_browse.enabled', 'llm_active.web_browse.interval', 'llm_active.web_browse.max_cache', 'llm_active.web_browse.allow_topics', 'llm_active.web_browse.mid', 'llm_active.web_browse.sessdata', 'llm_active.vision.model'],
        'abstract': ['catbrain.abstract_mem.summary_rounds', 'catbrain.abstract_mem.topic_update_interval', 'catbrain.abstract_mem.min_importance', 'catbrain.abstract_mem.recent_memory_lines', 'catbrain.abstract_mem.llm_type', 'catbrain.abstract_mem.deepseek.model', 'catbrain.abstract_mem.aliyun.model', 'catbrain.abstract_mem.gemini.model'],
        'rulesbreak': ['rulebreak.enabled_qq', 'rulebreak.enabled_msg', 'rulebreak.affinity_min', 'rulebreak.deepseek.model'],
        'values': ['catbrain.cat_values.llm_type', 'catbrain.cat_values.deepseek.model', 'catbrain.cat_values.aliyun.model', 'catbrain.cat_values.gemini.model', 'catbrain.cat_values.update_interval_hours', 'catbrain.cat_values.timer_check_seconds', 'catbrain.cat_values.second_review.enabled'],
        'usermem': ['catbrain.user_memory.update_rounds', 'catbrain.user_memory.llm_type', 'catbrain.user_memory.deepseek.model', 'catbrain.user_memory.aliyun.model', 'catbrain.user_memory.gemini.model'],
        'db_search': ['database.search.temperature', 'database.search.deepseek.model', 'database.search.aliyun.model', 'database.search.agent.max_rounds', 'database.record.max_messages', 'database.record.rounds'],
        'db_store': ['database.store.embedding.dimension', 'database.store.embedding.aliyun.model', 'database.store.embedding.siliconflow.model', 'database.store.top_k', 'database.store.keyword_top_k', 'database.store.db_dir'],
        'vts_config': ['emote.switch', 'emote.vtuber_websocket', 'emote.vtuber_authenticationToken', 'emote.mouth_sync.enabled'],
        'desktopet': ['desktopet_emote.switch', 'desktopet_emote.vtuber_websocket', 'desktopet_emote.vtuber_authenticationToken', 'desktopet_emote.mouth_sync.enabled'],
        'meowsinger_model': ['meowsinger.enabled', 'meowsinger.deepseek.model', 'meowsinger.aliyun.model', 'meowsinger.gemini.model'],
        'meowsinger_song': ['meowsinger.song.enabled', 'meowsinger.song.prefix', 'meowsinger.song.intent', 'meowsinger.song.netease_url'],
        'meowsinger_sentiment': ['meowsinger.sentiment.enabled', 'meowsinger.sentiment.word_count'],
        'tts_config': ['tts.select', 'tts.gpt-sovits.gpt_sovits_url', 'tts.output_dir', 'tts.interrupt.mode', 'tts.interrupt.key', 'tts.gpt-sovits.streaming_mode', 'tts.gpt-sovits.text_lang'],
        'tts_params': ['tts.gpt-sovits.min_chunk_length', 'tts.gpt-sovits.sample_rate', 'tts.volume', 'tts.seg_min_len'],
        'center': ['toolbox.llm_type', 'toolbox.excuse_enabled', 'toolbox.excuse_timeout'],
        'minecraft': ['minecraft.enabled', 'minecraft.log_path', 'minecraft.encoding', 'minecraft.username_fixed'],
        'meowvision': ['meowvision.model', 'meowvision.cache_dir', 'meowvision.watching.enabled'],
        'napcat_account': ['napcat.enabled', 'napcat.ws_url', 'napcat.access_token', 'napcat.self_nickname'],
        'napcat_private': ['napcat.private_reply_enabled', 'napcat.reply_word_count', 'napcat.history_limit', 'napcat.short_mem_rounds', 'napcat.thinking_level', 'napcat.emote_enabled'],
        'napcat_group': ['napcat.group_reply_enabled', 'napcat.group_reply_word_count', 'napcat.group_bots', 'napcat.group_keyword_reply.enabled', 'napcat.group_keyword_reply.keywords', 'napcat.group_active_enabled', 'napcat.group_reply_base'],
        'danmaku': ['danmaku.blivedm.enabled', 'danmaku.blivedm.room_id', 'danmaku.blivedm.sessdata', 'danmaku.blivedm.bili_jct', 'danmaku.read_aloud_enabled', 'danmaku.read_aloud_mode', 'danmaku.active_send.enabled', 'danmaku.active_send.cooldown'],
        'meowsongs': ['meowsongs.enabled', 'meowsongs.max_duration', 'meowsongs.pass_the_baton.enabled'],
        'turtle_soup': ['turtle_soup.enabled', 'turtle_soup.qq_enabled', 'turtle_soup.bank_dir', 'turtle_soup.cache_dir'],
        'flux_painter_service': ['flux_painter.enabled', 'flux_painter.comfy.mode', 'flux_painter.comfy.port', 'flux_painter.http_port', 'flux_painter.comfy.internal_python'],
        'flux_painter_model': ['flux_painter.unet_model', 'flux_painter.quality_mode', 'flux_painter.adult_mode'],
        'flux_painter_prompt': ['flux_painter.quality_prefix', 'flux_painter.negative_prompt', 'flux_painter.style_on_keywords'],
        'flux_painter_workflow': ['flux_painter.sampler_steps', 'flux_painter.sampler_cfg', 'flux_painter.sampler_name', 'flux_painter.quality_mode']
    };

    Config.filterSimple = function (root, cardId) {
        const keep = Config.SIMPLE[cardId];
        if (!keep || !root) return;
        root.querySelectorAll('[data-path]').forEach(function (el) {
            const p = el.dataset.path || '';
            const hit = keep.some(function (k) { return p === k || p.indexOf(k + '.') === 0; });
            if (!hit) {
                const g = el.closest('.form-group');
                if (g) g.remove();
            }
        });
        root.querySelectorAll('.form-section').forEach(function (s) {
            const n = s.nextElementSibling;
            if (!n || (n.classList && n.classList.contains('form-section'))) s.remove();
        });
    };

    // ==================== 2. 分类表（id 与卡片 id 对齐，kind 决定走哪条打开逻辑） ====================
    const GROUPS = [
        { t: '基础', items: [
            { id: 'identity_users', t: '用户 ID', kind: 'render', build: function () { return Config.identityUsers(); } },
            { id: 'basic', t: '基础设置', kind: 'planet' },
            { id: 'api_platforms', t: 'API 平台', kind: 'render', build: function () { return Config.apiPlatforms(); } },
            { id: 'character', t: '角色卡', kind: 'planet' },
            { id: 'subtitle', t: '字幕', kind: 'planet' },
            { id: 'calendar', t: '待办', kind: 'planet' }
        ] },
        { t: '语音', items: [
            { id: 'sensevoice_config', t: '语音识别', kind: 'planet' },
            { id: 'sensevoice_mic', t: '闭麦', kind: 'planet' },
            { id: 'sensevoice_audio', t: '音频采集', kind: 'planet' },
            { id: 'tts_config', t: 'TTS 配置', kind: 'planet' },
            { id: 'tts_model', t: 'TTS 模型', kind: 'planet' },
            { id: 'tts_params', t: 'TTS 参数', kind: 'planet' },
            { id: 'tts_pause', t: 'TTS 间隔', kind: 'planet' }
        ] },
        { t: '大脑', items: [
            { id: 'llm_model', t: 'LLM 模型', kind: 'planet' },
            { id: 'llm_prompt', t: 'LLM 提示词', kind: 'planet' },
            { id: 'llm_algorithm', t: 'LLM 算法', kind: 'planet' },
            { id: 'active_config', t: '主动回复', kind: 'planet' },
            { id: 'active_browse', t: 'B站浏览', kind: 'planet' },
            { id: 'ltmem', t: '长期记忆', kind: 'planet' },
            { id: 'abstract', t: '记忆摘要', kind: 'planet' },
            { id: 'rulesbreak', t: '原则词', kind: 'planet' },
            { id: 'values', t: '价值观', kind: 'planet' },
            { id: 'usermem', t: '用户记忆', kind: 'planet' },
            { id: 'db_search', t: '搜索学习', kind: 'planet' },
            { id: 'db_store', t: '知识存储', kind: 'planet' },
            { id: 'db_source', t: '数据来源', kind: 'planet' },
            { id: 'db_prefill', t: '知识预填', kind: 'planet' }
        ] },
        { t: '形象', items: [
            { id: 'vts_config', t: 'VTS 配置', kind: 'planet' },
            { id: 'vts_emotion', t: 'VTS 表情', kind: 'planet' },
            { id: 'desktopet', t: '桌宠', kind: 'planet' },
            { id: 'vts_params', t: 'VTS 参数', kind: 'planet' }
        ] },
        { t: '娱乐', items: [
            { id: 'meowsinger_model', t: '歌曲模型', kind: 'planet' },
            { id: 'meowsinger_song', t: '点歌', kind: 'planet' },
            { id: 'meowsinger_cover', t: '翻唱', kind: 'planet' },
            { id: 'meowsinger_sentiment', t: '感想', kind: 'planet' },
            { id: 'danmaku', t: '弹幕', kind: 'toolbox' }
        ] },
        { t: '工具箱', items: [
            { id: 'center', t: '父级模型', kind: 'toolbox' },
            { id: 'minecraft', t: 'Minecraft', kind: 'toolbox' },
            { id: 'meowvision', t: '视觉', kind: 'toolbox' },
            { id: 'napcat_account', t: 'NapCat 角色名', kind: 'toolbox' },
            { id: 'napcat_private', t: 'NapCat 私聊', kind: 'toolbox' },
            { id: 'napcat_group', t: 'NapCat 群聊', kind: 'toolbox' },
            { id: 'napcat_send', t: 'NapCat 主动发送', kind: 'toolbox' },
            { id: 'weather', t: '天气', kind: 'toolbox' },
            { id: 'news', t: '新闻', kind: 'toolbox' },
            { id: 'add_backlog', t: '提醒', kind: 'toolbox' },
            { id: 'meowsongs', t: '哼唱', kind: 'toolbox' },
            { id: 'turtle_soup', t: '海龟汤', kind: 'toolbox' },
            { id: 'flux_painter_service', t: '绘画·服务', kind: 'toolbox' },
            { id: 'flux_painter_model', t: '绘画·模型', kind: 'toolbox' },
            { id: 'flux_painter_prompt', t: '绘画·提示词', kind: 'toolbox' },
            { id: 'flux_painter_workflow', t: '绘画·工作流', kind: 'toolbox' },
            { id: 'plugins', t: '插件', kind: 'plugins' }
        ] },
        { t: '全量', items: [
            { id: 'raw_config', t: '原始配置（全部键）', kind: 'raw' }
        ] }
    ];

    // 原始配置中文标签（仅顶层，缺省显示键名）
    const LABELS = {
        AiName: 'AI 名称', app: '应用', audio: '音频采集', catbrain: 'CatBrain', character_card: '角色卡',
        danmaku: '弹幕', database: '数据库', desktopet_emote: '桌宠', emote: 'VTS', flux_painter: '绘画',
        llm: 'LLM', llm_active: '主动回复', meowsinger: '歌曲', meowsongs: '哼唱', meowvision: '视觉',
        minecraft: 'Minecraft', napcat: 'NapCat', news: '新闻', rulebreak: '原则词', sensevoice: '语音识别',
        silence: '闭麦', toolbox: '工具箱', tts: 'TTS', turtle_soup: '海龟汤', weather: '天气',
        add_backlog: '提醒', rewards: '奖励', plugins: '插件'
    };

    // ==================== 3. 高级设置 ====================
    const Adv = {
        built: false,
        hosting: false,
        bodyEl: null,
        onSave: null,
        activeId: null,

        flatten: function () {
            const out = [];
            GROUPS.forEach(function (g) { g.items.forEach(function (it) { out.push(Object.assign({ group: g.t }, it)); }); });
            return out;
        },

        ensure: function () {
            if (this.built) return;
            const ov = document.createElement('div');
            ov.className = 'adv-overlay';
            ov.id = 'advOverlay';
            ov.innerHTML =
                '<div class="adv-panel">' +
                    '<div class="adv-side">' +
                        '<div class="adv-side-title">高级设置</div>' +
                        '<div class="adv-side-list" id="advSideList"></div>' +
                    '</div>' +
                    '<div class="adv-main">' +
                        '<div class="adv-head"><h3 id="advTitle">高级设置</h3><button class="adv-close" id="advClose">&times;</button></div>' +
                        '<div class="adv-body" id="advBody"></div>' +
                        '<div class="adv-foot"><span class="adv-note" id="advNote"></span><button class="btn btn-primary" id="advSave">保存</button></div>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(ov);
            this.bodyEl = ov.querySelector('#advBody');
            const sideTitle = ov.querySelector('.adv-side-title');
            if (sideTitle) sideTitle.textContent = T('高级设置');

            const list = ov.querySelector('#advSideList');
            GROUPS.forEach(function (g) {
                const h = document.createElement('div');
                h.className = 'adv-group';
                h.textContent = T(g.t);
                list.appendChild(h);
                g.items.forEach(function (it) {
                    const a = document.createElement('div');
                    a.className = 'adv-item';
                    a.textContent = T(it.t);
                    a.dataset.id = it.id;
                    a.addEventListener('click', function () { Adv.open(it.id); });
                    list.appendChild(a);
                });
            });

            ov.querySelector('#advClose').addEventListener('click', function () { Adv.close(); });
            ov.addEventListener('click', function (e) { if (e.target === ov) Adv.close(); });
            ov.querySelector('#advSave').addEventListener('click', function () { Adv.save(); });
            this.built = true;
        },

        find: function (id) {
            const all = this.flatten();
            for (let i = 0; i < all.length; i++) if (all[i].id === id) return all[i];
            return null;
        },

        mark: function (id) {
            this.activeId = id;
            document.querySelectorAll('#advSideList .adv-item').forEach(function (a) {
                a.classList.toggle('active', a.dataset.id === id);
            });
        },

        open: function (id) {
            this.ensure();
            document.getElementById('advOverlay').classList.add('show');
            document.body.style.overflow = 'hidden';
            const item = (id && this.find(id)) || this.flatten()[0];
            this.mark(item.id);
            document.getElementById('advTitle').textContent = T(item.t);
            const note = document.getElementById('advNote');
            note.textContent = '';
            clearTimeout(this._guard);

            if (item.kind === 'raw') {
                this.unhost();
                this.onSave = null;
                this.renderRaw();
                note.textContent = T('原始配置：直接编辑全部键（数组/对象用 JSON）');
                return;
            }
            if (item.kind === 'render') {
                this.unhost();
                this.onSave = null;
                this.bodyEl.innerHTML = item.build ? item.build() : '';
                Modal.initAutoGrow(this.bodyEl);
                this.binds();
                note.textContent = T('整块配置，可直接编辑并保存');
                return;
            }
            if (item.kind === 'plugins') {
                this.unhost();
                this.onSave = null;
                this.renderPlugins();
                note.textContent = T('选择一个插件，进入其配置');
                return;
            }

            this.host();
            this.onSave = null;
            this.bodyEl.innerHTML = '<div class="help-text">' + T('加载中…') + '</div>';
            const self = this;
            this._guard = setTimeout(function () { self.hosting = false; }, 6000);
            try {
                if (item.kind === 'toolbox') {
                    if (window.App && App.onToolboxPlanetClick) App.onToolboxPlanetClick(item.id);
                } else {
                    if (window.App && App.onPlanetClick) App.onPlanetClick(item.id);
                }
            } catch (e) {
                console.error('[Adv] open failed', item.id, e);
                this.hosting = false;
                this.bodyEl.innerHTML = '<div class="help-text">' + T('打开失败：') + (e && e.message ? e.message : e) + '</div>';
            }
        },

        openPlugin: function (pid) {
            this.ensure();
            this.host();
            this.onSave = null;
            document.getElementById('advTitle').textContent = T('插件') + ' · ' + pid;
            document.getElementById('advNote').textContent = '';
            this.bodyEl.innerHTML = '<div class="help-text">' + T('加载中…') + '</div>';
            const self = this;
            clearTimeout(this._guard);
            this._guard = setTimeout(function () { self.hosting = false; }, 6000);
            if (window.App && App.openPluginPanel) App.openPluginPanel(pid);
        },

        renderPlugins: function () {
            const list = (window.App && App.plugins) || [];
            let h = '<div class="form-section"><h4>' + T('插件') + '</h4></div>';
            if (!list.length) {
                h += '<div class="help-text">' + T('暂无插件') + '</div>';
            } else {
                list.forEach(function (p) {
                    h += '<div class="form-group"><button type="button" class="btn btn-secondary" data-plugin="'
                        + Adv.esc(p.id) + '">' + Adv.esc(p.title || p.id) + T(' · 配置') + '</button></div>';
                });
            }
            this.bodyEl.innerHTML = h;
            this.bodyEl.querySelectorAll('[data-plugin]').forEach(function (b) {
                b.addEventListener('click', function () { Adv.openPlugin(b.dataset.plugin); });
            });
        },

        binds: function () {
            try {
                if (App.bindTabs) App.bindTabs();
                if (App.bindSplitFlagEditor) App.bindSplitFlagEditor();
                if (App.bindWordTagEditor) App.bindWordTagEditor();
                if (App.bindDictEditors) App.bindDictEditors();
                if (App.bindTriggerMode) App.bindTriggerMode();
                if (App.bindSessdataVerify) App.bindSessdataVerify();
                if (App.bindBiliLogin) App.bindBiliLogin();
                if (App.bindVtsParamsQuery) App.bindVtsParamsQuery();
            } catch (e) { console.error('[Adv] bind failed', e); }
        },

        // 把 id=modalBody 让给中间区，令原面板的 collectValues()/绑定 照常工作
        host: function () {
            const real = document.getElementById('modalBody');
            if (real && real.id !== 'modalBody_stash') real.id = 'modalBody_stash';
            if (this.bodyEl) this.bodyEl.id = 'modalBody';
            this.hosting = true;
        },

        unhost: function () {
            if (this.bodyEl) this.bodyEl.id = 'advBody';
            const stashed = document.getElementById('modalBody_stash');
            if (stashed) stashed.id = 'modalBody';
            this.hosting = false;
        },

        _hostPanel: function (title, html, onSave) {
            clearTimeout(this._guard);
            this.hosting = false;
            document.getElementById('advTitle').textContent = T(title || '高级设置');
            if (this.bodyEl) {
                this.bodyEl.innerHTML = html;
                Modal.initAutoGrow(this.bodyEl);
            }
            this.onSave = (typeof onSave === 'function') ? onSave : null;
            const self = this;
            setTimeout(function () { self.binds(); }, 10);
        },

        // ---- 原始配置：整棵 config 树 ----
        renderRaw: function () {
            this.bodyEl.innerHTML = this.nodeHtml('', App.config, true);
            Modal.initAutoGrow(this.bodyEl);
        },

        nodeHtml: function (path, val, top) {
            const self = this;
            if (val === null || typeof val !== 'object') return this.leafHtml(path, val);
            if (Array.isArray(val)) return this.jsonHtml(path, val);
            const keys = Object.keys(val);
            if (!keys.length) return this.jsonHtml(path, val);
            let h = '';
            keys.forEach(function (k) {
                const p = path ? path + '.' + k : k;
                const v = val[k];
                if (v !== null && typeof v === 'object') {
                    const label = (top && LABELS[k]) ? T(LABELS[k]) + '（' + k + '）' : k;
                    h += '<div class="form-section"><h4>' + self.esc(label) + '</h4></div>';
                    h += self.nodeHtml(p, v, false);
                } else {
                    h += self.leafHtml(p, v);
                }
            });
            return h;
        },

        leafHtml: function (path, val) {
            const label = path;
            if (typeof val === 'boolean') {
                return '<div class="form-group"><div class="checkbox-group"><input type="checkbox" data-path="' + this.esc(label) + '"' + (val ? ' checked' : '') + '><label>' + this.esc(label) + '</label></div></div>';
            }
            if (typeof val === 'number') {
                return '<div class="form-group"><label>' + this.esc(label) + '</label><input type="number" step="any" data-path="' + this.esc(label) + '" value="' + val + '"></div>';
            }
            const s = (val === null || val === undefined) ? '' : String(val);
            if (s.indexOf('\n') >= 0 || s.length > 80) {
                return '<div class="form-group"><label>' + this.esc(label) + '</label><textarea class="auto-grow" rows="3" data-path="' + this.esc(label) + '">' + this.esc(s) + '</textarea></div>';
            }
            return '<div class="form-group"><label>' + this.esc(label) + '</label><input type="text" data-path="' + this.esc(label) + '" value="' + this.esc(s) + '"></div>';
        },

        jsonHtml: function (path, val) {
            const s = JSON.stringify(val, null, 2);
            return '<div class="form-group"><label>' + this.esc(path) + T('（JSON）') + '</label><textarea class="auto-grow" rows="6" data-json="1" data-path="' + this.esc(path) + '">' + this.esc(s) + '</textarea></div>';
        },

        esc: function (s) {
            return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        },

        close: function () {
            this.unhost();
            const ov = document.getElementById('advOverlay');
            if (ov) ov.classList.remove('show');
            if (!document.body.classList.contains('modal-open')) document.body.style.overflow = '';
        },

        // ---- 保存：面板自带 onSave 优先，否则通用收集 ----
        save: async function () {
            try {
                if (this.onSave) {
                    await this.onSave();
                    if (App.showToast) App.showToast(T('配置已保存（重启对应服务后生效）'));
                    return;
                }
                const updates = [];
                const scope = this.bodyEl;
                scope.querySelectorAll('[data-path]').forEach(function (el) {
                    const path = el.dataset.path;
                    let value;
                    if (el.dataset.json) {
                        const t = el.value.trim();
                        try { value = t ? JSON.parse(t) : {}; } catch (e) { throw new Error(T('JSON 格式错误：') + path); }
                    } else if (el.type === 'checkbox') value = el.checked;
                    else if (el.type === 'number') { if (el.value === '') return; value = parseFloat(el.value); }
                    else value = el.value;
                    updates.push({ path: path, value: value });
                });
                Config.applyUpdates(updates, App.config);
                await API.saveConfig(App.config);
                if (App.showToast) App.showToast(T('配置已保存（重启主程序后生效）'));
            } catch (e) {
                if (App.showToast) App.showToast(T('保存失败: ') + (e && e.message ? e.message : e), true);
                else alert(T('保存失败: ') + (e && e.message ? e.message : e));
            }
        }
    };
    window.Adv = Adv;

    // ==================== 4. 接管 Modal.show（精简 + 重定向到高级设置） ====================
    const origShow = Modal.show;
    Modal.show = function (title, html, onSave, fromEl) {
        if (Adv.hosting) { Adv._hostPanel(title, html, onSave); return; }
        origShow.call(this, title, html, onSave, fromEl);
        const ov = document.getElementById('advOverlay');
        const fromAdv = ov && ov.classList.contains('show');
        const btn = document.getElementById('modalMore');
        if (fromAdv) { if (btn) btn.style.display = 'none'; return; }
        const cardId = (Modal.source && Modal.source.dataset) ? Modal.source.dataset.id : null;
        if (cardId && Config.SIMPLE[cardId]) {
            Config.filterSimple(Modal.getBody(), cardId);
            if (btn) { btn.style.display = ''; btn.dataset.target = cardId; }
        } else if (btn) {
            btn.style.display = 'none';
        }
    };

    // ==================== 5. 入口与按钮 ====================
    function addEntry() {
        const ls = document.getElementById('langSwitch');
        if (!ls || document.getElementById('advEntry')) return;
        const b = document.createElement('button');
        b.id = 'advEntry';
        b.type = 'button';
        b.className = 'adv-entry';
        b.textContent = T('高级设置');
        b.addEventListener('click', function () { Adv.open(); });
        ls.parentNode.insertBefore(b, ls.nextSibling);
    }

    function addMoreButton() {
        const footer = document.querySelector('#modalWindow .modal-footer');
        if (!footer || document.getElementById('modalMore')) return;
        const b = document.createElement('button');
        b.id = 'modalMore';
        b.type = 'button';
        b.className = 'btn btn-secondary';
        b.textContent = T('更多设置 →');
        b.style.display = 'none';
        b.addEventListener('click', function () {
            const id = b.dataset.target;
            Modal.hide();
            Adv.open(id);
        });
        footer.insertBefore(b, footer.firstChild);
    }

    document.addEventListener('DOMContentLoaded', function () {
        addEntry();
        addMoreButton();
    });
})();
