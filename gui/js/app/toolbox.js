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

/* =====================================================================
 * Flux 绘画配置面板补丁
 * 画布尺寸为 chips 输入：输入一项后回车或输入一个标点即添加，点击 × 删除
 * 采样器 / 调度器下拉取自 ComfyUI 原生枚举
 * ===================================================================== */
const FluxSamplerOptions = [{"value": "euler", "label": "euler"}, {"value": "euler_cfg_pp", "label": "euler_cfg_pp"}, {"value": "euler_ancestral", "label": "euler_ancestral"}, {"value": "euler_ancestral_cfg_pp", "label": "euler_ancestral_cfg_pp"}, {"value": "heun", "label": "heun"}, {"value": "heunpp2", "label": "heunpp2"}, {"value": "exp_heun_2_x0", "label": "exp_heun_2_x0"}, {"value": "exp_heun_2_x0_sde", "label": "exp_heun_2_x0_sde"}, {"value": "dpm_2", "label": "dpm_2"}, {"value": "dpm_2_ancestral", "label": "dpm_2_ancestral"}, {"value": "lms", "label": "lms"}, {"value": "dpm_fast", "label": "dpm_fast"}, {"value": "dpm_adaptive", "label": "dpm_adaptive"}, {"value": "dpmpp_2s_ancestral", "label": "dpmpp_2s_ancestral"}, {"value": "dpmpp_2s_ancestral_cfg_pp", "label": "dpmpp_2s_ancestral_cfg_pp"}, {"value": "dpmpp_sde", "label": "dpmpp_sde"}, {"value": "dpmpp_sde_gpu", "label": "dpmpp_sde_gpu"}, {"value": "dpmpp_2m", "label": "dpmpp_2m"}, {"value": "dpmpp_2m_cfg_pp", "label": "dpmpp_2m_cfg_pp"}, {"value": "dpmpp_2m_sde", "label": "dpmpp_2m_sde"}, {"value": "dpmpp_2m_sde_gpu", "label": "dpmpp_2m_sde_gpu"}, {"value": "dpmpp_2m_sde_heun", "label": "dpmpp_2m_sde_heun"}, {"value": "dpmpp_2m_sde_heun_gpu", "label": "dpmpp_2m_sde_heun_gpu"}, {"value": "dpmpp_3m_sde", "label": "dpmpp_3m_sde"}, {"value": "dpmpp_3m_sde_gpu", "label": "dpmpp_3m_sde_gpu"}, {"value": "ddpm", "label": "ddpm"}, {"value": "lcm", "label": "lcm"}, {"value": "ipndm", "label": "ipndm"}, {"value": "ipndm_v", "label": "ipndm_v"}, {"value": "deis", "label": "deis"}, {"value": "res_multistep", "label": "res_multistep"}, {"value": "res_multistep_cfg_pp", "label": "res_multistep_cfg_pp"}, {"value": "res_multistep_ancestral", "label": "res_multistep_ancestral"}, {"value": "res_multistep_ancestral_cfg_pp", "label": "res_multistep_ancestral_cfg_pp"}, {"value": "gradient_estimation", "label": "gradient_estimation"}, {"value": "gradient_estimation_cfg_pp", "label": "gradient_estimation_cfg_pp"}, {"value": "er_sde", "label": "er_sde"}, {"value": "seeds_2", "label": "seeds_2"}, {"value": "seeds_3", "label": "seeds_3"}, {"value": "sa_solver", "label": "sa_solver"}, {"value": "sa_solver_pece", "label": "sa_solver_pece"}];
const FluxSchedulerOptions = [{"value": "simple", "label": "simple"}, {"value": "sgm_uniform", "label": "sgm_uniform"}, {"value": "karras", "label": "karras"}, {"value": "exponential", "label": "exponential"}, {"value": "ddim_uniform", "label": "ddim_uniform"}, {"value": "beta", "label": "beta"}, {"value": "normal", "label": "normal"}, {"value": "linear_quadratic", "label": "linear_quadratic"}, {"value": "kl_optimal", "label": "kl_optimal"}];

