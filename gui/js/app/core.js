/**
 * 应用控制器 - core 模块
 * 由 app.js 拆分而来，统一挂载到全局 App 对象
 */

const App = {
    config: null,
    calendarData: {},

    _t(s) {
        try {
            if (typeof I18n !== 'undefined' && I18n && I18n.text) return I18n.text(s);
        } catch (e) { /* ignore */ }
        return s;
    },

    async init() {
        Modal.init();
        Orbit.init();

        // Toolbox 子视图关闭
        const toolboxClose = document.getElementById('toolboxClose');
        if (toolboxClose) {
            toolboxClose.addEventListener('click', () => this.closeToolbox());
        }
        const toolboxOverlay = document.getElementById('toolboxOverlay');
        if (toolboxOverlay) {
            toolboxOverlay.addEventListener('click', (e) => {
                if (e.target === toolboxOverlay) this.closeToolbox();
            });
        }

        try {
            this.config = await API.getConfig();
            window._config = this.config;
            Config.setConfig(this.config);
        } catch (e) {
            this.showToast('加载配置失败: ' + e.message, true);
        }
    },

    // ============ 服务启动球 ============,
    async onLaunchClick(id) {
        const map = {
            phone: { fn: () => API.startPhone(), name: '接口' },
            sensevoice: { fn: () => API.startSensevoice(), name: 'SenseVoice' },
            sovits: { fn: () => API.startSovits(), name: 'SoVITS' },
            main: { fn: () => API.startMain(), name: '主程序' },
            napcat: { fn: () => API.startNapcat(), name: 'NapCat' },
            netease: { fn: () => API.startNetease(), name: '网易云' },
            rvc: { fn: () => API.startRvc(), name: 'RVC' },
            desktopet: { fn: () => API.startDesktopet(), name: '桌宠' }
        };
        const item = map[id];
        if (!item) return;
        try {
            await item.fn();
            this.showToast(`${item.name} 已启动！`);
        } catch (e) {
            this.showToast(`${item.name} 启动失败: ${e.message}`, true);
        }
    },

    // ============ 闭麦切换 ============,
    async toggleMic() {
        try {
            const r = await API.toggleMic();
            if (r && r.status === 'error') {
                this.showToast(r.message || '闭麦操作失败', true);
                return;
            }
            const enabled = !!(r && r.enabled);
            this.showToast(enabled ? '麦克风已开启' : '已闭麦（麦克风关闭）');
        } catch (e) {
            this.showToast('闭麦操作失败: ' + e.message, true);
        }
    },

    // ============ 配置节点 ============,
    async onPlanetClick(id) {
        console.log('App.onPlanetClick received:', id);

        // 特殊面板
        if (id === 'character') { await this.openCharacterPanel(); return; }
        if (id === 'sensevoice') { await this.openSensevoicePanel(); return; }
        if (id === 'sensevoice_config') { await this.openSensevoicePanel(); return; }
        if (id === 'sensevoice_mic') { await this.openSilencePanel(); return; }
        if (id === 'sensevoice_audio') { await this.openAudioPanel(); return; }
        if (id === 'tts') { await this.openTtsPanel(); return; }
        if (id === 'toolbox') { this.openToolbox(); return; }
        if (id === 'calendar') { await this.openCalendarPanel(); return; }

        // LLM 子球
        if (id === 'llm_model') { await this.openLlmModelPanel(); return; }
        if (id === 'llm_prompt') { await this.openLlmPromptPanel(); return; }
        if (id === 'llm_algorithm') { await this.openLlmAlgorithmPanel(); return; }

        // TTS 子球
        if (id === 'tts_model') { await this.openTtsModelPanel(); return; }
        if (id === 'tts_params') { await this.openTtsParamsPanel(); return; }
        if (id === 'tts_config') { await this.openTtsConfigPanel(); return; }
        if (id === 'tts_pause') { await this.openTtsPausePanel(); return; }

        // 主动回复子球（配置/浏览）
        if (id === 'active_config') { await this.openActiveConfigPanel(); return; }
        if (id === 'active_browse') { await this.openActiveBrowsePanel(); return; }

        // 歌曲子球（模型/歌曲/翻唱/感想）
        if (id === 'meowsinger_model') { this._openConfigPanel('歌曲模型设置', () => Config.meowsingerModel()); return; }
        if (id === 'meowsinger_song') { this._openConfigPanel('点歌设置', () => Config.meowsingerSong()); return; }
        if (id === 'meowsinger_cover') { await this.openMeowsingerCoverPanel(); return; }
        if (id === 'meowsinger_sentiment') { this._openConfigPanel('感想设置', () => Config.meowsingerSentiment()); return; }

        // VTS 子球（配置/表情/桌宠/参数）
        if (id === 'vts_config') { this._openConfigPanel('VTS 配置', () => Config.vts_config()); return; }
        if (id === 'vts_emotion') { this._openConfigPanel('VTS 表情绑定', () => Config.vts_emotion()); return; }
        if (id === 'desktopet') { this._openConfigPanel('桌宠配置', () => Config.desktopet_config()); return; }
        if (id === 'vts_params') { this._openConfigPanel('VTS 模型参数', () => Config.vts_params()); return; }

        // CatBrain 子球（原则词需异步加载独立 json，单独处理）
        if (id === 'rulesbreak') { await this.openRulesBreakPanel(); return; }

        const catbrainSubMap = {
            'ltmem': { title: '长期记忆', fn: () => Config.catbrain_ltmem() },
            'abstract': { title: '记忆摘要', fn: () => Config.catbrain_abstract() },
            'values': { title: '价值观', fn: () => Config.catbrain_values() },
            'usermem': { title: '用户记忆', fn: () => Config.catbrain_usermem() }
        };
        if (catbrainSubMap[id]) {
            this._openConfigPanel(catbrainSubMap[id].title, catbrainSubMap[id].fn);
            return;
        }

        // 数据库子球
        if (id === 'db_source') { this.openDatabaseSourcePanel(); return; }
        if (id === 'db_prefill') { this.openDbPrefillPanel(); return; }
        const databaseSubMap = {
            'db_search': { title: '搜索学习', fn: () => Config.db_search() },
            'db_store': { title: '知识存储与检索', fn: () => Config.db_store() }
        };
        if (databaseSubMap[id]) {
            this._openConfigPanel(databaseSubMap[id].title, databaseSubMap[id].fn);
            return;
        }

        const panelMap = {
            'basic': { title: '基本设置', fn: () => Config.basic(), special: true },
            'subtitle': { title: '字幕设置', fn: () => Config.subtitle() },
            'active': { title: '主动回复设置', fn: () => Config.llm_active() }
        };

        const panel = panelMap[id];
        if (!panel) {
            console.warn('No panel found for id:', id);
            return;
        }
        if (panel.special) { this.openBasicPanel(); return; }
        this._openConfigPanel(panel.title, panel.fn);
    },

    // ============ 主动回复子球：配置 ============,
    _esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
    _escAttr(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
    onToolboxPlanetClick(id) {
        const map = {
            'center': { title: 'Toolbox 父级模型', fn: () => Config.toolbox() },
            'minecraft': { title: 'Minecraft 设置', fn: () => Config.minecraft() },
            'meowvision': { title: 'MeowVision 视觉设置', fn: () => Config.meowvision() },
            'napcat': { title: 'NapCat 设置', fn: () => Config.napcat() },
            'napcat_private': { title: 'NapCat 私聊回复', fn: () => Config.napcat_private() },
            'napcat_group': { title: 'NapCat 群聊回复', fn: () => Config.napcat_group() },
            'napcat_send': { title: 'NapCat 主动发送', fn: () => Config.napcat_send() },
            'napcat_account': { title: 'NapCat 角色名', fn: () => Config.napcat_account() },
            'weather': { title: '天气查询设置', fn: () => Config.weather() },
            'news': { title: '新闻查询设置', fn: () => Config.news() },
            'danmaku': { title: '弹幕设置', fn: () => Config.danmaku() },
            'add_backlog': { title: '提醒设置', fn: () => Config.addBacklog() },
            'meowsongs': { title: '即兴哼唱设置', fn: () => Config.meowsongs() },
            'turtle_soup': { title: '海龟汤设置', fn: () => Config.turtle_soup() }
        };
        const panel = map[id];
        if (!panel) {
            console.warn('No toolbox panel for id:', id);
            return;
        }
        this._openConfigPanel(panel.title, panel.fn);
    },

    // 普通配置面板（保存到 config.yml）,
    _openConfigPanel(title, fn) {
        try {
            const html = fn();
            Modal.show(title, html, async () => {
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                try {
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
        setTimeout(() => {
            this.bindTabs();
            this.bindSplitFlagEditor();
            this.bindWordTagEditor();
            this.bindTriggerMode();
            this.bindDictEditors();
            this.bindSessdataVerify();
            this.bindBiliLogin();
            this.bindVtsParamsQuery();
        }, 10);
    },

    // ============ 基本设置面板（含奖励收纳篮） ============,
    async openBasicPanel() {
        try {
            const html = Config.basic();
            Modal.show('基本设置', html, async () => {
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                try {
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
            this.loadRewards();
        } catch (e) {
            console.error('Error rendering basic panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    _ensureRewardStyle() {
        if (document.getElementById('rewardManageStyle')) return;
        const st = document.createElement('style');
        st.id = 'rewardManageStyle';
        st.textContent = '#rewardManage input{' +
            'width:auto;padding:6px 10px;border:1px solid var(--pink-soft);border-radius:12px;' +
            'font-size:14px;font-family:inherit;background:var(--white);color:var(--text-main);' +
            'transition:all .3s ease;}' +
            '#rewardManage input:focus{outline:none;border-color:var(--pink-main);' +
            'box-shadow:0 0 0 3px var(--shadow);}';
        document.head.appendChild(st);
    },

    async loadRewards() {
        const box = document.getElementById('rewardManage');
        if (!box) return;
        this._ensureRewardStyle();
        box.innerHTML = '<div class="help-text">加载中...</div>';
        try {
            const res = await fetch('/api/rewards');
            const data = await res.json();
            const kinds = (data && data.kinds) || [];
            if (!kinds.length) {
                box.innerHTML = '<div class="help-text">暂无奖励项，点击下方新建</div>';
            } else {
                box.innerHTML = kinds.map(k => this.rewardRowHtml(k)).join('');
            }
            box.insertAdjacentHTML('beforeend',
                '<div style="margin-top:12px;">' +
                '<button type="button" class="btn btn-primary" id="addRewardBtn">新建奖励种类</button></div>');
            this.bindRewardManage(box);
        } catch (e) {
            box.innerHTML = '<div class="help-text">读取奖励失败: ' + this._esc(e.message) + '</div>';
        }
    },

    rewardRowHtml(k) {
        const unit = k.unit || '';
        const rows = (k.history || []).slice().reverse().map(h => {
            const who = h.user ? ' · ' + this._esc(h.user) : '';
            const gift = h.gift ? ' · ' + this._esc(h.gift) : '';
            return '<div class="help-text" style="margin:2px 0;">' + this._t(h.type || '') +
                ' ' + (h.delta >= 0 ? '+' : '') + this._esc(h.delta) + this._esc(unit) + who + gift + '</div>';
        }).join('');
        return '<div class="reward-row" data-name="' + this._escAttr(k.name) + '"' +
            ' style="border:1px solid rgba(255,255,255,.14);border-radius:14px;padding:12px 14px;' +
            'margin-bottom:12px;background:rgba(255,255,255,.05);">' +
            '<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;">' +
            '<b>' + this._esc(k.name) + '</b>' +
            '<span style="font-size:24px;font-weight:800;color:var(--pink-main,#ff7eb6);">' +
            this._esc(k.balance) + this._esc(unit) + '</span>' +
            '<span class="help-text">累计获取 ' + this._esc(k.total_acquired) + this._esc(unit) + '</span></div>' +
            '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px;align-items:center;">' +
            '<label>每</label><input type="number" data-f="battery_per_unit" step="0.5" min="0.1" value="' +
            this._esc(k.battery_per_unit) + '" style="width:74px;">' +
            '<label>电池 = 1</label><input type="text" data-f="unit" value="' + this._esc(unit) + '" style="width:52px;">' +
            '<label>启动每次消耗</label><input type="number" data-f="startup_cost" step="0.1" min="0" value="' +
            this._esc(k.startup_cost) + '" style="width:72px;">' +
            '<label>' + this._esc(unit) + '</label></div>' +
            '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">' +
            '<button type="button" class="btn btn-secondary" data-act="set">保存配置</button>' +
            '<button type="button" class="btn btn-primary" data-act="adjust" data-delta="1">+1</button>' +
            '<button type="button" class="btn btn-primary" data-act="adjust" data-delta="0.1">+0.1</button>' +
            '<button type="button" class="btn btn-secondary" data-act="adjust" data-delta="-1">-1</button>' +
            '<button type="button" class="btn btn-secondary" data-act="adjust" data-delta="-0.1">-0.1</button>' +
            '<button type="button" class="btn btn-secondary" data-act="remove" style="color:#ff6b6b;">删除</button></div>' +
            '<div style="margin-top:6px;">' + rows + '</div></div>';
    },

    bindRewardManage(box) {
        const addBtn = document.getElementById('addRewardBtn');
        if (addBtn) {
            addBtn.addEventListener('click', () => {
                const name = (prompt('新奖励名称：') || '').trim();
                if (!name) return;
                const unit = (prompt('单位（如 条/个，可空）：') || '').trim();
                const per = parseFloat(prompt('1 个 = 多少电池（默认10）：') || '10');
                const cost = parseFloat(prompt('每次启动消耗（默认1）：') || '1');
                this.rewardPost({
                    action: 'add_kind', name: name, unit: unit,
                    battery_per_unit: isNaN(per) ? 10 : per,
                    startup_cost: isNaN(cost) ? 1 : cost
                });
            });
        }
        box.onclick = (e) => {
            const btn = e.target && e.target.closest ? e.target.closest('button[data-act]') : null;
            if (!btn) return;
            const row = btn.closest('.reward-row');
            if (!row) return;
            const name = row.dataset.name;
            const act = btn.dataset.act;
            if (act === 'remove') {
                if (confirm('删除奖励「' + name + '」及其全部数据？')) {
                    this.rewardPost({ action: 'remove', name: name });
                }
                return;
            }
            if (act === 'adjust') {
                this.rewardPost({ action: 'adjust', name: name, delta: parseFloat(btn.dataset.delta) });
                return;
            }
            if (act === 'set') {
                const getV = (f) => { const el = row.querySelector('[data-f="' + f + '"]'); return el ? el.value : ''; };
                const per = parseFloat(getV('battery_per_unit'));
                const cost = parseFloat(getV('startup_cost'));
                this.rewardPost({
                    action: 'set', name: name,
                    unit: getV('unit') || '',
                    battery_per_unit: isNaN(per) ? 10 : per,
                    startup_cost: isNaN(cost) ? 0 : cost
                });
            }
        };
    },

    async rewardPost(payload) {
        try {
            const res = await fetch('/api/rewards', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok || data.status !== 'ok') {
                throw new Error(data.message || ('操作失败: ' + res.status));
            }
            this.loadRewards();
            this.showToast('奖励已更新');
        } catch (e) {
            this.showToast('奖励操作失败: ' + e.message, true);
        }
    },

    showToast(msg, isError) {
        const toast = document.getElementById('toast');
        const txt = (typeof I18n !== 'undefined' && I18n.text) ? I18n.text(msg) : msg;
        toast.textContent = txt;
        toast.style.background = isError ? 'linear-gradient(145deg, #ff6b6b, #ee5a5a)' : 'linear-gradient(145deg, var(--pink-main), var(--pink-deep))';
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
    },
};


document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, initializing App...');
    window.App = App;
    App.init();
});

