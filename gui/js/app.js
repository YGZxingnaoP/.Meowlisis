/**
 * Main application entry point
 */
const App = {
    config: null,
    ttsConfig: null,

    async init() {
        Modal.init();
        Orbit.init();

        try {
            this.config = await API.getConfig();
            window._config = this.config;
            Config.setConfig(this.config);
        } catch (e) {
            this.showToast('加载配置失败: ' + e.message, true);
        }

        document.getElementById('centerLauncher').addEventListener('click', async () => {
            try {
                await API.startMain();
                this.showToast('主程序已启动！');
            } catch (e) {
                this.showToast('启动失败: ' + e.message, true);
            }
        });
    },

    onPlanetClick(id) {
        console.log('App.onPlanetClick received:', id);
        
        if (id === 'sovits') {
            Modal.show('SoVITS 配置', Sovits.renderPanel(), async () => {
                try {
                    await API.startSovits();
                    this.showToast('SoVITS 已启动');
                } catch (e) {
                    this.showToast('启动失败: ' + e.message, true);
                }
            });
            setTimeout(() => Sovits.bindEvents(), 0);
            return;
        }

        const panelMap = {
            'basic': { title: '基本设置', fn: () => Config.basic() },
            'llm': { title: 'LLM 设置', fn: () => Config.llm() },
            'memory': { title: '记忆设置', fn: () => Config.memory() },
            'visionSetting': { title: '视觉设置', fn: () => Config.vision() },
            'search': { title: '搜索设置', fn: () => Config.search() },
            'response': { title: '响应设置', fn: () => Config.response() },
            'obs': { title: 'OBS 设置', fn: () => Config.obs() },
            'vtuber': { title: 'VTuber 设置', fn: () => Config.vtuber() },
            'sensevoice': { title: 'SenseVoice 设置', fn: () => Config.sensevoice() },
            'agent': { title: 'Agent 设置', fn: () => Config.agent() },
            'minecraft': { title: 'Minecraft 设置', fn: () => Config.minecraft() },
            'character': { title: '角色卡管理', fn: () => Config.character() },
            'sing': { title: '唱歌模块', fn: () => Config.sing() },
            'tts': { title: 'TTS 设置', fn: () => Config.tts() }
        };

        const panel = panelMap[id];
        if (!panel) {
            console.warn('No panel found for id:', id);
            return;
        }

        try {
            const html = panel.fn();
            Modal.show(panel.title, html, async () => {
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

        setTimeout(() => this.bindTabs(), 10);
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
    window.App = App;  // 立即挂载到 window
    App.init();
});
