/**
 * 配置面板生成器 - plugins 模块
 * 插件独立配置（plugins/<id>/config.yml）：每插件一张卡，点开为子卡
 */
Object.assign(Config, {
    pluginSchemas: {},
    pluginConfigs: {},
    _spriteStamp: 0,

    async loadPluginSchemas() {
        try {
            const list = await API.getPlugins();
            (list || []).forEach(p => { this.pluginSchemas[p.id] = p; });
            return list || [];
        } catch (e) {
            console.error('load plugins failed', e);
            return [];
        }
    },

    async preloadPluginConfig(id) {
        const cfg = await API.getPluginConfig(id);
        this.pluginConfigs[id] = cfg || {};
        return this.pluginConfigs[id];
    },

    pluginPanel(id) {
        const schema = this.pluginSchemas[id];
        if (!schema) return '<div class="help-text">插件信息加载失败</div>';
        const fields = schema.fields || [];
        const backup = this.cfg;
        this._pluginCurrentId = id;
        this._spriteStamp = Date.now();   // 每次打开面板换一次缓存版本，面板内重绘不会重复请求
        this.cfg = this.pluginConfigs[id] || {};
        try {
            let html = this._section(schema.title || id);
            html += fields.map(f => this._pluginField(f)).join('');
            html += '<div class="help-text">插件配置保存在 plugins/' + id + '/config.yml，保存后需重启主程序生效</div>';
            return html;
        } finally {
            this.cfg = backup;
        }
    },

    _pluginField(f) {
        const path = f.key;
        const def = f.default;
        const label = f.label || f.key;
        const help = f.help || '';
        const type = f.type || 'text';
        // 插件配置是独立文件（plugins/<id>/config.yml），不走「API 平台」去重。
        // 文本/密码字段直接用 credentials.js 提供的"直接拼 HTML"，绕开凭据隐藏规则。
        if ((type === 'password' || type === 'text') && this._rawField) {
            const v = this._val(path, def);
            return this._rawField(label, path, v == null ? '' : v, type === 'password', help);
        }
        if (type === 'check') return this._check(label, path, def, help);
        if (type === 'num') return this._num(label, path, def, f.min, f.max, f.step, help);
        if (type === 'select') return this._select(label, path, f.options || [], def, help);
        if (type === 'tags') return this._wordTagEditor(label, path, def, help, f.placeholder || '输入后回车添加');
        if (type === 'list') return this._list(label, path, def, help);
        if (type === 'loras') return this._loraRows(label, path, def, help);
        if (type === 'area') return this._area(label, path, def, help);
        if (type === 'image') return this._pluginImage(label, path, def, help);
        if (type === 'action') return this._pluginAction(label, f, help);
        const rawText = this._baseText || this._text;
        const rawPassword = this._basePassword || this._password;
        if (type === 'password') return rawPassword.call(this, label, path, def, help);
        return rawText.call(this, label, path, def, help);
    },

    // ---------- 皮肤：图片上传 + 预览 ----------
    _pluginAssetUrl(rel, stamp) {
        const id = encodeURIComponent(this._pluginCurrentId || '');
        const path = encodeURIComponent(rel);
        return `/api/plugins/${id}/asset?path=${path}${stamp ? '&t=' + Date.now() : ''}`;
    },

    _pluginImage(label, path, def, help, asset) {
        const key = String(asset || 'farmer_base');
        const url = `/api/plugins/${encodeURIComponent(this._pluginCurrentId || '')}/sprite?asset=${encodeURIComponent(key)}&v=${this._spriteStamp}`;
        return `<div class="form-group skin-field">
            <label>${this._t(label)}</label>
            <div class="skin-preview"><img id="sprite_preview_${key}" src="${url}" alt="${key}"
                 data-sprite="${key}" loading="lazy" decoding="async"
                 onerror="this.style.display='none'"></div>
            <div class="skin-actions">
                <input type="file" id="sprite_file_${key}" accept="image/png"
                       onchange="Config._uploadSprite('${key}', this)">
                <button type="button" class="skin-btn" onclick="Config._triggerSkinAction('export_sprites', this)">
                    ${this._t('导出原版底稿')}</button>
            </div>
            ${help ? `<div class="help-text">${this._t(help)}</div>` : ''}</div>`;
    },

    _pluginAction(label, field, help) {
        const action = field.action || 'export_sprites';
        return `<div class="form-group skin-field">
            <label>${this._t(label)}</label>
            <div class="skin-actions">
                <button type="button" class="skin-btn primary" onclick="Config._triggerSkinAction('${action}', this)">
                    ${this._t(label)}</button>
            </div>
            <pre class="skin-log" data-skin-log></pre>
            ${help ? `<div class="help-text">${this._t(help)}</div>` : ''}</div>`;
    },

    _skinLog(button, text) {
        try {
            const box = button.closest('.skin-field').querySelector('[data-skin-log]');
            if (box) box.textContent = text;
        } catch (e) { /* ignore */ }
    },

    async _uploadSprite(asset, inputEl) {
        const file = inputEl && inputEl.files && inputEl.files[0];
        if (!file) return;
        const id = this._pluginCurrentId || '';
        try {
            const res = await fetch(`/api/plugins/${encodeURIComponent(id)}/sprite?asset=${encodeURIComponent(asset)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'image/png' },
                body: file,
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.ok !== true) throw new Error(data.reason || data.message || ('HTTP ' + res.status));
            this._spriteStamp += 1;
            this._refreshSpritePreviews();
            this._skinLog(inputEl, this._t('已保存') + `：${asset}.png（${Math.round(file.size / 1024)} KB）`);
        } catch (err) {
            this._skinLog(inputEl, this._t('上传失败') + '：' + err.message);
        }
    },

    _refreshSpritePreviews() {
        const id = this._pluginCurrentId || '';
        document.querySelectorAll('img[data-sprite]').forEach(img => {
            const key = img.getAttribute('data-sprite');
            img.style.display = '';
            img.src = `/api/plugins/${id}/sprite?asset=${encodeURIComponent(key)}&v=${this._spriteStamp}`;
        });
    },

    async _triggerSkinAction(action, button) {
        const id = this._pluginCurrentId || '';
        this._skinLog(button, this._t('执行中') + '……');
        try {
            const res = await fetch(`/api/plugins/${encodeURIComponent(id)}/action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action, slug: this._val('skin.active', 'default') || 'default' }),
            });
            const data = await res.json().catch(() => ({}));
            this._skinLog(button, (data.log || data.message || JSON.stringify(data)).slice(0, 4000));
        } catch (err) {
            this._skinLog(button, this._t('失败') + '：' + err.message);
        }
    },

    // ---------- LoRA 列表编辑器（插件用；与绘画卡同款，但独立实现） ----------
    _loraRows(label, path, def, help) {
        let list = this._val(path, def);
        if (typeof list === 'string') {
            try { list = JSON.parse(list); } catch (e) { list = []; }
        }
        if (!Array.isArray(list)) list = [];
        const esc = (t) => String(t == null ? '' : t)
            .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const rows = list.map(x => this._loraRow(x)).join('');
        return `<div class="form-group"><label>${this._t(label)}</label>
            <div class="kv-editor" id="plugin-lora-box"
                 oninput="Config.loraSync('${path}')" onchange="Config.loraSync('${path}')">${rows}</div>
            <button type="button" class="btn btn-secondary"
                onclick="Config.loraAdd('${path}')">${this._t('添加 LoRA')}</button>
            <input type="hidden" data-path="${path}" data-loras="1" id="plugin-lora-value"
                   value="${esc(JSON.stringify(list))}">
            ${help ? `<div class="help-text">${this._t(help)}</div>` : ''}</div>`;
    },

    _loraRow(item) {
        item = item || { name: '', strength: 0.8, enabled: true, trigger: '' };
        const esc = (t) => String(t == null ? '' : t)
            .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return `<div class="kv-lora-row" style="display:flex;align-items:center;gap:6px;margin:4px 0;">
            <input type="checkbox" data-lora-enabled title="${this._t('启用')}" style="flex:none;"
                ${item.enabled !== false ? 'checked' : ''}>
            <input type="text" data-lora-name value="${esc(item.name)}"
                placeholder="${this._t('lora 文件名')}" style="flex:1;min-width:0;">
            <input type="number" data-lora-strength value="${Number(item.strength) || 0}"
                min="-5" max="2" step="0.05" title="${this._t('权重')}" style="flex:none;width:84px;">
            <input type="text" data-lora-trigger value="${esc(item.trigger)}"
                placeholder="${this._t('触发词')}" title="${this._t('触发词')}"
                style="flex:none;width:100px;">
            <button type="button" class="kv-remove" title="${this._t('删除')}"
                onclick="Config.loraRemove(this)">&times;</button>
        </div>`;
    },

    loraCollect() {
        const box = document.getElementById('plugin-lora-box');
        const out = [];
        if (!box) return out;
        box.querySelectorAll('.kv-lora-row').forEach(row => {
            const nameEl = row.querySelector('[data-lora-name]');
            const name = ((nameEl && nameEl.value) || '').trim();
            if (!name) return;
            const sEl = row.querySelector('[data-lora-strength]');
            const strength = parseFloat(sEl && sEl.value);
            const tEl = row.querySelector('[data-lora-trigger]');
            out.push({
                name,
                strength: isNaN(strength) ? 0.8 : strength,
                enabled: row.querySelector('[data-lora-enabled]').checked,
                trigger: ((tEl && tEl.value) || '').trim(),
            });
        });
        return out;
    },

    loraSync(path) {
        const hid = document.getElementById('plugin-lora-value');
        if (hid) hid.value = JSON.stringify(this.loraCollect());
    },

    loraAdd(path) {
        const box = document.getElementById('plugin-lora-box');
        if (box) box.insertAdjacentHTML('beforeend', this._loraRow(null));
        this.loraSync(path);
    },

    loraRemove(btn) {
        const row = btn.closest('.kv-lora-row');
        if (row) row.remove();
        this.loraSync();
    },

    applyPluginUpdates(id, updates) {
        const schema = this.pluginSchemas[id] || {};
        const tagPaths = new Set((schema.fields || [])
            .filter(f => (f.type || '') === 'tags')
            .map(f => String(f.key)));
        const loraPaths = new Set((schema.fields || [])
            .filter(f => (f.type || '') === 'loras')
            .map(f => String(f.key)));
        const fixed = (updates || []).map(item => {
            const path = String(item.path);
            if (loraPaths.has(path) && typeof item.value === 'string') {
                let value;
                try { value = JSON.parse(item.value); } catch (e) { value = []; }
                return { path: item.path, value: Array.isArray(value) ? value : [] };
            }
            if (!tagPaths.has(path) || typeof item.value !== 'string') return item;
            let value;
            try { value = JSON.parse(item.value); } catch (e) { value = []; }
            if (!Array.isArray(value)) value = [];
            return { path: item.path, value: value };
        });
        const cfg = this.pluginConfigs[id] || (this.pluginConfigs[id] = {});
        this.applyUpdates(fixed, cfg);
        return cfg;
    },
});
