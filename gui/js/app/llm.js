/**
 * 应用控制器 - llm 模块
 * 由 app.js 拆分而来，统一挂载到全局 App 对象
 */

Object.assign(App, {
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

    // ============ 主动回复子球：浏览 ============,
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

    // ============ Toolbox 子视图 ============,
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

    // ============ 数据库来源站点编辑器 ============,
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
    async openRulesBreakPanel() {
        try {
            let armorData = {};
            try {
                armorData = await API.getArmorPrompt() || {};
            } catch (e) {
                console.warn('加载原则词失败:', e);
            }
            const html = Config.catbrain_rulesbreak(armorData);
            Modal.show('原则词配置', html, async () => {
                try {
                    // 原则词内容（独立 json）
                    const armor = {
                        prompt: document.getElementById('armorPromptInput')?.value || '',
                        prompt_napcat: document.getElementById('armorNapcatPromptInput')?.value || '',
                        nsfw_personality: document.getElementById('armorNsfwInput')?.value || '',
                        nsfw_hobby: document.getElementById('armorNsfwHobbyInput')?.value || '',
                        nsfw_favorite: document.getElementById('armorNsfwFavoriteInput')?.value || '',
                        nsfw_word_norm: document.getElementById('armorNsfwWordNormInput')?.value || ''
                    };
                    await API.saveArmorPrompt(armor);
                    // config.yml 的 rulebreak 节点（开关 + 好感度下限 + API）
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);
                    this.showToast('原则词配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering rulesbreak panel:', e);
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

    // ============ 角色卡面板 ============,
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

    // ============ 音频采集面板 ============,
});
