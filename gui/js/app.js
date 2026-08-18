/**
 * Main application entry point
 */
const App = {
    config: null,

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
    },

    // ============ 服务启动球 ============
    async onLaunchClick(id) {
        const map = {
            sensevoice: { fn: () => API.startSensevoice(), name: 'SenseVoice' },
            sovits: { fn: () => API.startSovits(), name: 'SoVITS' },
            main: { fn: () => API.startMain(), name: '主程序' }
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
        if (id === 'llm') { await this.openLlmPanel(); return; }

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

        const panelMap = {
            'basic': { title: '基本设置', fn: () => Config.basic() },
            'danmaku': { title: '弹幕设置', fn: () => Config.danmaku() },
            'vtuber': { title: 'VTuber 设置', fn: () => Config.vtuber() },
            'minecraft': { title: 'Minecraft 设置', fn: () => Config.minecraft() },
            'obs': { title: 'OBS 设置', fn: () => Config.obs() }
        };

        const panel = panelMap[id];
        if (!panel) {
            console.warn('No panel found for id:', id);
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
        }, 10);
    },

    // ============ LLM 面板（含前置词） ============
    async openLlmPanel() {
        try {
            // 先获取前置词，渲染时直接内联到 textarea，避免异步填充时序问题
            let frontPrompt = '';
            try {
                const front = await API.getFrontPrompt();
                frontPrompt = front.prompt || '';
            } catch (e) {
                console.warn('加载前置词失败:', e);
            }

            const html = Config.llm(frontPrompt);
            Modal.show('LLM 设置', html, async () => {
                try {
                    // 1. 保存 config.yml 的 llm 节点
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);

                    // 2. 保存前置词
                    const frontEl = document.getElementById('frontPromptInput');
                    if (frontEl) {
                        await API.saveFrontPrompt({ prompt: frontEl.value });
                    }

                    this.showToast('LLM 配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });

            setTimeout(() => {
                this.bindTabs();
                this.bindSplitFlagEditor();
            }, 10);
        } catch (e) {
            console.error('Error rendering llm panel:', e);
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
                try {
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });

            await this.loadSpeakers();
            this.bindSpeakerEvents();
        } catch (e) {
            console.error('Error rendering sensevoice panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
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
