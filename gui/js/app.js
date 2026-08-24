/**
 * Main application entry point
 */
const App = {
    config: null,
    calendarData: {},

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

    // ============ 服务启动球 ============
    async onLaunchClick(id) {
        const map = {
            sensevoice: { fn: () => API.startSensevoice(), name: 'SenseVoice' },
            sovits: { fn: () => API.startSovits(), name: 'SoVITS' },
            main: { fn: () => API.startMain(), name: '主程序' },
            napcat: { fn: () => API.startNapcat(), name: 'NapCat' },
            netease: { fn: () => API.startNetease(), name: '网易云' },
            rvc: { fn: () => API.startRvc(), name: 'RVC' }
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

    // ============ 配置节点 ============
    async onPlanetClick(id) {
        console.log('App.onPlanetClick received:', id);

        // 特殊面板
        if (id === 'character') { await this.openCharacterPanel(); return; }
        if (id === 'sensevoice') { await this.openSensevoicePanel(); return; }
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

        // 主动回复子球（配置/浏览）
        if (id === 'active_config') { await this.openActiveConfigPanel(); return; }
        if (id === 'active_browse') { await this.openActiveBrowsePanel(); return; }

        // 歌曲子球（模型/歌曲/翻唱/感想）
        if (id === 'meowsinger_model') { this._openConfigPanel('歌曲模型设置', () => Config.meowsingerModel()); return; }
        if (id === 'meowsinger_song') { this._openConfigPanel('点歌设置', () => Config.meowsingerSong()); return; }
        if (id === 'meowsinger_cover') { await this.openMeowsingerCoverPanel(); return; }
        if (id === 'meowsinger_sentiment') { this._openConfigPanel('感想设置', () => Config.meowsingerSentiment()); return; }

        // VTS 子球（配置/表情/窗口/参数）
        if (id === 'vts_config') { this._openConfigPanel('VTS 配置', () => Config.vts_config()); return; }
        if (id === 'vts_emotion') { this._openConfigPanel('VTS 表情绑定', () => Config.vts_emotion()); return; }
        if (id === 'vts_window') { this._openConfigPanel('VTS 窗口', () => Config.vts_window()); return; }
        if (id === 'vts_params') { this._openConfigPanel('VTS 模型参数', () => Config.vts_params()); return; }

        // CatBrain 子球
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
            'basic': { title: '基本设置', fn: () => Config.basic() },
            'subtitle': { title: '字幕设置', fn: () => Config.subtitle() },
            'active': { title: '主动回复设置', fn: () => Config.llm_active() }
        };

        const panel = panelMap[id];
        if (!panel) {
            console.warn('No panel found for id:', id);
            return;
        }
        this._openConfigPanel(panel.title, panel.fn);
    },

    // ============ 主动回复子球：配置 ============
    async openActiveConfigPanel() {
        const html = Config.llm_active();
        Modal.show('主动回复配置', html, async () => {
            try {
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                await API.saveConfig(this.config);
                this.showToast('主动回复配置已保存');
            } catch (e) {
                this.showToast('保存失败: ' + e.message, true);
            }
        });
        setTimeout(() => {
            this.bindTabs();
            this.bindSplitFlagEditor();
            this.bindWordTagEditor();
            this.bindDictEditors();
            this.bindSessdataVerify();
            this.bindBiliLogin();
        }, 10);
    },

    // ============ 主动回复子球：浏览 ============
    async openActiveBrowsePanel() {
        let cache = [];
        let collected = [];
        try {
            [cache, collected] = await Promise.all([
                API.getWebBrowseCache(),
                API.getWebBrowseCollected()
            ]);
        } catch (e) {
            console.warn('加载浏览数据失败:', e);
        }
        const html = Config.webBrowsePanel({}, cache, collected);
        Modal.show('B站内容浏览', html, async () => {
            try {
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                await API.saveConfig(this.config);
                this.showToast('B站浏览配置已保存');
            } catch (e) {
                this.showToast('保存失败: ' + e.message, true);
            }
        });
        setTimeout(() => {
            this.bindBiliLogin();
            this.bindWebBrowseRefresh();
        }, 10);
    },

    bindWebBrowseRefresh() {
        const btn = document.querySelector('.webbrowse-refresh-btn');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            try {
                const [cache, collected] = await Promise.all([
                    API.getWebBrowseCache(),
                    API.getWebBrowseCollected()
                ]);
                const cacheEl = document.getElementById('webBrowseCacheList');
                const collectedEl = document.getElementById('webBrowseCollectedList');
                if (cacheEl) cacheEl.innerHTML = Config._videoList(cache, false);
                if (collectedEl) collectedEl.innerHTML = Config._videoList(collected, true);
                this.showToast('列表已刷新');
            } catch (e) {
                this.showToast('刷新失败: ' + e.message, true);
            } finally {
                btn.disabled = false;
            }
        });
    },

    // ============ Toolbox 子视图 ============
    openToolbox() {
        const overlay = document.getElementById('toolboxOverlay');
        if (overlay) overlay.classList.add('show');
    },

    closeToolbox() {
        const overlay = document.getElementById('toolboxOverlay');
        if (overlay) overlay.classList.remove('show');
    },

    // ============ 待办提醒面板 ============
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
                    <button type="button" class="btn btn-secondary backlog-add-todo" data-user="${this._escAttr(u)}">添加待办</button>
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
            <div class="form-group"><label>提醒日期</label>
                <input type="text" data-todo-field="day" value="${this._esc(todo.day || '')}" placeholder="MM-DD，留空/none 每天"></div>
            <div class="form-group"><label>提醒时间</label>
                <div class="time-row">
                    <input type="number" data-todo-field="time_hour" value="${this._esc(timeHour)}" min="0" max="23" placeholder="时">
                    <span class="time-colon">:</span>
                    <input type="number" data-todo-field="time_minute" value="${this._esc(timeMinute)}" min="0" max="59" placeholder="分">
                </div></div>
            <div class="form-group"><label>类型</label>
                <button type="button" class="btn btn-secondary cycle-btn" data-todo-field="type" data-todo-values="instant,steady" data-todo-value="${type}">${type}</button></div>
            <div class="form-group"><label>QQ提醒</label>
                <button type="button" class="btn btn-secondary cycle-btn" data-todo-field="qq" data-todo-values="false,true" data-todo-value="${qq ? 'true' : 'false'}">${qq ? '开' : '关'}</button></div>
            <div class="form-group"><label>重复间隔(秒)</label>
                <input type="number" data-todo-field="repeat_interval" value="${todo.repeat_interval != null ? todo.repeat_interval : 300}"></div>
            <div class="form-group"><label>总次数</label>
                <input type="number" data-todo-field="loop" value="${todo.loop != null ? todo.loop : 2}"></div>
            <div class="form-group"><label>提醒内容</label>
                <input type="text" data-todo-field="content" value="${this._esc(todo.content || '')}" placeholder="提醒内容"></div>
            <button type="button" class="btn btn-secondary backlog-remove-todo">删除待办</button>
        </div>`;
    },

    _esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },

    _escAttr(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
            'meowsongs': { title: '即兴哼唱设置', fn: () => Config.meowsongs() }
        };
        const panel = map[id];
        if (!panel) {
            console.warn('No toolbox panel for id:', id);
            return;
        }
        this._openConfigPanel(panel.title, panel.fn);
    },

    // 普通配置面板（保存到 config.yml）
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
            this.bindVtsWindowPreview();
            this.bindVtsParamsQuery();
        }, 10);
    },

    bindSessdataVerify() {
        const btn = document.querySelector('.sessdata-verify-btn');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            const input = document.querySelector('input[data-path="danmaku.blivedm.sessdata"]');
            const resultEl = document.querySelector('.sessdata-verify-result');
            const sessdata = (input && input.value || '').trim();
            if (!sessdata) {
                if (resultEl) resultEl.textContent = '请先输入 SESSDATA';
                return;
            }
            if (resultEl) resultEl.textContent = '验证中...';
            try {
                const r = await API.verifySessdata(sessdata);
                if (resultEl) resultEl.textContent = (r.ok ? '✓ ' : '✗ ') + (r.message || '');
            } catch (err) {
                if (resultEl) resultEl.textContent = '验证失败: ' + err.message;
            }
        });
    },

    bindBiliLogin() {
        document.querySelectorAll('.bili-login-btn').forEach(btn => {
            const target = btn.dataset.target || 'danmaku';
            btn.addEventListener('click', () => this.openBiliLogin(target));
        });
    },

    openBiliLogin(target) {
        target = target || 'danmaku';
        // 独立的扫码登录弹窗（不复用配置 Modal，避免「保存」语义冲突）
        const overlay = document.createElement('div');
        overlay.className = 'bili-login-overlay';
        overlay.innerHTML = `
            <div class="bili-login-box">
                <div class="bili-login-header">
                    <span>B站扫码登录</span>
                    <button type="button" class="bili-login-close">&times;</button>
                </div>
                <div class="bili-login-body">
                    <div class="bili-login-qr-wrap">
                        <img class="bili-login-qr" alt="登录二维码" src="">
                    </div>
                    <div class="bili-login-status">正在生成二维码...</div>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const img = overlay.querySelector('.bili-login-qr');
        const statusEl = overlay.querySelector('.bili-login-status');
        const closeBtn = overlay.querySelector('.bili-login-close');
        let timer = null;

        const close = () => {
            if (timer) clearInterval(timer);
            overlay.remove();
        };
        closeBtn.addEventListener('click', close);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

        const fillBack = (sessdata, biliJct, mid) => {
            // 回填到对应配置面板的输入框 + 内存 config 对象
            const sPath = target === 'web_browse' ? 'llm_active.web_browse.sessdata' : 'danmaku.blivedm.sessdata';
            const jPath = target === 'web_browse' ? 'llm_active.web_browse.bili_jct' : 'danmaku.blivedm.bili_jct';
            const sInput = document.querySelector(`input[data-path="${sPath}"]`);
            const jInput = document.querySelector(`input[data-path="${jPath}"]`);
            if (sInput) sInput.value = sessdata || '';
            if (jInput) jInput.value = biliJct || '';
            if (mid) {
                const mInput = document.querySelector('input[data-path="llm_active.web_browse.mid"]');
                if (mInput) mInput.value = mid;
            }
            if (this.config) {
                if (target === 'web_browse') {
                    this.config.llm_active = this.config.llm_active || {};
                    this.config.llm_active.web_browse = this.config.llm_active.web_browse || {};
                    this.config.llm_active.web_browse.sessdata = sessdata || '';
                    this.config.llm_active.web_browse.bili_jct = biliJct || '';
                    if (mid) this.config.llm_active.web_browse.mid = mid;
                } else {
                    this.config.danmaku = this.config.danmaku || {};
                    this.config.danmaku.blivedm = this.config.danmaku.blivedm || {};
                    this.config.danmaku.blivedm.sessdata = sessdata || '';
                    this.config.danmaku.blivedm.bili_jct = biliJct || '';
                }
            }
        };

        const poll = async (qrcodeKey) => {
            try {
                const r = await API.checkBiliLogin(qrcodeKey, target);
                if (r && r.status === 'success') {
                    statusEl.textContent = '✓ ' + (r.message || '登录成功');
                    statusEl.classList.add('success');
                    fillBack(r.sessdata, r.bili_jct, r.mid);
                    clearInterval(timer);
                    setTimeout(close, 1200);
                    return true;
                }
                if (r && (r.status === 'expired' || (r.ok === false && r.status === 'error'))) {
                    statusEl.textContent = '✗ ' + (r.message || '登录失败');
                    statusEl.classList.add('error');
                    clearInterval(timer);
                    return true;
                }
                statusEl.textContent = (r && r.message) ? r.message : '等待扫码...';
            } catch (err) {
                statusEl.textContent = '轮询失败: ' + err.message;
                clearInterval(timer);
            }
            return false;
        };

        API.startBiliLogin(target).then(r => {
            if (!r || !r.ok) {
                statusEl.textContent = '✗ ' + (r.message || '生成二维码失败');
                statusEl.classList.add('error');
                return;
            }
            img.src = r.qrcode;
            statusEl.textContent = '请用手机 B站 App 扫码，并确认登录';
            timer = setInterval(() => poll(r.qrcode_key), 2000);
        }).catch(err => {
            statusEl.textContent = '生成二维码失败: ' + err.message;
            statusEl.classList.add('error');
        });
    },

    // ============ 数据库来源站点编辑器 ============
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

    // ============ 知识库一键预填 ============
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

    // ============ 键值对编辑器事件绑定 ============
    bindDictEditors() {
        // 简单键值对（group_bots：机器人名 → QQ号）
        document.querySelectorAll('[data-kv-editor]').forEach(editor => {
            const path = editor.dataset.kvEditor;
            const container = editor.parentElement;
            const hidden = container.querySelector(`input[data-path="${path}"]`);
            const addBtn = container.querySelector(`[data-kv-add="${path}"]`);
            const sync = () => {
                const obj = {};
                editor.querySelectorAll('.kv-row').forEach(row => {
                    const k = row.querySelector('[data-kv-key]');
                    const v = row.querySelector('[data-kv-value]');
                    if (k && v && k.value.trim()) obj[k.value.trim()] = v.value.trim();
                });
                if (hidden) hidden.value = JSON.stringify(obj);
            };
            editor.addEventListener('click', (e) => {
                const btn = e.target.closest('.kv-remove');
                if (btn) { btn.closest('.kv-row').remove(); sync(); }
            });
            editor.addEventListener('input', sync);
            if (addBtn) {
                addBtn.addEventListener('click', () => {
                    const keyLabel = editor.dataset.kvKeyLabel || '机器人名';
                    const valueLabel = editor.dataset.kvValueLabel || 'QQ号';
                    const empty = editor.querySelector('.help-text');
                    if (empty) empty.remove();
                    editor.insertAdjacentHTML('beforeend', Config._kvRow('', '', keyLabel, valueLabel));
                    sync();
                });
            }
        });

        // 每群配置（group_per_group：群号 → 触发基数/pass次数）
        document.querySelectorAll('[data-gc-editor]').forEach(editor => {
            const path = editor.dataset.gcEditor;
            const container = editor.parentElement;
            const hidden = container.querySelector(`input[data-path="${path}"]`);
            const addBtn = container.querySelector(`[data-gc-add="${path}"]`);
            const sync = () => {
                const obj = {};
                editor.querySelectorAll('.kv-row').forEach(row => {
                    const g = row.querySelector('[data-gc-group]');
                    const b = row.querySelector('[data-gc-base]');
                    const p = row.querySelector('[data-gc-pass]');
                    if (g && g.value.trim()) {
                        const cfg = {};
                        if (b && b.value !== '') cfg.reply_base = parseInt(b.value, 10);
                        if (p && p.value !== '') cfg.pass_rounds = parseInt(p.value, 10);
                        obj[g.value.trim()] = cfg;
                    }
                });
                if (hidden) hidden.value = JSON.stringify(obj);
            };
            editor.addEventListener('click', (e) => {
                const btn = e.target.closest('.kv-remove');
                if (btn) { btn.closest('.kv-row').remove(); sync(); }
            });
            editor.addEventListener('input', sync);
            if (addBtn) {
                addBtn.addEventListener('click', () => {
                    const empty = editor.querySelector('.help-text');
                    if (empty) empty.remove();
                    editor.insertAdjacentHTML('beforeend', Config._groupConfigRow('', {}));
                    sync();
                });
            }
        });
    },

    // ============ VTS 窗口全屏预览（拖拽/等比缩放） ============
    bindVtsWindowPreview() {
        const preview = document.querySelector('[data-window-preview]');
        if (!preview) return;
        const screenEl = preview.querySelector('[data-window-screen]');
        const box = preview.querySelector('[data-window-box]');
        const sizeLabel = preview.querySelector('[data-window-size]');
        // 像素输入框位于 .window-preview-fields，它是 data-window-preview 的兄弟节点，
        // 必须在父容器（.form-group）内查找，否则这里拿不到输入框会导致函数提前 return、
        // 拖拽事件从未绑定（症状：光标变成拖拽符号但完全拖不动）。
        const scope = preview.closest('.form-group') || preview.parentElement || document;
        const fieldX = scope.querySelector('input[data-window-field="x"]');
        const fieldY = scope.querySelector('input[data-window-field="y"]');
        const fieldW = scope.querySelector('input[data-window-field="w"]');
        const fieldH = scope.querySelector('input[data-window-field="h"]');
        if (!screenEl || !box || !fieldX || !fieldY || !fieldW || !fieldH) return;

        const MIN = 50;
        const infoLabel = (preview.closest('.form-group') || document).querySelector('[data-screen-info]');

        // 先用浏览器 window.screen 兜底，随后用后端真实屏幕信息覆盖（与 tkinter 置顶窗口坐标一致）
        let screenW = window.screen.width || 1920;
        let screenH = window.screen.height || 1080;
        let screenRatio = screenW / screenH;

        let winW = parseFloat(fieldW.value) || 400;
        let winH = parseFloat(fieldH.value) || 600;
        let winX = parseFloat(fieldX.value) || 0;
        let winY = parseFloat(fieldY.value) || 0;
        // 用户手动改过像素后，不再被异步到达的屏幕信息强制等比重置
        let userEdited = false;

        // 按当前屏幕比例等比缩放（保持宽度，调整高度）
        const normalizeRatio = () => {
            if (screenRatio > 0 && Math.abs(winW / winH - screenRatio) > 0.01) {
                winH = Math.round(winW / screenRatio);
            }
        };

        // 让预览「屏幕」画布也按真实屏幕比例显示高度（限制在合理区间，避免竖屏/带鱼屏过高过矮）
        const applyScreenAspect = () => {
            if (!(screenW > 0) || !(screenH > 0)) return;
            const cw = screenEl.clientWidth || 1;
            const targetH = cw / (screenW / screenH);
            const clamped = Math.max(180, Math.min(420, targetH));
            screenEl.style.height = clamped + 'px';
        };

        const updateScreenInfo = () => {
            if (infoLabel) {
                infoLabel.textContent = `当前屏幕分辨率：${screenW}×${screenH}（窗口按屏幕比例等比缩放）`;
            }
        };

        const scaleOf = () => {
            const cw = screenEl.clientWidth || 1;
            const ch = screenEl.clientHeight || 1;
            return { sx: cw / screenW, sy: ch / screenH };
        };

        const render = () => {
            const { sx, sy } = scaleOf();
            box.style.left = (winX * sx) + 'px';
            box.style.top = (winY * sy) + 'px';
            box.style.width = (winW * sx) + 'px';
            box.style.height = (winH * sy) + 'px';
            if (sizeLabel) sizeLabel.textContent = `${Math.round(winW)}×${Math.round(winH)}`;
        };

        const sync = () => {
            winW = Math.max(MIN, Math.min(winW, screenW));
            winH = Math.max(MIN, Math.min(winH, screenH));
            winX = Math.max(0, Math.min(screenW - winW, winX));
            winY = Math.max(0, Math.min(screenH - winH, winY));
            fieldX.value = Math.round(winX);
            fieldY.value = Math.round(winY);
            fieldW.value = Math.round(winW);
            fieldH.value = Math.round(winH);
            render();
        };

        const select = () => box.classList.add('selected');
        const deselect = () => box.classList.remove('selected');

        // ---- 最兼容拖拽：onmousedown + document mousemove/mouseup ----
        let drag = null;

        const startDrag = (e, mode) => {
            if (e.button !== 0) return; // 仅左键
            e.preventDefault();
            drag = {
                mode,
                startX: e.clientX,
                startY: e.clientY,
                origX: winX,
                origY: winY,
                origW: winW,
                origH: winH,
                ratio: winW / winH,
            };
            select();
            console.log('[VTS窗口] 开始拖拽', mode);
            document.addEventListener('mousemove', onDragMove);
            document.addEventListener('mouseup', onDragEnd);
        };

        const onDragMove = (e) => {
            if (!drag) return;
            const { sx, sy } = scaleOf();
            const dx = (e.clientX - drag.startX) / sx;
            const dy = (e.clientY - drag.startY) / sy;

            if (drag.mode === 'move') {
                winX = drag.origX + dx;
                winY = drag.origY + dy;
                sync();
                return;
            }

            const dir = drag.mode;
            const hx = dir.includes('w') ? -1 : 1;
            const vy = dir.includes('n') ? -1 : 1;
            const dw = dx * hx;
            const dh = dy * vy;
            const ratio = drag.ratio;

            let nw, nh;
            if (Math.abs(dw / drag.origW) > Math.abs(dh / drag.origH)) {
                nw = drag.origW + dw;
                nh = nw / ratio;
            } else {
                nh = drag.origH + dh;
                nw = nh * ratio;
            }
            if (nw < MIN) { nw = MIN; nh = nw / ratio; }
            if (nh < MIN) { nh = MIN; nw = nh * ratio; }

            if (hx === 1) winX = drag.origX; else winX = drag.origX + drag.origW - nw;
            if (vy === 1) winY = drag.origY; else winY = drag.origY + drag.origH - nh;
            winW = nw;
            winH = nh;
            sync();
        };

        const onDragEnd = () => {
            drag = null;
            document.removeEventListener('mousemove', onDragMove);
            document.removeEventListener('mouseup', onDragEnd);
            console.log('[VTS窗口] 结束拖拽');
        };

        // 直接用 onmousedown 属性（最可靠），不用 addEventListener
        box.onmousedown = (e) => {
            if (e.target.closest('[data-handle]')) return;
            startDrag(e, 'move');
        };

        preview.querySelectorAll('[data-handle]').forEach(h => {
            h.onmousedown = (e) => {
                startDrag(e, h.dataset.handle);
            };
        });

        // 点空白取消选中
        screenEl.onmousedown = (e) => {
            if (e.target === screenEl) deselect();
        };

        // 手动输入像素时同步预览
        const onFieldInput = () => {
            winW = parseFloat(fieldW.value) || MIN;
            winH = parseFloat(fieldH.value) || MIN;
            winX = parseFloat(fieldX.value) || 0;
            winY = parseFloat(fieldY.value) || 0;
            userEdited = true;
            sync();
        };
        fieldX.addEventListener('input', onFieldInput);
        fieldY.addEventListener('input', onFieldInput);
        fieldW.addEventListener('input', onFieldInput);
        fieldH.addEventListener('input', onFieldInput);

        // 初始渲染（先用 window.screen 兜底，保证面板打开即可见、可拖拽）
        normalizeRatio();
        applyScreenAspect();
        updateScreenInfo();
        sync();

        // 异步获取后端真实屏幕信息（与 tkinter 置顶窗口同一坐标系统），按真实屏幕比例重新缩放
        if (typeof API !== 'undefined' && typeof API.getScreenInfo === 'function') {
            API.getScreenInfo().then((info) => {
                if (!info || !(info.width > 0) || !(info.height > 0)) return;
                screenW = info.width;
                screenH = info.height;
                screenRatio = screenW / screenH;
                // 用户尚未手动调整时，按真实屏幕比例重新等比缩放
                if (!userEdited) normalizeRatio();
                applyScreenAspect();
                updateScreenInfo();
                sync();
            }).catch(() => {});
        }
    },

    // ============ VTS 参数查询 ============
    bindVtsParamsQuery() {
        const btn = document.querySelector('[data-vts-query]');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            const resultEl = document.querySelector('[data-vts-params-result]');
            btn.disabled = true;
            if (resultEl) resultEl.innerHTML = '<div class="help-text">查询中，请稍候…</div>';
            try {
                const r = await API.getVtsParameters();
                if (r && r.ok) {
                    const data = r.data || {};
                    if (resultEl) resultEl.innerHTML = Config._vtsParamsTable(data, data);
                } else {
                    const msg = (r && r.data) ? r.data : '查询失败';
                    if (resultEl) resultEl.innerHTML = `<div class="help-text">${this._esc(msg)}</div>`;
                }
            } catch (e) {
                if (resultEl) resultEl.innerHTML = `<div class="help-text">查询失败：${this._esc(e.message)}</div>`;
            } finally {
                btn.disabled = false;
            }
        });
    },

    // ============ 歌曲翻唱面板（RVC 模型/索引下拉） ============
    async openMeowsingerCoverPanel() {
        let models = [], indices = [];
        try {
            const r = await API.getRvcModels();
            models = r.models || [];
            indices = r.indices || [];
        } catch (e) {
            console.warn('加载 RVC 模型列表失败:', e);
        }
        this._openConfigPanel('翻唱设置', () => Config.meowsingerCover(models, indices));
    },

    // ============ LLM 面板（含前置词/后置词） ============
    async openLlmModelPanel() {
        try {
            const html = Config.llm_model();
            Modal.show('LLM 模型设置', html, async () => {
                try {
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);
                    this.showToast('LLM 模型配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
            setTimeout(() => {
                this.bindTabs();
                this.bindSplitFlagEditor();
            }, 10);
        } catch (e) {
            console.error('Error rendering llm model panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    async openLlmPromptPanel() {
        try {
            let frontData = {};
            try {
                frontData = await API.getFrontPrompt() || {};
            } catch (e) {
                console.warn('加载前置词失败:', e);
            }
            const html = Config.llm_prompt(frontData);
            Modal.show('LLM 提示词设置', html, async () => {
                try {
                    const front = {
                        prompt: document.getElementById('frontPromptInput')?.value || '',
                        prompt_active: document.getElementById('activeFrontPromptInput')?.value || '',
                        prompt_napcat: document.getElementById('napcatFrontPromptInput')?.value || '',
                        post_prompt: document.getElementById('postPromptInput')?.value || ''
                    };
                    await API.saveFrontPrompt(front);
                    this.showToast('提示词已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering llm prompt panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    async openLlmAlgorithmPanel() {
        try {
            const html = Config.llm_algorithm();
            Modal.show('LLM 算法设置', html, async () => {
                try {
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);
                    this.showToast('算法配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering llm algorithm panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ 角色卡面板 ============
    async openCharacterPanel() {
        try {
            const files = await API.getCharacterCards();
            const cardFile = Config._val('character_card.card_file', 'prompt');
            const data = await API.getCharacterCard(cardFile);

            const html = Config.characterCardConfig(files) + Config.characterCardData(data);
            Modal.show('角色卡配置', html, async () => {
                try {
                    // 1. 收集角色卡 JSON 字段
                    const charData = Config.collectCharacterCard();
                    const newCardFile = Config._val('character_card.card_file', 'prompt');
                    await API.saveCharacterCard(newCardFile, charData);

                    // 2. 保存 config.yml 的 character_card 节点（select 自动同步为角色名）
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    if (charData.characters && charData.characters[0] && charData.characters[0].name) {
                        this.config.character_card = this.config.character_card || {};
                        this.config.character_card.select = charData.characters[0].name;
                    }
                    await API.saveConfig(this.config);

                    this.showToast('角色卡已保存');
                } catch (e) {
                    this.showToast('角色卡保存失败: ' + e.message, true);
                }
            });

            this.bindCharacterEvents(files);
        } catch (e) {
            console.error('Error loading character card:', e);
            this.showToast('加载角色卡失败: ' + e.message, true);
        }
    },

    bindCharacterEvents() {
        // 添加设定
        const addSetting = document.getElementById('addSettingBtn');
        if (addSetting) {
            addSetting.addEventListener('click', () => {
                const list = document.getElementById('settingList');
                const idx = list.querySelectorAll('.dict-row').length;
                list.insertAdjacentHTML('beforeend', Config._settingRow(idx, 'setting' + (idx + 1), ''));
            });
        }
        // 新建性格
        const addPersonality = document.getElementById('addPersonalityBtn');
        if (addPersonality) {
            addPersonality.addEventListener('click', () => {
                const list = document.getElementById('personalityList');
                const idx = list.querySelectorAll('.dict-row').length;
                list.insertAdjacentHTML('beforeend', Config._personalityRow(idx, '', ''));
            });
        }
        // 新建角色卡文件
        const newCard = document.getElementById('newCardBtn');
        if (newCard) {
            newCard.addEventListener('click', async () => {
                const name = prompt('请输入新角色卡文件名（不含 .json）：');
                if (!name) return;
                try {
                    const empty = { characters: [{ name: '', nickname: '', personality: {}, setting: {}, appearance: '', birthday: '', id_card: '', qq: '', phone: '', mbti: '', favorite: '', hobbies: '', dislikes: '', relationships: '' }] };
                    await API.saveCharacterCard(name, empty);
                    this.showToast('角色卡已创建');
                    await this.openCharacterPanel();
                } catch (e) {
                    this.showToast('创建失败: ' + e.message, true);
                }
            });
        }
        // 切换角色卡文件
        const cardSelect = document.getElementById('cardFileSelect');
        if (cardSelect) {
            cardSelect.addEventListener('change', async () => {
                this.config.character_card = this.config.character_card || {};
                this.config.character_card.card_file = cardSelect.value;
                await this.openCharacterPanel();
            });
        }
    },

    // ============ SenseVoice 面板（含声纹管理） ============
    async openSensevoicePanel() {
        try {
            const html = Config.sensevoice() + Config.speakerManager();
            Modal.show('SenseVoice 设置', html, async () => {
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                // 易错词替换规则（dict 结构单独收集）
                this.config.sensevoice = this.config.sensevoice || {};
                this.config.sensevoice.replace_rules = Config.collectReplaceRules();
                try {
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });

            // 渲染易错词替换规则
            const rulesEl = document.getElementById('replaceRulesList');
            if (rulesEl) {
                const rules = (this.config.sensevoice && this.config.sensevoice.replace_rules) || {};
                rulesEl.innerHTML = Config.replaceRulesPanel(rules);
            }
            this.bindReplaceRuleEvents();

            await this.loadSpeakers();
            this.bindSpeakerEvents();
        } catch (e) {
            console.error('Error rendering sensevoice panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    bindReplaceRuleEvents() {
        const addBtn = document.getElementById('addReplaceRuleBtn');
        if (addBtn) {
            addBtn.addEventListener('click', () => {
                const list = document.getElementById('replaceRulesList');
                const empty = list.querySelector('.help-text');
                if (empty) empty.remove();
                list.insertAdjacentHTML('beforeend', Config.replaceRuleRow('', []));
            });
        }

        const list = document.getElementById('replaceRulesList');
        if (!list) return;

        // 错误词输入：回车添加 tag
        list.addEventListener('keydown', (e) => {
            const input = e.target.closest('.replace-wrong-input');
            if (!input || e.key !== 'Enter') return;
            e.preventDefault();
            const w = input.value.trim();
            if (!w) return;
            const tags = input.closest('.replace-wrong-editor').querySelector('.replace-wrong-tags');
            if (tags.querySelector(`[data-wrong="${w}"]`)) {
                input.value = '';
                return;
            }
            const tag = document.createElement('span');
            tag.className = 'split-tag';
            tag.dataset.wrong = w;
            tag.textContent = w;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'split-tag-remove';
            btn.innerHTML = '&times;';
            tag.appendChild(btn);
            tags.appendChild(tag);
            input.value = '';
        });

        // 错误词 tag：点击 × 删除
        list.addEventListener('click', (e) => {
            const btn = e.target.closest('.split-tag-remove');
            if (btn) btn.closest('.split-tag').remove();
        });
    },

    async loadSpeakers() {
        try {
            const speakers = await API.getSpeakers();
            this.renderSpeakerList(speakers);
        } catch (e) {
            const list = document.getElementById('speakerList');
            if (list) list.innerHTML = '<div class="help-text">加载声纹列表失败</div>';
        }
    },

    renderSpeakerList(speakers) {
        const container = document.getElementById('speakerList');
        if (!container) return;
        if (!speakers.length) {
            container.innerHTML = '<div class="help-text">暂无声纹用户，请新建或一键生成</div>';
            return;
        }
        container.innerHTML = speakers.map(s => `
            <div class="speaker-item">
                <input type="checkbox" id="spk_${s.name}" ${s.enabled ? 'checked' : ''} data-speaker-name="${s.name}">
                <label for="spk_${s.name}">${s.name}</label>
            </div>
        `).join('');
        container.querySelectorAll('input[data-speaker-name]').forEach(cb => {
            cb.addEventListener('change', async () => {
                try {
                    await API.toggleSpeaker(cb.dataset.speakerName, cb.checked);
                    this.showToast('声纹状态已更新');
                } catch (e) {
                    this.showToast('更新失败: ' + e.message, true);
                }
            });
        });
    },

    bindSpeakerEvents() {
        const buildBtn = document.getElementById('speakerBuildBtn');
        if (buildBtn) {
            buildBtn.addEventListener('click', async () => {
                try {
                    await API.buildAllSpeakers();
                    this.showToast('开始生成声纹...');
                    this.pollBuildStatus();
                } catch (e) {
                    this.showToast('启动失败: ' + e.message, true);
                }
            });
        }

        const createBtn = document.getElementById('speakerCreateBtn');
        if (createBtn) {
            createBtn.addEventListener('click', () => {
                this.showCreateSpeakerForm();
            });
        }
    },

    showCreateSpeakerForm() {
        const list = document.getElementById('speakerList');
        if (!list) return;
        const formHtml = `
            <div class="char-card" id="createSpeakerForm">
                <div class="char-card-title">新建声纹用户</div>
                <div class="form-group"><label>用户名</label>
                    <input type="text" id="newSpeakerName" placeholder="输入用户名"></div>
                <div class="form-group">
                    <label>拖拽 wav 文件到下方区域</label>
                    <div class="drop-zone" id="dropZone">
                        <input type="file" id="wavFileInput" accept=".wav" style="display:none;">
                        <span id="dropZoneText">点击或拖拽 wav 文件到此处</span>
                    </div>
                </div>
                <div class="speaker-actions">
                    <button class="btn btn-primary" id="submitSpeakerBtn">提交</button>
                    <button class="btn btn-secondary" id="cancelSpeakerBtn">取消</button>
                </div>
            </div>`;
        list.insertAdjacentHTML('afterend', formHtml);

        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('wavFileInput');
        const dropText = document.getElementById('dropZoneText');
        let selectedFile = null;

        dropZone.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', () => {
            selectedFile = fileInput.files[0];
            if (selectedFile) dropText.textContent = selectedFile.name;
        });
        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            selectedFile = e.dataTransfer.files[0];
            if (selectedFile) dropText.textContent = selectedFile.name;
        });

        document.getElementById('cancelSpeakerBtn').addEventListener('click', () => {
            const form = document.getElementById('createSpeakerForm');
            if (form) form.remove();
        });

        document.getElementById('submitSpeakerBtn').addEventListener('click', async () => {
            const name = document.getElementById('newSpeakerName').value.trim();
            if (!name) { this.showToast('请输入用户名', true); return; }
            if (!selectedFile) { this.showToast('请选择 wav 文件', true); return; }
            try {
                const result = await API.createSpeaker(name, selectedFile);
                if (result.status === 'ok') {
                    this.showToast('声纹用户已创建');
                    const form = document.getElementById('createSpeakerForm');
                    if (form) form.remove();
                    await this.loadSpeakers();
                } else {
                    this.showToast('创建失败: ' + (result.message || ''), true);
                }
            } catch (e) {
                this.showToast('创建失败: ' + e.message, true);
            }
        });
    },

    async pollBuildStatus() {
        const progressEl = document.getElementById('speakerBuildProgress');
        const timer = setInterval(async () => {
            try {
                const status = await API.getBuildStatus();
                if (progressEl) progressEl.textContent = status.progress || '生成中...';
                if (status.progress.includes('声纹库已写入') || status.progress.includes('未找到 wav')) {
                    clearInterval(timer);
                    this.showToast('声纹生成完成');
                    await this.loadSpeakers();
                }
            } catch (e) {
                clearInterval(timer);
            }
        }, 1500);
    },

    // ============ TTS 面板（含参考音频 + 模型） ============
    async openTtsPanel() {
        try {
            const html = Config.tts();
            Modal.show('TTS 设置', html, async () => {
                try {
                    // 1. config.yml 的 tts 节点
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);

                    // 2. 参考音频
                    const refAudio = Config.collectRefAudio();
                    await API.saveRefAudio(refAudio);

                    // 3. tts_infer.yaml 模型配置
                    const ttsModel = Config.collectTtsModel();
                    await API.saveTtsConfig(ttsModel);

                    this.showToast('TTS 配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });

            // 异步填充参考音频与模型配置
            const refAudio = await API.getRefAudio();
            const refPanel = document.getElementById('refAudioPanel');
            if (refPanel) {
                refPanel.innerHTML = Config.refAudioPanel(refAudio);
                Modal.initAutoGrow(refPanel);
            }

            const ttsModel = await API.getTtsConfig();
            const sovitsModels = await API.getSovitsModels();
            const modelPanel = document.getElementById('ttsModelPanel');
            if (modelPanel) modelPanel.innerHTML = Config.ttsModelPanel(ttsModel, sovitsModels);
        } catch (e) {
            console.error('Error rendering tts panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ TTS 子球：模型配置 ============
    async openTtsModelPanel() {
        try {
            const [ttsModel, sovitsModels, refAudio] = await Promise.all([
                API.getTtsConfig(),
                API.getSovitsModels(),
                API.getRefAudio()
            ]);
            const html = Config.tts_model_panel(ttsModel, sovitsModels);
            Modal.show('TTS 模型配置', html, async () => {
                try {
                    // 1. 参考音频（ref_audio/config.json）
                    const refAudioData = Config.collectRefAudio();
                    await API.saveRefAudio(refAudioData);
                    // 2. 模型权重（tts_infer.yaml）
                    const ttsModelData = Config.collectTtsModel();
                    await API.saveTtsConfig(ttsModelData);
                    this.showToast('模型配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });

            // 异步填充参考音频
            const refPanel = document.getElementById('refAudioPanel');
            if (refPanel) {
                refPanel.innerHTML = Config.refAudioPanel(refAudio);
                Modal.initAutoGrow(refPanel);
            }
        } catch (e) {
            console.error('Error rendering tts model panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ TTS 子球：参数配置 ============
    async openTtsParamsPanel() {
        try {
            const ttsModel = await API.getTtsConfig();
            const html = Config.tts_params_panel(ttsModel);
            Modal.show('TTS 参数配置', html, async () => {
                try {
                    // 1. config.yml 的 tts 节点（流式参数 + 音量 + 线程数）
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);
                    // 2. tts_infer.yaml 合成参数（语速/温度/top_k/top_p/切分）
                    const ttsModelData = Config.collectTtsModel();
                    await API.saveTtsConfig(ttsModelData);
                    this.showToast('参数配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering tts params panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ TTS 子球：打断与流式开关 ============
    async openTtsConfigPanel() {
        try {
            const html = Config.tts_config_panel();
            Modal.show('TTS 打断与流式开关', html, async () => {
                try {
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering tts config panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    bindTabs() {
        const tabs = document.querySelectorAll('.modal-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const target = tab.dataset.tab;
                document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const content = document.querySelector(`.tab-content[data-tab-content="${target}"]`);
                if (content) content.classList.add('active');
            });
        });
    },

    bindSplitFlagEditor() {
        const editor = document.querySelector('[data-split-flag-editor]');
        if (!editor) return;
        const hidden = editor.querySelector('input[data-path]');
        const tagsEl = editor.querySelector('.split-tags');
        const addInput = editor.querySelector('.split-add-input');
        if (!hidden || !tagsEl || !addInput) return;

        const sync = () => {
            const chars = [];
            tagsEl.querySelectorAll('.split-tag').forEach(t => {
                const c = t.dataset.char;
                if (c) chars.push(c);
            });
            hidden.value = chars.join('|');
        };

        tagsEl.addEventListener('click', (e) => {
            const btn = e.target.closest('.split-tag-remove');
            if (btn) {
                btn.closest('.split-tag').remove();
                sync();
            }
        });

        addInput.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            const c = addInput.value.trim();
            if (!c) return;
            // 去重
            if (tagsEl.querySelector(`[data-char="${c}"]`)) {
                addInput.value = '';
                return;
            }
            const tag = document.createElement('span');
            tag.className = 'split-tag';
            tag.dataset.char = c;
            tag.innerHTML = `${c}<button type="button" class="split-tag-remove">&times;</button>`;
            tagsEl.appendChild(tag);
            addInput.value = '';
            sync();
        });
    },

    bindWordTagEditor() {
        document.querySelectorAll('[data-word-tag-editor]').forEach(editor => {
            const hidden = editor.querySelector('input[data-path]');
            const tagsEl = editor.querySelector('.split-tags');
            const addInput = editor.querySelector('.split-add-input');
            if (!hidden || !tagsEl || !addInput) return;

            const sync = () => {
                const words = [];
                tagsEl.querySelectorAll('.split-tag').forEach(t => {
                    const w = t.dataset.word;
                    if (w != null && w !== '') words.push(w);
                });
                hidden.value = JSON.stringify(words);
            };

            tagsEl.addEventListener('click', (e) => {
                const btn = e.target.closest('.split-tag-remove');
                if (btn) {
                    btn.closest('.split-tag').remove();
                    sync();
                }
            });

            addInput.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter') return;
                e.preventDefault();
                const w = addInput.value.trim();
                if (!w) return;
                if (tagsEl.querySelector(`[data-word="${this._escAttr(w)}"]`)) {
                    addInput.value = '';
                    return;
                }
                const tag = document.createElement('span');
                tag.className = 'split-tag';
                tag.dataset.word = w;
                tag.innerHTML = `${this._esc(w)}<button type="button" class="split-tag-remove">&times;</button>`;
                tagsEl.appendChild(tag);
                addInput.value = '';
                sync();
            });
        });
    },

    bindTriggerMode() {
        document.querySelectorAll('select[data-trigger-mode]').forEach(sel => {
            const group = sel.dataset.triggerMode;
            const apply = () => {
                const mode = sel.value;
                document.querySelectorAll(`[data-mode-group="${group}"]`).forEach(g => {
                    const show = g.dataset.modeShow;
                    if (mode === 'both') {
                        g.style.display = '';
                    } else {
                        g.style.display = (show === mode) ? '' : 'none';
                    }
                });
            };
            sel.addEventListener('change', apply);
            apply();
        });
    },

    showToast(msg, isError) {
        const toast = document.getElementById('toast');
        toast.textContent = msg;
        toast.style.background = isError ? 'linear-gradient(145deg, #ff6b6b, #ee5a5a)' : 'linear-gradient(145deg, var(--pink-main), var(--pink-deep))';
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
    }
};

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, initializing App...');
    window.App = App;
    App.init();
});
