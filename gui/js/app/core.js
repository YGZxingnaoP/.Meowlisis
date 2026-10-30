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
        this.bindFolds();
        await this.loadPlugins();
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
            API.setSnapshot(this.config);   // 增量保存的基准
            window._config = this.config;
            Config.setConfig(this.config);
        } catch (e) {
            this.showToast('加载配置失败: {msg}', true, { msg: e.message });
        }
    },

    // ============ 服务启动球 ============,
    async onLaunchClick(id) {
        if (id === 'catpaws') { await this.startCatpaws(); return; }
        const map = {
            phone: { fn: () => API.startPhone(), name: '接口' },
            sensevoice: { fn: () => API.startSensevoice(), name: 'SenseVoice' },
            sovits: { fn: () => API.startSovits(), name: 'SoVITS' },
            main: { fn: () => API.startMain(), name: '主程序' },
            painting: { fn: () => API.startPainting(), name: '绘画引擎' },
            napcat: { fn: () => API.startNapcat(), name: 'NapCat' },
            netease: { fn: () => API.startNetease(), name: '网易云' },
            rvc: { fn: () => API.startRvc(), name: 'RVC' },
            desktopet: { fn: () => API.startDesktopet(), name: '桌宠' }
        };
        const item = map[id];
        if (!item) return;
        const name = this._t(item.name);
        try {
            const r = await item.fn();
            // 启动接口统一返回 200 + {status, message}（见 gui/tools/loghub.py）
            if (r && r.status === 'error') {
                this.showToast('{name} 启动失败: {msg}', true, { name: name, msg: r.message || '' });
                return;
            }
            this.showToast('{name} 已启动！', false, { name: name });
        } catch (e) {
            this.showToast('{name} 启动失败: {msg}', true, { name: name, msg: e.message });
        }
    },

    // ============ 手机操作（CatPaws）============,
    async startCatpaws() {
        try {
            const r = await API.startCatpaw();
            if (r && r.status === 'error') {
                this.showToast('手机操作服务启动失败: {msg}', true, { msg: r.message || '' });
                return;
            }
        } catch (e) {
            this.showToast('手机操作服务启动失败: {msg}', true, { msg: e.message });
            return;
        }
        this.showToast('手机操作服务已启动，正在打开日志中心…');
        window.open('/logs?svc=catpaw', '_blank');
    },

    async openCatpawsPanel() {
        try {
            Config.setCatpawsConfig(await API.getCatpawsConfig());
        } catch (e) {
            this.showToast('读取手机操作配置失败: {msg}', true, { msg: e.message });
            return;
        }
        this._openConfigPanel('手机操作（CatPaws）', () => Config.catpaws(), async () => {
            const patch = Config.collectCatpaws();
            if (!patch) throw new Error('没有可保存的内容');
            const r = await API.saveCatpawsConfig(patch);
            if (r && r.status === 'error') throw new Error(r.message || '保存失败');
            this.showToast('手机操作配置已保存（立即生效）');
        });
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
        const ok = await ConfigPanels.open(id);
        if (!ok) console.warn('No panel found for id:', id);
    },

    // ============ 主动回复子球：配置 ============,
    _esc(s) { return U.esc(s); },
    _escAttr(s) { return U.escAttr(s); },
    async onToolboxPlanetClick(id) {
        const pluginRef = this.pluginMap && this.pluginMap[id];
        if (pluginRef) {
            this.openPluginPanel(pluginRef.id);
            return;
        }
        const ok = await ConfigPanels.open(id);
        if (!ok) console.warn('No toolbox panel for id:', id);
    },

    // ============ 插件卡片：一张「插件」父卡，子卡 = 各插件 ============,
    PLUGIN_KIDS_MAX: 5,
    async loadPlugins() {
        try {
            this.plugins = await API.getPlugins();
        } catch (e) {
            this.plugins = [];
        }
        this.pluginMap = {};
        if (typeof Cards !== 'undefined' && Cards.META) {
            Cards.META['plugins'] = { n: '插件', g: 'core', e: '🧩', img: '/api/plugins/card' };
            Cards.META['plugins_more'] = { n: '更多', g: 'core', e: '⋯', img: Cards.DIR + 'plugins_more.png' };
        }
        const kids = [];
        (this.plugins || []).forEach(p => {
            if (typeof Cards !== 'undefined' && Cards.META) {
                Cards.META[p.id] = {
                    n: p.title || p.id, g: p.group || 'core', e: p.emoji || '🧩',
                    img: '/api/plugins/' + p.id + '/card'
                };
            }
            if (Config.pluginSchemas) Config.pluginSchemas[p.id] = p;
            this.pluginMap[p.id] = { id: p.id };
            kids.push({ id: p.id, label: p.title || p.id, card: p.id,
                        tooltip: (p.title || p.id) + ' 插件配置与开关' });
        });
        // 轨道上最多展开 5 张插件卡；更多插件收进「更多」卡的方阵浮层。
        const shown = kids.slice(0, this.PLUGIN_KIDS_MAX);
        if (kids.length > this.PLUGIN_KIDS_MAX) {
            shown.push({
                id: 'plugins_more', label: '更多', card: 'plugins_more',
                tooltip: '查看全部插件', more: true
            });
        }
        if (typeof Orbit !== 'undefined' && Orbit.toolboxPlanets && shown.length) {
            Orbit.toolboxPlanets = Orbit.toolboxPlanets.filter(p => p.id !== 'plugins');
            Orbit.toolboxPlanets.push({
                id: 'plugins', label: '插件', card: 'plugins',
                tooltip: '插件配置与开关', kids: shown
            });
        }
        console.log('[Plugins] 插件子卡: ' + shown.map(k => k.id).join(', ') +
                    '（共 ' + kids.length + ' 个）');
    },

    openPluginMore() {
        const list = this.plugins || [];
        if (!list.length) return;
        let ov = document.getElementById('pluginMoreOverlay');
        if (!ov) {
            ov = document.createElement('div');
            ov.id = 'pluginMoreOverlay';
            ov.className = 'plugin-more-overlay';
            ov.innerHTML =
                '<div class="plugin-more-panel">' +
                    '<div class="plugin-more-head">' +
                        '<h3>' + this._t('全部插件') + '</h3>' +
                        '<button type="button" class="plugin-more-close" aria-label="' + this._t('关闭') + '">&times;</button>' +
                    '</div>' +
                    '<div class="plugin-more-grid" id="pluginMoreGrid"></div>' +
                '</div>';
            document.body.appendChild(ov);
            ov.addEventListener('click', (e) => {
                if (e.target === ov || (e.target.closest && e.target.closest('.plugin-more-close'))) {
                    this.closePluginMore();
                }
            });
            if (!this._pluginMoreEsc) {
                this._pluginMoreEsc = true;
                document.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape') this.closePluginMore();
                });
            }
        }
        const grid = ov.querySelector('#pluginMoreGrid');
        grid.innerHTML = list.map(p => {
            const th = Cards.theme(p.id);
            return '<button type="button" class="plugin-more-card" data-plugin="' + U.escAttr(p.id) + '"' +
                ' style="--a:' + th.a + ';--b:' + th.b + '">' +
                '<span class="pm-art"><span class="pm-emoji">' + U.esc(p.emoji || '🧩') + '</span>' +
                '<img src="' + U.escAttr(Cards.img(p.id)) + '" alt="" loading="lazy" onerror="this.remove()"></span>' +
                '<span class="pm-name">' + U.esc(p.title || p.id) + '</span></button>';
        }).join('');
        grid.querySelectorAll('.plugin-more-card').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = btn.dataset.plugin;
                this.closePluginMore();
                this.openPluginPanel(id);
            });
        });
        ov.classList.add('show');
        ov.style.zIndex = '';
        document.body.classList.add('plugin-more-open');
    },

    closePluginMore() {
        const ov = document.getElementById('pluginMoreOverlay');
        if (ov) {
            ov.classList.remove('show');
            ov.style.zIndex = '4000';   // 淡出时让配置面板（5000）盖在它上面
        }
        document.body.classList.remove('plugin-more-open');
    },

    async openPluginPanel(id) {
        try {
            await Config.preloadPluginConfig(id);
        } catch (e) {
            this.showToast('插件配置读取失败: {msg}', true, { msg: e.message });
            return;
        }
        const schema = (Config.pluginSchemas || {})[id] || {};
        this._openConfigPanel(schema.title || id, () => Config.pluginPanel(id), async () => {
            const updates = Config.collectValues();
            const cfg = Config.applyPluginUpdates(id, updates);
            await API.savePluginConfig(id, cfg);
            this.showToast('插件配置已保存（重启主程序生效）');
        });
    },

    // 普通配置面板（保存到 config.yml）,
    _openConfigPanel(title, fn, onSave) {
        try {
            const html = fn();
            Modal.show(title, html, async () => {
                if (typeof onSave === 'function') {
                    try {
                        await onSave();
                    } catch (e) {
                        this.showToast('保存失败: {msg}', true, { msg: e.message });
                    }
                    return;
                }
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                try {
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: {msg}', true, { msg: e.message });
                }
            });
        } catch (e) {
            console.error('Error rendering panel:', e);
            this.showToast('面板渲染失败: {msg}', true, { msg: e.message });
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

    // ============ 基本设置面板：礼物 / API / 端口 三个页签 ============,
    // 备注：原来的 Config.basic()（js/config/basic.js）是"一长条"，这里重建为页签式。
    // 所有字段仍是普通的 data-path 输入，保存走同一套 collectValues。
    _basicPanelHtml() {
        const C = Config;
        const tabs =
            '<div class="modal-tabs">' +
                '<button type="button" class="modal-tab active" data-tab="basic_gift">' + this._t('礼物') + '</button>' +
                '<button type="button" class="modal-tab" data-tab="basic_api">' + this._t('API') + '</button>' +
                '<button type="button" class="modal-tab" data-tab="basic_port">' + this._t('端口') + '</button>' +
            '</div>';

        const giftTab =
            '<div class="tab-content active" data-tab-content="basic_gift">' +
                C._section('奖励收纳篮（礼物入账）') +
                '<div id="rewardManage"></div>' +
                '<div class="help-text">' + this._t('礼物按 1000瓜子=1元=10电池 折算，随机入账到某个奖励项') + '</div>' +
            '</div>';

        const apiTab =
            '<div class="tab-content" data-tab-content="basic_api">' +
                (typeof C.apiPlatforms === 'function'
                    ? C.apiPlatforms()
                    : '<div class="help-text" style="color:#c62828;font-weight:600">' +
                      'DEBUG apiPlatforms 未定义：credentials.js 没有加载或版本不匹配</div>') +
            '</div>';

        const portTab =
            '<div class="tab-content" data-tab-content="basic_port">' +
                C._section('端口') +
                C._num('API 端口', 'app.port', 1800, 1, 65535, 1) +
                '<div class="help-text">' + this._t('配置管理器自身的监听端口；改动后需重启配置管理器生效') + '</div>' +
            '</div>';

        const html = C._section('基础信息') +
            C._text('AI名称', 'AiName', '喵呜') +
            tabs + giftTab + apiTab + portTab;
        return html;
    },

    async openBasicPanel() {
        try {
            const html = this._basicPanelHtml();
            Modal.show('基本设置', html, async () => {
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                try {
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: {msg}', true, { msg: e.message });
                }
            });
            this.loadRewards();
            setTimeout(() => this.bindTabs(), 10);   // 页签切换：礼物 / API / 端口
        } catch (e) {
            console.error('Error rendering basic panel:', e);
            this.showToast('面板渲染失败: {msg}', true, { msg: e.message });
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
                box.innerHTML = '<div class="help-text">' + this._t('暂无奖励项，点击下方新建') + '</div>';
            } else {
                box.innerHTML = kinds.map(k => this.rewardRowHtml(k)).join('');
            }
            box.insertAdjacentHTML('beforeend',
                '<div style="margin-top:12px;">' +
                '<button type="button" class="btn btn-primary" id="addRewardBtn">' + this._t('新建奖励种类') + '</button></div>');
            this.bindRewardManage(box);
        } catch (e) {
            box.innerHTML = '<div class="help-text">' + this._t('读取奖励失败: ') + this._esc(e.message) + '</div>';
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
            '<span class="help-text">' + this._t('累计获取 ') + this._esc(k.total_acquired) + this._esc(unit) + '</span></div>' +
            '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px;align-items:center;">' +
            '<label>' + this._t('每') + '</label><input type="number" data-f="battery_per_unit" step="0.5" min="0.1" value="' +
            this._esc(k.battery_per_unit) + '" style="width:74px;">' +
            '<label>' + this._t('电池 = 1') + '</label><input type="text" data-f="unit" value="' + this._esc(unit) + '" style="width:52px;">' +
            '<label>' + this._t('启动每次消耗') + '</label><input type="number" data-f="startup_cost" step="0.1" min="0" value="' +
            this._esc(k.startup_cost) + '" style="width:72px;">' +
            '<label>' + this._esc(unit) + '</label></div>' +
            '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">' +
            '<button type="button" class="btn btn-secondary" data-act="set">' + this._t('保存配置') + '</button>' +
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
            this.showToast('奖励操作失败: {msg}', true, { msg: e.message });
        }
    },

    showToast(msg, isError, vars) {
        const toast = document.getElementById('toast');
        if (!toast) return;
        const txt = (typeof I18n !== 'undefined' && I18n.text) ? I18n.text(msg, vars) : msg;
        toast.textContent = txt;
        toast.style.background = isError ? 'linear-gradient(145deg, #ff6b6b, #ee5a5a)' : 'linear-gradient(145deg, var(--pink-main), var(--pink-deep))';
        // 定时器要存起来并清掉：连着弹两条时，前一条的 3 秒到了会把后一条一起收走
        clearTimeout(this._toastTimer);
        toast.classList.add('show');
        this._toastTimer = setTimeout(() => toast.classList.remove('show'), 3000);
    },
};


document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, initializing App...');
    window.App = App;
    App.init();
});