window.FluxChips = {
    norm(v) {
        let list = [];
        if (Array.isArray(v)) list = v.map(String);
        else if (typeof v === 'string') list = v.split(/[\s,，;；]+/);
        else return [];
        return list.map(s => {
            const m = String(s).trim().match(/^(\d+)\s*[xX*]\s*(\d+)$/);
            return m ? m[1] + 'x' + m[2] : '';
        }).filter(Boolean);
    },
    join() {
        const box = document.getElementById('flux-canvas-chips');
        if (!box) return '';
        return Array.from(box.querySelectorAll('.split-tag')).map(s => s.dataset.v).join(' ');
    },
    sync() {
        const hid = document.getElementById('flux-canvas-value');
        if (hid) hid.value = FluxChips.join();
    },
    key(e, input) {
        if (e.key === 'Enter' || e.key === ',' || e.key === '，') {
            e.preventDefault();
            FluxChips.add(input);
        }
    },
    add(input) {
        const t = (input.value || '').trim();
        const m = t.match(/^(\d+)\s*[xX*]\s*(\d+)$/);
        input.value = '';
        if (!m) return;
        const v = m[1] + 'x' + m[2];
        const box = document.getElementById('flux-canvas-chips');
        if (!box) return;
        const exists = Array.from(box.querySelectorAll('.split-tag')).some(s => s.dataset.v === v);
        if (!exists) {
            box.insertAdjacentHTML('beforeend',
                `<span class="split-tag" data-v="${v}">${v}<button type="button" class="split-tag-remove" onclick="FluxChips.remove(this)">&times;</button></span>`);
        }
        FluxChips.sync();
    },
    remove(btn) {
        const span = btn.closest('.split-tag');
        if (span) span.remove();
        FluxChips.sync();
    }
};

/* LoRA 链行编辑器：每行 = 启用开关 + 文件名 + 权重；值写 flux_painter.lora_chain（JSON 数组） */
const FluxDefaultLoras = [
    { name: 'anima-highres-aesthetic-boost.safetensors', strength: 1.0, enabled: true },
    { name: 'anima_context_detailer_base10.safetensors', strength: 0.5, enabled: true }
];
window.FluxLoraRows = {
    norm(v) {
        if (v == null || v === '') return [];
        let arr = v;
        if (typeof v === 'string') { try { arr = JSON.parse(v); } catch (e) { return []; } }
        if (!Array.isArray(arr)) return [];
        return arr.filter(x => x && String(x.name || '').trim())
            .map(x => ({ name: String(x.name).trim(), strength: Number(x.strength) || 0, enabled: x.enabled !== false }));
    },
    rowHtml(item) {
        item = item || { name: '', strength: 0.8, enabled: true };
        const name = String(item.name || '')
            .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return `<div class="kv-lora-row" style="display:flex;align-items:center;gap:6px;margin:4px 0;">
            <input type="checkbox" data-lora-enabled title="启用" style="flex:none;" ${item.enabled ? 'checked' : ''}>
            <input type="text" data-lora-name value="${name}" placeholder="lora 文件名（loras 目录内）" style="flex:1;min-width:0;">
            <input type="number" data-lora-strength value="${Number(item.strength) || 0}" min="0" max="2" step="0.05" title="权重" style="flex:none;width:90px;">
            <button type="button" class="kv-remove" title="删除该 LoRA" onclick="FluxLoraRows.remove(this)">&times;</button>
        </div>`;
    },
    collect() {
        const list = [];
        const box = document.getElementById('flux-lora-editor');
        if (!box) return list;
        box.querySelectorAll('.kv-lora-row').forEach(row => {
            const name = (row.querySelector('[data-lora-name]').value || '').trim();
            if (!name) return;
            const strength = parseFloat(row.querySelector('[data-lora-strength]').value);
            list.push({
                name,
                strength: isNaN(strength) ? 0.8 : strength,
                enabled: row.querySelector('[data-lora-enabled]').checked
            });
        });
        return list;
    },
    sync() {
        const hid = document.getElementById('flux-lora-value');
        if (hid) hid.value = JSON.stringify(FluxLoraRows.collect());
    },
    add() {
        const box = document.getElementById('flux-lora-editor');
        if (box) box.insertAdjacentHTML('beforeend', FluxLoraRows.rowHtml());
        FluxLoraRows.sync();
    },
    remove(btn) {
        const row = btn.closest('.kv-lora-row');
        if (row) row.remove();
        FluxLoraRows.sync();
    }
};

