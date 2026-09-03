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

