/**
 * 应用控制器 - audio 模块
 * 由 app.js 拆分而来，统一挂载到全局 App 对象
 */

Object.assign(App, {
    async openAudioPanel() {
        try {
            const html = Config.audio();
            Modal.show('音频采集设置', html, async () => {
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                try {
                    await API.saveAudioConfig(this.config.audio || {});
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering audio panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ 静默（闭麦）面板 ============,
    async openSilencePanel() {
        try {
            const html = Config.silence();
            Modal.show('静默（闭麦）设置', html, async () => {
                const updates = Config.collectValues();
                Config.applyUpdates(updates, this.config);
                try {
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
            setTimeout(() => {
                this.bindWordTagEditor();
            }, 10);
        } catch (e) {
            console.error('Error rendering silence panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ SenseVoice 面板（含声纹管理） ============,
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

    // ============ TTS 面板（含参考音频 + 模型） ============,
});