if (typeof Config !== 'undefined' && Config) Object.assign(Config, {
    fluxPainter() {
        const canvasVals = FluxChips.norm(this._val('flux_painter.canvas_sizes', ['1024x1024', '1080x1960']));
        const chipsHtml = canvasVals.map(v =>
            `<span class="split-tag" data-v="${v}">${v}<button type="button" class="split-tag-remove" onclick="FluxChips.remove(this)">&times;</button></span>`).join('');
        const opts = (arr, cur) => arr.map(o => {
            const sel = String(o.value) === String(cur) ? 'selected' : '';
            return `<option value="${o.value}" ${sel}>${o.label}</option>`;
        }).join('');
        const samplerCur = this._val('flux_painter.sampler_name', 'er_sde');
        const schedCur = this._val('flux_painter.sampler_scheduler', 'simple');
        // LoRA 链当前值：config.yml 有则用之，无则回退默认两条
        const loraCur = FluxLoraRows.norm(this._val('flux_painter.lora_chain', []));
        const loraDefaults = loraCur.length ? loraCur : FluxDefaultLoras;
        // 长文本 / 数组型字段的当前值（textarea 需预填，否则保存会清空）
        const esc = (s) => String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
        const qpCur = esc(this._val('flux_painter.quality_prefix', '') || '');
        const negCur = esc(this._val('flux_painter.negative_prompt', '') || '');
        const styleOnCur = esc(Array.isArray(this._val('flux_painter.style_on_keywords', []))
            ? this._val('flux_painter.style_on_keywords', []).join(' ')
            : String(this._val('flux_painter.style_on_keywords', '') || ''));
        const srcRaw = this._val('flux_painter.artist_sources', []);
        const srcCur = esc(Array.isArray(srcRaw)
            ? srcRaw.map(x => `${(x && x.name) || ''} | ${(x && x.url) || ''}`).join('\n') : '');
        const posHandCur = esc(this._val('flux_painter.pro.pos_hand', 'hand') || 'hand');
        const negHandCur = esc(this._val('flux_painter.pro.neg_hand', '') || '');

        let h = this._section('Flux 绘画') +
            this._check('启用绘画', 'flux_painter.enabled', true) +
            this._select('绘图引擎', 'flux_painter.comfy.mode', [
                { value: 'internal', label: '内置' },
                { value: 'external', label: '外部' }
            ], 'internal') +
            this._select('画质档位', 'flux_painter.quality_mode', [
                { value: 'fast', label: '快速（单段采样，出图快）' },
                { value: 'pro', label: '清晰（Pro：放大+分块重绘+局部细化）' }
            ], 'fast') +
            this._num('HTTP 端口', 'flux_painter.http_port', 8090, 1, 65535, 1) +
            this._num('WebSocket 端口', 'flux_painter.ws_port', 8767, 1, 65535, 1) +
            this._num('ComfyUI 端口', 'flux_painter.comfy.port', 8188, 1, 65535, 1) +
            this._check('角色查证(萌娘百科)', 'flux_painter.moegirl_lookup', true) +
            `<div class="form-group"><label>${this._t('画布尺寸')}</label>
                <div class="split-tags" id="flux-canvas-chips">${chipsHtml}</div>
                <input type="hidden" data-path="flux_painter.canvas_sizes" id="flux-canvas-value" value="${canvasVals.join(' ')}">
                <input type="text" placeholder="${this._t('输入一个尺寸后回车添加')}" onkeydown="FluxChips.key(event,this)">
            </div>` +
            `<div class="form-group"><label>${this._t('采样器')}</label>
                <select data-path="flux_painter.sampler_name">${opts(FluxSamplerOptions, samplerCur)}</select></div>` +
            `<div class="form-group"><label>${this._t('调度器')}</label>
                <select data-path="flux_painter.sampler_scheduler">${opts(FluxSchedulerOptions, schedCur)}</select></div>` +
            this._check('记录绘画记忆', 'flux_painter.memory_enabled', true) +
            this._num('记忆轮数', 'flux_painter.memory_rounds', 10, 1, 50, 1) +
            this._text('归档目录', 'flux_painter.backup_dir', 'character/paints') +
            this._num('基础采样 cfg', 'flux_painter.sampler_cfg', 5, 0, 30, 0.1) +
            this._num('基础采样步数', 'flux_painter.sampler_steps', 30, 1, 200, 1) +
            this._num('采样 shift', 'flux_painter.sampler_shift', 3, 0, 30, 0.1) +
            this._check('破甲模式(成年向边界)', 'flux_painter.adult_mode', true) +
            this._num('仅保留最近会话', 'flux_painter.keep_last_sessions', 0, 0, 9999, 1) +
            this._text('临时目录', 'flux_painter.temp_dir', '.temp/flux_paint') +
            this._text('记忆类型', 'flux_painter.memory_type', 'painting') +
            this._text('语音来源', 'flux_painter.tts_source', 'toolbox_painting') +
            this._section('画图改图（续画）') +
            this._check('启用改图判定', 'flux_painter.edit_followup.enabled', true,
                '出图后等待窗口内，对下一条 @/关键词消息判定是否改图；命中则在上一轮完整提示词基础上重绘') +
            this._num('改图等待窗口(秒)', 'flux_painter.edit_followup.window', 120, 10, 3600, 10,
                '画完后多少秒内视为可改图窗口') +
            this._num('判定 max_tokens', 'flux_painter.edit_followup.llm_max_tokens', 512, 64, 4096, 64) +
            this._num('判定温度', 'flux_painter.edit_followup.llm_temperature', 0.3, 0, 2, 0.1) +
            `<div class="form-group"><label>${this._t('质量前缀（固定件，拼在画师串之后）')}</label>
                <textarea data-path="flux_painter.quality_prefix" rows="3"
                    style="width:100%;font-family:inherit;font-size:13px;">${qpCur}</textarea></div>` +
            `<div class="form-group"><label>${this._t('负面提示词（长负库）')}</label>
                <textarea data-path="flux_painter.negative_prompt" rows="4"
                    style="width:100%;font-family:inherit;font-size:13px;">${negCur}</textarea></div>` +
            this._wordTagEditor('风格化触发词（回车添加，空=不限制）', 'flux_painter.style_on_keywords', [],
                '需求里出现这些词时，从 .ComfyNode/artist/data.js 画师库随机抽 1 个画师') +
            `<div class="form-group"><label>${this._t('画师站列表（每行：名称 | URL，可用 {id}/{name} 占位）')}</label>
                <textarea data-path="flux_painter.artist_sources" rows="3"
                    style="width:100%;font-family:inherit;font-size:13px;">${srcCur}</textarea></div>`;
        // ===== LoRA 链（行编辑器：启用 + 文件名 + 权重 → flux_painter.lora_chain JSON） =====
        {
            const loraRows = loraDefaults.map(x => FluxLoraRows.rowHtml(x)).join('');
            const loraJson = JSON.stringify(loraDefaults).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/'/g, '&#39;');
            h += this._section('LoRA 链（叠加到 UNET）') +
                `<div class="form-group"><label>${this._t('启用 / LoRA 文件名 / 权重')}</label>
                    <div class="kv-editor" id="flux-lora-editor"
                         oninput="FluxLoraRows.sync()" onchange="FluxLoraRows.sync()">${loraRows}</div>
                    <button type="button" class="btn btn-secondary" onclick="FluxLoraRows.add()">${this._t('添加 LoRA')}</button>
                    <input type="hidden" data-path="flux_painter.lora_chain" id="flux-lora-value" value='${loraJson}'>
                    <div class="help-text">${this._t('勾选=启用该 LoRA，取消勾选则不加载；权重范围 0~2（如 1.0 / 0.5）。保存后需重启绘画引擎生效。')}</div>
                </div>`;
        }
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="flux_llm">提示词模型</button>
            <button class="modal-tab" data-tab="flux_deepseek">DeepSeek</button>
            <button class="modal-tab" data-tab="flux_aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab" data-tab="flux_pro_hires">Pro·放大/分块</button>
            <button class="modal-tab" data-tab="flux_pro_det">Pro·局部细化</button>
            <button class="modal-tab" data-tab="flux_review">审查与安全</button>
            <button class="modal-tab" data-tab="flux_engine">引擎与路径</button>
        </div>`;
        h += `<div class="tab-content active" data-tab-content="flux_llm">` +
            this._section('提示词模型') +
            this._select('生效平台', 'flux_painter.llm_type', [
                { value: 'deepseek', label: 'DeepSeek' },
                { value: 'aliyun', label: '阿里云 Qwen' }
            ], 'deepseek') +
            this._check('深度思考', 'flux_painter.thinking_enabled', true) +
            this._num('max_tokens', 'flux_painter.max_tokens', 8192, 256, 32768, 256) +
            this._num('温度', 'flux_painter.temperature', 0.8, 0, 2, 0.1) +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="flux_deepseek">` +
            this._section('DeepSeek') +
            this._text('API Key', 'flux_painter.deepseek.api_key', '') +
            this._text('Base URL', 'flux_painter.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'flux_painter.deepseek.model', 'deepseek-v4-flash') +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="flux_aliyun">` +
            this._section('阿里云 Qwen') +
            this._text('API Key', 'flux_painter.aliyun.api_key', '') +
            this._text('Base URL', 'flux_painter.aliyun.base_url',
                'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'flux_painter.aliyun.model', 'qwen3.7-flash') +
            `</div>`;

        // ===== Pro·放大 / 分块（05 + 06） =====
        let hiresHtml = this._section('Pro·05 高清预处理（模型放大）') +
            this._check('启用放大', 'flux_painter.pro.hires.enabled', true) +
            this._text('放大模型', 'flux_painter.pro.hires.upscale_model', '4x-AnimeSharp.pth') +
            this._num('放大倍率', 'flux_painter.pro.hires.scale', 2, 1, 4, 0.05) +
            this._select('缩放算法', 'flux_painter.pro.hires.resize', [
                { value: 'lanczos', label: 'lanczos（锐利，推荐）' },
                { value: 'bicubic', label: 'bicubic' },
                { value: 'bilinear', label: 'bilinear' },
                { value: 'area', label: 'area' },
                { value: 'nearest-exact', label: 'nearest-exact' }
            ], 'lanczos') +
            this._section('Pro·06 分块重绘（UltimateSDUpscale）') +
            this._check('启用分块重绘', 'flux_painter.pro.usdu.enabled', true) +
            this._select('采样器', 'flux_painter.pro.usdu.sampler', FluxSamplerOptions, 'euler') +
            this._select('调度器', 'flux_painter.pro.usdu.scheduler', FluxSchedulerOptions, 'simple') +
            this._select('分块模式', 'flux_painter.pro.usdu.mode_type', [
                { value: 'Linear', label: 'Linear' },
                { value: 'Chess', label: 'Chess' },
                { value: 'None', label: 'None' }
            ], 'Linear') +
            this._select('接缝修复', 'flux_painter.pro.usdu.seam_fix_mode', [
                { value: 'None', label: 'None' },
                { value: 'Band Pass', label: 'Band Pass' },
                { value: 'Half Tile', label: 'Half Tile' },
                { value: 'Half Tile + Intersections', label: 'Half Tile + Intersections' }
            ], 'None');
        [['denoise', 'denoise', 0.15, 0, 1, 0.01],
         ['steps', '步数', 20, 1, 200, 1],
         ['cfg', 'cfg', 8, 0, 30, 0.1],
         ['tile_width', '分块宽', 512, 64, 2048, 64],
         ['tile_height', '分块高', 512, 64, 2048, 64],
         ['mask_blur', '遮罩模糊', 32, 0, 64, 1],
         ['tile_padding', '分块重叠', 256, 0, 1024, 16],
         ['seam_fix_denoise', '接缝 denoise', 1, 0, 1, 0.05],
         ['seam_fix_width', '接缝宽', 64, 0, 1024, 8],
         ['seam_fix_mask_blur', '接缝模糊', 8, 0, 64, 1],
         ['seam_fix_padding', '接缝重叠', 16, 0, 512, 8]
        ].forEach(t => {
            hiresHtml += this._num(t[1], `flux_painter.pro.usdu.${t[0]}`, t[2], t[3], t[4], t[5]);
        });
        hiresHtml += this._check('强制统一分块', 'flux_painter.pro.usdu.force_uniform_tiles', true) +
            this._check('分块解码(tiled_decode)', 'flux_painter.pro.usdu.tiled_decode', false) +
            this._section('Pro·档位与基础采样') +
            this._check('Pro 档位启用', 'flux_painter.pro.enabled', true) +
            this._check('允许第三方插件', 'flux_painter.pro.allow_custom_nodes', true) +
            this._num('基础 cfg（pro）', 'flux_painter.pro.base_cfg', 4, 0, 30, 0.1) +
            this._num('基础步数（pro）', 'flux_painter.pro.base_steps', 30, 1, 200, 1);
        h += `<div class="tab-content" data-tab-content="flux_pro_hires">${hiresHtml}</div>`;

        // ===== Pro·局部细化（07：hand / face / eye + SAM） =====
        const detDefs = [
            { key: 'hand', label: '手部', det: 'bbox/hand_yolov8s.pt', d: 0.28, s: 14, c: 3 },
            { key: 'face', label: '面部', det: 'bbox/face_yolov8m.pt', d: 0.24, s: 14, c: 3 },
            { key: 'eye', label: '眼脸', det: 'bbox/face_yolov8m.pt', d: 0.18, s: 12, c: 2.8 }
        ];
        let detHtml = '';
        detDefs.forEach(x => {
            const p = `flux_painter.pro.detailers.${x.key}.`;
            detHtml += this._section(`Pro·07 ${x.label}细化（链式 ${x.key}）`) +
                this._check('启用', p + 'enabled', true) +
                this._text('检测器', p + 'detector', x.det) +
                this._num('denoise', p + 'denoise', x.d, 0, 1, 0.01) +
                this._num('步数', p + 'steps', x.s, 1, 100, 1) +
                this._num('cfg', p + 'cfg', x.c, 0, 30, 0.1) +
                this._num('guide_size', p + 'guide_size', 768, 64, 4096, 16) +
                this._num('max_size', p + 'max_size', 1280, 64, 4096, 16) +
                this._num('羽化 feather', p + 'feather', 8, 0, 100, 1) +
                this._num('检测阈值', p + 'bbox_threshold', 0.35, 0, 1, 0.01) +
                this._num('框膨胀', p + 'bbox_dilation', 16, -512, 512, 1) +
                this._num('裁剪系数', p + 'bbox_crop_factor', 2.5, 1, 10, 0.1) +
                this._check('noise_mask', p + 'noise_mask', true) +
                this._check('force_inpaint', p + 'force_inpaint', true);
        });
        let samHtml = this._section('Pro·SAM 与局部提示词') +
            this._text('SAM 模型', 'flux_painter.pro.sam_model', 'sam_vit_b_01ec64.pth') +
            this._select('SAM 检测提示', 'flux_painter.pro.sam.sam_detection_hint', [
                { value: 'center-1', label: 'center-1' },
                { value: 'horizontal-2', label: 'horizontal-2' },
                { value: 'vertical-2', label: 'vertical-2' },
                { value: 'rect-4', label: 'rect-4' },
                { value: 'diamond-4', label: 'diamond-4' },
                { value: 'mask-area', label: 'mask-area' }
            ], 'center-1') +
            this._select('负向提示用法', 'flux_painter.pro.sam.sam_mask_hint_use_negative', [
                { value: 'False', label: 'False' },
                { value: 'Small', label: 'Small' },
                { value: 'Outter', label: 'Outter' }
            ], 'False');
        [['sam_threshold', 'SAM 阈值', 0.93, 0, 1, 0.01],
         ['sam_dilation', 'SAM 膨胀', 0, -512, 512, 1],
         ['sam_bbox_expansion', 'SAM 框扩展', 0, 0, 1000, 1],
         ['sam_mask_hint_threshold', 'SAM 提示阈值', 0.7, 0, 1, 0.01],
         ['drop_size', '丢弃最小尺寸', 10, 1, 1024, 1],
         ['cycle', '循环次数', 1, 1, 10, 1],
         ['noise_mask_feather', '遮罩羽化', 20, 0, 100, 1]
        ].forEach(t => {
            samHtml += this._num(t[1], `flux_painter.pro.sam.${t[0]}`, t[2], t[3], t[4], t[5]);
        });
        samHtml += `<div class="form-group"><label>${this._t('局部正向提示词（手部区域）')}</label>
                <textarea data-path="flux_painter.pro.pos_hand" rows="2"
                    style="width:100%;font-family:inherit;font-size:13px;">${posHandCur}</textarea></div>` +
            `<div class="form-group"><label>${this._t('局部负向提示词（手部区域）')}</label>
                <textarea data-path="flux_painter.pro.neg_hand" rows="3"
                    style="width:100%;font-family:inherit;font-size:13px;">${negHandCur}</textarea></div>`;
        h += `<div class="tab-content" data-tab-content="flux_pro_det">${detHtml}${samHtml}</div>`;

        // ===== 审查与安全 =====
        h += `<div class="tab-content" data-tab-content="flux_review">` +
            this._section('审查与安全（ONNX 裸露判定）') +
            this._check('开启审查', 'flux_painter.review_enabled', false) +
            this._select('审查方式', 'flux_painter.review_mode', [
                { value: 'onnx', label: 'ONNX 自动（NudeNet，与 QQ 群聊同模型）' },
                { value: 'manual', label: '人工按钮（画板点通过 / 驳回）' }
            ], 'onnx') +
            this._check('启用裸露模型', 'flux_painter.nsfw_check.enabled', false) +
            this._num('判定阈值', 'flux_painter.nsfw_check.threshold', 0.45, 0, 1, 0.01) +
            this._select('模型异常时', 'flux_painter.nsfw_check.fail_action', [
                { value: 'dm', label: 'dm（保守：视为命中，只私发）' },
                { value: 'pass', label: 'pass（放行）' }
            ], 'dm') +
            this._text('检测模式名', 'flux_painter.nsfw_check.mode', 'nudenet') +
            this._text('模型路径', 'flux_painter.nsfw_check.model_path', '.ComfyNode/nsfw/nudenet.onnx') +
            this._text('模型下载源', 'flux_painter.nsfw_check.model_url',
                'https://huggingface.co/vladmandic/nudenet/resolve/main/nudenet.onnx') +
            `</div>`;

        // ===== 引擎与路径 =====
        h += `<div class="tab-content" data-tab-content="flux_engine">` +
            this._section('引擎与路径（改后需重启绘画引擎）') +
            this._text('监听地址', 'flux_painter.comfy.host', '127.0.0.1') +
            this._check('独立引擎窗口', 'flux_painter.comfy.engine_window', true) +
            this._check('画板实时进度（阶段/百分比/步进）', 'flux_painter.progress_detail', true) +
            this._text('内核目录', 'flux_painter.comfy.comfy_node_dir', '.ComfyNode') +
            this._text('输出目录', 'flux_painter.comfy.output_dir', '.ComfyNode/output') +
            this._text('工作流文件', 'flux_painter.comfy.workflow_file', '.ComfyNode/node/workflow.json') +
            this._text('提示词参考目录', 'flux_painter.comfy.prompt_reference_dir', '.ComfyNode/prompt_reference') +
            this._text('画师数据', 'flux_painter.comfy.artist_data', '.ComfyNode/artist/data.js') +
            this._text('内核解释器（须指向装了 torch 的 python）',
                'flux_painter.comfy.internal_python', '') +
            this._text('内核 main.py（备用，当前版本固定用 .ComfyNode/ComfyUI/main.py）',
                'flux_painter.comfy.internal_main', '') +
            `</div>`;
        return h;
    },
});

/* flux_painter 保存补偿：
   1) 数组/对象数组路径（lora_chain / style_on_keywords / artist_sources）：把编辑器值还原成数组写回 config 树
   2) 长文本 textarea（quality_prefix / negative_prompt / pos_hand / neg_hand）：
      若 collectValues 未收录 textarea，则直接从 DOM 兜底读取，避免保存时被清空 */
if (typeof Config !== 'undefined' && Config) {
    const __origApplyUpdates = Config.applyUpdates ? Config.applyUpdates.bind(Config) : null;

    const setDeep = (obj, path, value) => {
        const keys = String(path).split('.');
        let node = obj;
        for (let i = 0; i < keys.length - 1; i++) {
            const k = keys[i];
            if (!node[k] || typeof node[k] !== 'object') node[k] = {};
            node = node[k];
        }
        node[keys[keys.length - 1]] = value;
    };
    const domVal = (path) => {
        const el = document.querySelector(`[data-path="${path}"]`);
        return el ? el.value : undefined;
    };
    const splitList = (v) => String(v == null ? '' : v)
        .split(/[\s,，;；]+/).map(s => s.trim()).filter(Boolean);
    const parseSources = (v) => String(v == null ? '' : v).split(/\r?\n/)
        .map(line => {
            const t = line.trim();
            if (!t) return null;
            const parts = t.split('|').map(s => s.trim());
            return parts[0] ? { name: parts[0], url: parts[1] || '' } : null;
        }).filter(Boolean);

    const ARR_PATHS = {
        'flux_painter.lora_chain': (v) => {
            try {
                const a = JSON.parse(v || '[]');
                return Array.isArray(a) ? a : [];
            } catch (e) { return []; }
        },
        'flux_painter.style_on_keywords': (v) => {
            try {
                const a = JSON.parse(v || '[]');
                return Array.isArray(a) ? a : [];
            } catch (e) { return splitList(v); }
        },
        'flux_painter.artist_sources': parseSources
    };
    const TEXT_PATHS = [
        'flux_painter.quality_prefix', 'flux_painter.negative_prompt',
        'flux_painter.pro.pos_hand', 'flux_painter.pro.neg_hand'
    ];

    Config.applyUpdates = function (updates, target) {
        if (__origApplyUpdates) __origApplyUpdates(updates, target);
        if (!target) return target;
        const findHit = (path) => (updates || []).find(u => u && u.path === path);
        Object.keys(ARR_PATHS).forEach(path => {
            const hit = findHit(path);
            const raw = hit ? hit.value : domVal(path);
            if (raw === undefined) return;
            setDeep(target, path, ARR_PATHS[path](raw));
        });
        TEXT_PATHS.forEach(path => {
            if (findHit(path)) return;          // 已被正常收集，无需兜底
            const raw = domVal(path);
            if (raw === undefined) return;
            setDeep(target, path, raw);
        });
        return target;
    };
}
