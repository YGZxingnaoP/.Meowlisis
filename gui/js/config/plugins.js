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

    applyPluginUpdates(id, updates) {
        const schema = this.pluginSchemas[id] || {};
        const tagPaths = new Set((schema.fields || [])
            .filter(f => (f.type || '') === 'tags')
            .map(f => String(f.key)));
        const fixed = (updates || []).map(item => {
            if (!tagPaths.has(String(item.path)) || typeof item.value !== 'string') return item;
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
