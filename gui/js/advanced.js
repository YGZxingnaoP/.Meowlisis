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
    // Config.SIMPLE 已迁移到 config/simple.js；advanced.js 不再维护卡片白名单。

    Config.filterSimple = function (root, cardId) {
        const keep = Config.SIMPLE[cardId];
        if (!keep || !root) return;
        root.querySelectorAll('[data-path]').forEach(function (el) {
            // 页签（礼物 / API / 端口）是卡片的详细部分，不参与精简：
            // 否则「基本」卡的 API 页签会被这条规则整片删掉，面板看起来是空的。
            if (el.closest('[data-tab-content]')) return;
            const p = el.dataset.path || '';
            const hit = keep.some(function (k) { return p === k || p.indexOf(k + '.') === 0; });
            if (!hit) {
                const g = el.closest('.form-group');
                if (g) g.remove();
            }
        });
        root.querySelectorAll('.form-section').forEach(function (s) {
            if (s.closest('[data-tab-content]')) return;
            const n = s.nextElementSibling;
            if (!n || (n.classList && n.classList.contains('form-section'))) s.remove();
        });
    };

    // ==================== 2. 分类表：从 ConfigPanels 自动生成 ====================
    // 侧栏不再手写面板列表；面板标题/分组/打开方式都来自 config/panels.js。
    const GROUPS = ConfigPanels.advancedGroups([
        {
            group: '基础',
            prepend: [
                { id: 'identity_users', t: '用户 ID', kind: 'render', build: function () { return Config.identityUsers(); } },
                { id: 'api_platforms', t: 'API 平台', kind: 'render', build: function () { return Config.apiPlatforms(); } }
            ]
        },
        {
            group: '工具箱',
            append: [
                { id: 'plugins', t: '插件', kind: 'plugins' }
            ]
        },
        {
            group: '全量',
            append: [
                { id: 'raw_config', t: '原始配置（全部键）', kind: 'raw' }
            ]
        }
    ]);

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
            if (real && real !== this.bodyEl) {
                if (real.id !== 'modalBody_stash') real.id = 'modalBody_stash';
                // 顺手把上一个面板的 DOM 清掉：留着就是一堆"隐藏但仍在文档里"的同 id/同名节点，
                // 面板绑定里的 document.querySelector / getElementById 会命中这些旧节点 →
                // 高级设置里"验证 / 刷新 / 查询"按钮点了没反应。清空后文档里只剩活跃那一份。
                real.innerHTML = '';
            }
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
                    if (App.showToast) App.showToast(T('配置已保存（已热重载）'));
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
                if (App.showToast) App.showToast(T('配置已保存（已热重载）'));
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
        const src = Modal.source;
        const navId = (src && src.dataset) ? (src.dataset.id || null) : null;
        const cardId = (src && src.dataset) ? (src.dataset.card || navId) : null;
        if (cardId && Config.SIMPLE[cardId]) {
            Config.filterSimple(Modal.getBody(), cardId);
            if (btn) { btn.style.display = ''; btn.dataset.target = navId || cardId; }
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
