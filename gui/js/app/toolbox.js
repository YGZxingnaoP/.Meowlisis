/**
 * 应用控制器 - toolbox 模块
 * 由 app.js 拆分而来，统一挂载到全局 App 对象
 */

Object.assign(App, {
    openToolbox() {
        const overlay = document.getElementById('toolboxOverlay');
        if (overlay) overlay.classList.add('show');
    },
    closeToolbox() {
        const overlay = document.getElementById('toolboxOverlay');
        if (overlay) overlay.classList.remove('show');
    },

    // ============ 待办提醒面板 ============,
    async openCalendarPanel() {
        try {
            const users = await API.getBacklogUsers();
            this.calendarData = {};
            for (const u of users) {
                this.calendarData[u] = await API.getBacklog(u);
            }
        } catch (e) {
            this.calendarData = {};
        }
        Modal.show('待办提醒', Config.calendarPanel(), async () => {
            await this.saveCalendar();
        });
        this.renderCalendarUsers();
        this.bindCalendarEvents();
    },
    renderCalendarUsers() {
        const list = document.getElementById('backlogUserList');
        if (!list) return;
        const users = Object.keys(this.calendarData);
        if (!users.length) {
            list.innerHTML = '<div class="help-text">暂无用户，输入用户名新建</div>';
            return;
        }
        list.innerHTML = users.map(u => {
            const todos = (this.calendarData[u] && this.calendarData[u].to_do_list) || [];
            const todoHtml = todos.map((t, i) => this.renderCalendarTodo(u, i, t)).join('');
            return `<div class="char-card" data-backlog-user="${this._escAttr(u)}">
                <div class="char-card-title backlog-user-toggle" style="cursor:pointer;">
                    <span class="backlog-toggle-arrow">▾</span> ${this._esc(u)}
                </div>
                <div class="backlog-user-body">
                    <div class="backlog-todo-list">${todoHtml || '<div class="help-text">暂无待办</div>'}</div>
                    <button type="button" class="btn btn-secondary backlog-add-todo" data-user="${this._escAttr(u)}">${this._t('添加待办')}</button>
                </div>
            </div>`;
        }).join('');
    },
    renderCalendarTodo(user, index, todo) {
        todo = todo || {};
        const type = todo.type === 'steady' ? 'steady' : 'instant';
        const qq = !!todo.qq;
        const timeParts = String(todo.time || '').split(':');
        const timeHour = timeParts[0] || '';
        const timeMinute = timeParts[1] || '';
        return `<div class="backlog-todo" data-user="${this._escAttr(user)}" data-todo-index="${index}">
            <div class="form-group"><label>${this._t('提醒日期')}</label>
                <input type="text" data-todo-field="day" value="${this._esc(todo.day || '')}" placeholder="${this._t('MM-DD，留空/none 每天')}"></div>
            <div class="form-group"><label>${this._t('提醒时间')}</label>
                <div class="time-row">
                    <input type="number" data-todo-field="time_hour" value="${this._esc(timeHour)}" min="0" max="23" placeholder="${this._t('时')}">
                    <span class="time-colon">:</span>
                    <input type="number" data-todo-field="time_minute" value="${this._esc(timeMinute)}" min="0" max="59" placeholder="${this._t('分')}">
                </div></div>
            <div class="form-group"><label>${this._t('类型')}</label>
                <button type="button" class="btn btn-secondary cycle-btn" data-todo-field="type" data-todo-values="instant,steady" data-todo-value="${type}">${type}</button></div>
            <div class="form-group"><label>${this._t('QQ提醒')}</label>
                <button type="button" class="btn btn-secondary cycle-btn" data-todo-field="qq" data-todo-values="false,true" data-todo-value="${qq ? 'true' : 'false'}">${qq ? '开' : '关'}</button></div>
            <div class="form-group"><label>${this._t('重复间隔(秒)')}</label>
                <input type="number" data-todo-field="repeat_interval" value="${todo.repeat_interval != null ? todo.repeat_interval : 300}"></div>
            <div class="form-group"><label>${this._t('总次数')}</label>
                <input type="number" data-todo-field="loop" value="${todo.loop != null ? todo.loop : 2}"></div>
            <div class="form-group"><label>${this._t('提醒内容')}</label>
                <input type="text" data-todo-field="content" value="${this._esc(todo.content || '')}" placeholder="${this._t('提醒内容')}"></div>
            <button type="button" class="btn btn-secondary backlog-remove-todo">${this._t('删除待办')}</button>
        </div>`;
    },
    bindCalendarEvents() {
        const list = document.getElementById('backlogUserList');
        if (!list) return;

        const newInput = document.getElementById('newBacklogUserInput');
        const addUserBtn = document.getElementById('addBacklogUserBtn');
        const addUser = () => {
            const name = (newInput && newInput.value || '').trim();
            if (!name) { this.showToast('请输入用户名', true); return; }
            if (this.calendarData[name]) { this.showToast('用户已存在', true); return; }
            this.calendarData[name] = { username: name, to_do_list: [] };
            if (newInput) newInput.value = '';
            this.renderCalendarUsers();
        };
        if (addUserBtn) addUserBtn.addEventListener('click', addUser);
        if (newInput) newInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') addUser(); });

        list.addEventListener('click', (e) => {
            const toggle = e.target.closest('.backlog-user-toggle');
            if (toggle) {
                const card = toggle.closest('[data-backlog-user]');
                const body = card.querySelector('.backlog-user-body');
                const arrow = toggle.querySelector('.backlog-toggle-arrow');
                if (body) {
                    const collapsed = body.style.display === 'none';
                    body.style.display = collapsed ? '' : 'none';
                    if (arrow) arrow.textContent = collapsed ? '▾' : '▸';
                }
                return;
            }

            const addTodo = e.target.closest('.backlog-add-todo');
            if (addTodo) {
                const user = addTodo.dataset.user;
                const data = this.calendarData[user] || { username: user, to_do_list: [] };
                data.to_do_list = data.to_do_list || [];
                data.to_do_list.push({ day: '', time: '', type: 'instant', repeat_interval: 300, loop: 2, content: '', qq: false });
                this.calendarData[user] = data;
                this.renderCalendarUsers();
                return;
            }

            const removeTodo = e.target.closest('.backlog-remove-todo');
            if (removeTodo) {
                const todo = removeTodo.closest('.backlog-todo');
                const user = todo.dataset.user;
                const index = parseInt(todo.dataset.todoIndex, 10);
                const data = this.calendarData[user];
                if (data && data.to_do_list) {
                    data.to_do_list.splice(index, 1);
                    this.renderCalendarUsers();
                }
                return;
            }

            const cycle = e.target.closest('.cycle-btn');
            if (cycle) {
                const values = (cycle.dataset.todoValues || '').split(',');
                const cur = cycle.dataset.todoValue;
                let idx = values.indexOf(cur);
                idx = (idx + 1) % values.length;
                const next = values[idx];
                cycle.dataset.todoValue = next;
                cycle.textContent = cycle.dataset.todoField === 'qq' ? (next === 'true' ? '开' : '关') : next;
                // 同步到内存数据
                const todo = cycle.closest('.backlog-todo');
                const user = todo.dataset.user;
                const index = parseInt(todo.dataset.todoIndex, 10);
                const data = this.calendarData[user];
                if (data && data.to_do_list && data.to_do_list[index]) {
                    if (cycle.dataset.todoField === 'qq') {
                        data.to_do_list[index].qq = (next === 'true');
                    } else {
                        data.to_do_list[index][cycle.dataset.todoField] = next;
                    }
                }
                return;
            }
        });

        list.addEventListener('input', (e) => {
            const input = e.target.closest('input[data-todo-field]');
            if (!input) return;
            const todo = input.closest('.backlog-todo');
            const user = todo.dataset.user;
            const index = parseInt(todo.dataset.todoIndex, 10);
            const data = this.calendarData[user];
            const item = data && data.to_do_list && data.to_do_list[index];
            if (!item) return;
            const field = input.dataset.todoField;
            if (field === 'time_hour' || field === 'time_minute') {
                const parts = String(item.time || '').split(':');
                const hour = field === 'time_hour' ? String(input.value || '') : (parts[0] || '');
                const minute = field === 'time_minute'
                    ? (input.value === '' ? '' : String(input.value).padStart(2, '0'))
                    : (parts[1] || '');
                item.time = `${hour}:${minute}`;
                return;
            }
            let v = input.value;
            if (input.type === 'number') v = input.value === '' ? 0 : parseFloat(input.value);
            item[field] = v;
        });
    },
    async saveCalendar() {
        try {
            for (const u of Object.keys(this.calendarData)) {
                await API.saveBacklog(u, this.calendarData[u]);
            }
            this.showToast('待办已保存');
        } catch (e) {
            this.showToast('保存失败: ' + e.message, true);
        }
    },
    async openDatabaseSourcePanel() {
        const html = Config.db_source();
        Modal.show('网页数据来源', html, async () => {
            try {
                this.config.database = this.config.database || {};
                this.config.database.search = this.config.database.search || {};
                this.config.database.search.sites = Config.collectSources();
                await API.saveConfig(this.config);
                this.showToast('来源配置已保存');
            } catch (e) {
                this.showToast('保存失败: ' + e.message, true);
            }
        });
        setTimeout(() => this.bindSourceSiteEvents(), 10);
    },

    // ============ 知识库一键预填 ============,
    async openDbPrefillPanel() {
        let data = {};
        try {
            data = await API.getDbPrefillConfig() || {};
        } catch (e) {
            console.warn('加载预填配置失败:', e);
        }
        const html = Config.db_prefill(data);
        Modal.show('知识库预填充', html, null);
        setTimeout(() => this.bindDbPrefillEvents(), 10);
    },
    bindDbPrefillEvents() {
        const startBtn = document.getElementById('dbPrefillStartBtn');
        const statusEl = document.getElementById('dbPrefillStatus');
        if (!startBtn || !statusEl) return;

        // 绑定每个站点的词条 tag 编辑器
        document.querySelectorAll('[data-keyword-editor]').forEach(editor => {
            this._bindKeywordEditor(editor);
        });

        startBtn.addEventListener('click', async () => {
            const sites = [];
            const keywords = {};
            document.querySelectorAll('.db-prefill-site:checked').forEach(cb => {
                sites.push(cb.dataset.site);
            });
            document.querySelectorAll('[data-keyword-editor]').forEach(editor => {
                const site = editor.dataset.keywordEditor;
                if (!sites.includes(site)) return;
                const words = [];
                editor.querySelectorAll('.split-tag').forEach(t => {
                    const k = t.dataset.keyword;
                    if (k) words.push(k);
                });
                if (words.length) keywords[site] = words;
            });

            if (!sites.length || !Object.keys(keywords).length) {
                this.showToast('请至少选择一个站点并添加词条', true);
                return;
            }

            const reset = document.getElementById('dbPrefillReset').checked;

            // 1. 保存词条配置到 gui/tools/prefill_seed.json（独立于 config.yml）
            try {
                const cfg = await API.getDbPrefillConfig() || {};
                cfg.sites = cfg.sites || {};
                sites.forEach(site => {
                    const label = (cfg.sites[site] && cfg.sites[site].label) || site;
                    cfg.sites[site] = { label, keywords: keywords[site] || [] };
                });
                await API.saveDbPrefillConfig(cfg);
            } catch (e) {
                this.showToast('保存预填配置失败: ' + e.message, true);
            }

            startBtn.disabled = true;
            statusEl.textContent = '预填充中，请稍候...';
            try {
                const r = await API.startDbPrefill({ sites, keywords, reset });
                if (!r.ok) {
                    statusEl.textContent = r.message || '启动失败';
                    startBtn.disabled = false;
                    return;
                }
                this.pollDbPrefillStatus(startBtn, statusEl);
            } catch (e) {
                statusEl.textContent = '启动失败: ' + e.message;
                startBtn.disabled = false;
            }
        });
    },
    _bindKeywordEditor(editor) {
        const tagsEl = editor.querySelector('.split-tags');
        const addInput = editor.querySelector('.split-add-input');
        if (!tagsEl || !addInput) return;

        const add = () => {
            const k = addInput.value.trim();
            if (!k) return;
            const exists = Array.from(tagsEl.querySelectorAll('.split-tag'))
                .some(t => t.dataset.keyword === k);
            if (exists) {
                addInput.value = '';
                return;
            }
            const tag = document.createElement('span');
            tag.className = 'split-tag';
            tag.dataset.keyword = k;
            tag.innerHTML = `${this._esc(k)}<button type="button" class="split-tag-remove">&times;</button>`;
            tagsEl.appendChild(tag);
            addInput.value = '';
        };
        addInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); add(); }
        });
        tagsEl.addEventListener('click', (e) => {
            const btn = e.target.closest('.split-tag-remove');
            if (btn) btn.closest('.split-tag').remove();
        });
    },
    pollDbPrefillStatus(startBtn, statusEl) {
        const timer = setInterval(async () => {
            try {
                const s = await API.getDbPrefillStatus();
                if (s.done) {
                    clearInterval(timer);
                    startBtn.disabled = false;
                    statusEl.textContent = s.error
                        ? ('预填充失败: ' + s.error)
                        : ('预填充完成，共入库 ' + s.result + ' 条');
                    return;
                }
                if (!s.running) {
                    clearInterval(timer);
                    startBtn.disabled = false;
                    statusEl.textContent = '任务已停止';
                    return;
                }
                statusEl.textContent = '预填充中，请稍候...';
            } catch (e) {
                clearInterval(timer);
                startBtn.disabled = false;
                statusEl.textContent = '查询状态失败: ' + e.message;
            }
        }, 2000);
    },
    bindSourceSiteEvents() {
        const list = document.getElementById('sourceSiteList');
        if (!list) return;

        // 添加站点
        const addBtn = document.getElementById('addSourceSiteBtn');
        if (addBtn) {
            addBtn.addEventListener('click', () => {
                const empty = list.querySelector('.help-text');
                if (empty) empty.remove();
                list.insertAdjacentHTML('beforeend', Config.sourceSiteRow('', {}));
            });
        }

        // 折叠 / 删除 / 验证（事件委托）
        list.addEventListener('click', async (e) => {
            // 折叠：点击标题栏切换 body 显隐
            const toggle = e.target.closest('.source-site-toggle');
            if (toggle) {
                const card = toggle.closest('[data-source-site]');
                const body = card.querySelector('.source-site-body');
                const arrow = toggle.querySelector('.source-toggle-arrow');
                if (body) {
                    const collapsed = body.style.display === 'none';
                    body.style.display = collapsed ? '' : 'none';
                    if (arrow) arrow.textContent = collapsed ? '▾' : '▸';
                }
                return;
            }

            const card = e.target.closest('[data-source-site]');
            if (!card) return;
            if (e.target.closest('.source-remove-btn')) {
                card.remove();
                if (!list.querySelector('[data-source-site]')) {
                    list.innerHTML = '<div class="help-text">暂无站点，点击下方按钮添加</div>';
                }
                return;
            }
            if (e.target.closest('.source-verify-btn')) {
                const key = (card.querySelector('[data-source-field="key"]') || {}).value || '';
                const query = '测试';
                const resultEl = card.querySelector('.source-verify-result');
                if (!key) {
                    resultEl.textContent = '请先填写站点标识';
                    return;
                }
                resultEl.textContent = '验证中...';
                try {
                    const r = await API.verifySite(key, query);
                    resultEl.textContent = (r.ok ? '✓ 通过：' : '✗ 失败：') + r.message;
                    if (r.sample && r.sample.length) {
                        resultEl.textContent += '（' + r.sample.map(s => s.title).slice(0, 3).join('、') + '...）';
                    }
                } catch (err) {
                    resultEl.textContent = '验证失败: ' + err.message;
                }
            }
        });
    },

    // ============ 键值对编辑器事件绑定 ============,
    bindVtsParamsQuery() {
        const btn = document.querySelector('[data-vts-query]');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            const resultEl = document.querySelector('[data-vts-params-result]');
            btn.disabled = true;
            if (resultEl) resultEl.innerHTML = '<div class="help-text">' + this._t('查询中，请稍候…') + '</div>';
            try {
                const r = await API.getVtsParameters();
                if (r && r.ok) {
                    const data = r.data || {};
                    if (resultEl) resultEl.innerHTML = Config._vtsParamsTable(data, data);
                } else {
                    const msg = (r && r.data) ? r.data : this._t('查询失败');
                    if (resultEl) resultEl.innerHTML = `<div class="help-text">${this._esc(msg)}</div>`;
                }
            } catch (e) {
                if (resultEl) resultEl.innerHTML = `<div class="help-text">${this._t('查询失败：')}${this._esc(e.message)}</div>`;
            } finally {
                btn.disabled = false;
            }
        });
    },

    // ============ 歌曲翻唱面板（RVC 模型/索引下拉） ============,
});
