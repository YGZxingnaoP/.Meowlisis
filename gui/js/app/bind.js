/**
 * 应用控制器 - bind 模块
 * 由 app.js 拆分而来，统一挂载到全局 App 对象
 */

Object.assign(App, {
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

    // ============ VTS 参数查询 ============,
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
});
