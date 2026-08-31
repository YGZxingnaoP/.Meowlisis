/**
 * 配置面板生成器 - core 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

const Config = {
    cfg: null,

    setConfig(c) { this.cfg = c; },
    _val(path, def) {
        const parts = path.split('.');
        let v = this.cfg;
        for (const p of parts) {
            v = v?.[p];
            if (v === undefined) return def;
        }
        return v;
    },
    _text(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <input type="text" data-path="${path}" value="${v == null ? '' : v}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _num(label, path, def, min, max, step, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <input type="number" data-path="${path}" value="${v == null ? '' : v}" min="${min}" max="${max}" step="${step}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _check(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><div class="checkbox-group">
            <input type="checkbox" data-path="${path}" ${v ? 'checked' : ''}>
            <label>${label}</label></div>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _select(label, path, options, def, help, extraAttr) {
        const v = this._val(path, def);
        const opts = options.map(o => `<option value="${o.value}" ${String(o.value) === String(v) ? 'selected' : ''}>${o.label}</option>`).join('');
        return `<div class="form-group"><label>${label}</label>
            <select data-path="${path}" ${extraAttr || ''}>${opts}</select>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _password(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <input type="password" data-path="${path}" value="${v == null ? '' : v}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _list(label, path, def, help) {
        const v = this._val(path, def) || [];
        const text = Array.isArray(v) ? v.join(', ') : v;
        return `<div class="form-group"><label>${label}</label>
            <input type="text" data-path="${path}" data-list="1" value="${text}">
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _area(label, path, def, help) {
        const v = this._val(path, def);
        return `<div class="form-group"><label>${label}</label>
            <textarea class="auto-grow" rows="3" data-path="${path}">${this._esc(v == null ? '' : v)}</textarea>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _wordTagEditor(label, path, def, help, placeholder) {
        const list = (this._val(path, def) || []).filter(x => x != null && String(x).trim());
        const tags = list.map(w =>
            `<span class="split-tag" data-word="${this._escAttr(w)}">${this._esc(w)}<button type="button" class="split-tag-remove">&times;</button></span>`
        ).join('');
        const json = JSON.stringify(list);
        return `<div class="form-group"><label>${label}</label>
            <div class="split-flag-editor" data-word-tag-editor="${path}">
                <div class="split-tags">${tags}</div>
                <div class="split-add-row">
                    <input type="text" class="split-add-input" placeholder="${placeholder || '输入后回车添加'}">
                </div>
                <input type="hidden" data-path="${path}" value='${this._escAttr(json)}'>
            </div>
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },

    // ============ 键值对（dict）可视化编辑器 ============,
    _dictHidden(path, obj) {
        const json = JSON.stringify(obj || {});
        const safe = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, '&#39;');
        return `<input type="hidden" data-path="${path}" value='${safe}'>`;
    },

    // 简单键值对编辑器（名 → QQ号），用于 group_bots,
    _kvDictEditor(label, path, help, keyLabel, valueLabel) {
        const obj = this._val(path, {}) || {};
        const rows = Object.keys(obj).map(k => this._kvRow(k, obj[k], keyLabel, valueLabel)).join('');
        return `<div class="form-group"><label>${label}</label>
            <div class="kv-editor" data-kv-editor="${path}" data-kv-key-label="${keyLabel}" data-kv-value-label="${valueLabel}">
                ${rows || '<div class="help-text">暂无条目，点击下方按钮添加</div>'}
            </div>
            <button type="button" class="btn btn-secondary" data-kv-add="${path}">添加条目</button>
            ${this._dictHidden(path, obj)}
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _kvRow(key, value, keyLabel, valueLabel) {
        return `<div class="kv-row">
            <input type="text" data-kv-key value="${this._esc(key || '')}" placeholder="${keyLabel}">
            <input type="text" data-kv-value value="${this._esc(value || '')}" placeholder="${valueLabel}">
            <button type="button" class="kv-remove" title="删除">&times;</button>
        </div>`;
    },

    // 每群配置编辑器（群号 → 触发基数 / pass 次数），用于 group_per_group,
    _groupConfigEditor(label, path, help) {
        const obj = this._val(path, {}) || {};
        const rows = Object.keys(obj).map(gid => this._groupConfigRow(gid, obj[gid])).join('');
        return `<div class="form-group"><label>${label}</label>
            <div class="kv-editor" data-gc-editor="${path}">
                ${rows || '<div class="help-text">暂无条目，点击下方按钮添加</div>'}
            </div>
            <button type="button" class="btn btn-secondary" data-gc-add="${path}">添加群配置</button>
            ${this._dictHidden(path, obj)}
            ${help ? `<div class="help-text">${help}</div>` : ''}</div>`;
    },
    _groupConfigRow(gid, cfg) {
        cfg = cfg || {};
        const base = cfg.reply_base != null ? cfg.reply_base : '';
        const pass = cfg.pass_rounds != null ? cfg.pass_rounds : '';
        return `<div class="kv-row kv-row-3">
            <input type="text" data-gc-group value="${this._esc(gid || '')}" placeholder="群号">
            <input type="number" data-gc-base value="${base}" placeholder="触发基数(默认6)">
            <input type="number" data-gc-pass value="${pass}" placeholder="pass次数(默认1)">
            <button type="button" class="kv-remove" title="删除">&times;</button>
        </div>`;
    },
    _section(title) {
        return `<div class="form-section"><h4>${title}</h4></div>`;
    },
    _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },
    _escAttr(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    // ============ 基本设置（根级 + app） ============,
    collectValues() {
        const inputs = document.querySelectorAll('#modalBody [data-path]');
        const updates = [];
        inputs.forEach(el => {
            const path = el.dataset.path;
            let value;
            if (el.type === 'checkbox') value = el.checked;
            else if (el.type === 'number') {
                // 情绪参数等「留空=不覆盖」的字段：空值跳过，避免写入 NaN/null
                if (el.value === '' || el.value == null) return;
                value = parseFloat(el.value);
            } else value = el.value;
            updates.push({ path, value });
        });
        return updates;
    },

    // 收集数据库来源站点（sites 编辑器）,
    collectSources() {
        const result = {};
        document.querySelectorAll('#sourceSiteList [data-source-site]').forEach(card => {
            const get = (field) => {
                const el = card.querySelector(`[data-source-field="${field}"]`);
                if (!el) return undefined;
                if (el.type === 'checkbox') return el.checked;
                if (el.type === 'number') return parseFloat(el.value);
                return el.value;
            };
            const key = (get('key') || '').trim();
            if (!key) return;
            result[key] = {
                label: get('label') || key,
                description: get('description') || '',
                enabled: get('enabled') !== false,
                strategy: get('strategy') || 'http',
                count: get('count') || 5,
                base_url: get('base_url') || '',
                search_url: get('search_url') || '',
                interval: get('interval') || 2,
            };
        });
        return result;
    },

    // 收集新结构角色卡（共用字段 + setting 字典 + personality 字典）,
    collectCharacterCard() {
        const obj = {};
        document.querySelectorAll('#modalBody [data-char-field]').forEach(el => {
            obj[el.dataset.charField] = el.value;
        });
        const setting = {};
        document.querySelectorAll('#settingList .dict-row').forEach(row => {
            const key = row.querySelector('[data-setting-key]').value.trim();
            const value = row.querySelector('[data-setting-value]').value;
            if (key) setting[key] = value;
        });
        obj.setting = setting;
        const personality = {};
        document.querySelectorAll('#personalityList .dict-row').forEach(row => {
            const key = row.querySelector('[data-personality-key]').value.trim();
            const value = row.querySelector('[data-personality-value]').value;
            if (key) personality[key] = value;
        });
        obj.personality = personality;
        return { characters: [obj] };
    },

    // 收集参考音频配置（支持多情绪三层结构：角色名 → 情绪 → 字段）,
    collectRefAudio() {
        const result = {};
        document.querySelectorAll('#refAudioPanel [data-ref-audio-name]').forEach(el => {
            const name = el.dataset.refAudioName;
            const emotion = el.dataset.refAudioEmotion;
            const field = el.dataset.refAudioField;
            if (emotion) {
                // 多情绪格式
                if (!result[name]) result[name] = {};
                if (!result[name][emotion]) result[name][emotion] = {};
                result[name][emotion][field] = el.value;
            } else {
                // 旧单条格式
                if (!result[name]) result[name] = {};
                result[name][field] = el.value;
            }
        });
        return result;
    },

    // 收集 TTS 模型配置（从当前 modal 面板收集 data-tts-model 字段）,
    collectTtsModel() {
        const result = { custom: {} };
        const customKeys = ['device', 'is_half', 't2s_weights_path', 'vits_weights_path', 'version'];
        document.querySelectorAll('#modalBody [data-tts-model]').forEach(el => {
            const key = el.dataset.ttsModel;
            let value;
            if (el.type === 'checkbox') value = el.checked;
            else if (el.type === 'number') value = parseFloat(el.value);
            else value = el.value;
            if (customKeys.includes(key)) {
                result.custom[key] = value;
            } else {
                result[key] = value;
            }
        });
        return result;
    },
    applyUpdates(updates, target) {
        for (const { path, value } of updates) {
            const parts = path.split('.');
            let current = target;
            for (let i = 0; i < parts.length - 1; i++) {
                const p = parts[i];
                const nextP = parts[i + 1];
                if (!(p in current)) {
                    current[p] = (!isNaN(parseInt(nextP)) && !isNaN(Number(nextP))) ? [] : {};
                }
                current = current[p];
            }
            const last = parts[parts.length - 1];
            // 列表类型字段：逗号/换行分隔后存为数组
            if (typeof value === 'string' && (
                path === 'app.mode' ||
                path === 'sensevoice.target_speakers' ||
                path === 'sensevoice.hotwords' ||
                path === 'minecraft.filter_players' ||
                path === 'napcat.group_blacklist' ||
                path === 'llm_active.web_browse.allow_topics'
            )) {
                current[last] = value.split(/[,，\n]/).map(s => s.trim()).filter(Boolean);
            } else if (typeof value === 'string' && (
                path === 'meowsinger.song.prefix' ||
                path === 'meowsinger.song.intent' ||
                path === 'meowsinger.cover.prefix' ||
                path === 'meowsinger.cover.intent' ||
                path === 'meowsinger.cover.learn_users' ||
                path === 'meowsinger.stop.keywords' ||
                path === 'silence.wake_phrases' ||
                path === 'silence.mute_phrases'
            )) {
                try { current[last] = JSON.parse(value); }
                catch (e) { current[last] = value.split(/\n/).map(s => s.trim()).filter(Boolean); }
            } else if (path === 'napcat.group_bots' || path === 'napcat.group_per_group') {
                // dict 编辑器：隐藏 input 存 JSON 字符串，这里解析回对象
                try { current[last] = JSON.parse(value); }
                catch (e) { current[last] = {}; }
            } else {
                current[last] = value;
            }
        }
    },
};


