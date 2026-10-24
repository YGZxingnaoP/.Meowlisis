/**
 * 配置面板生成器 - plugins 模块
 * 插件独立配置（plugins/<id>/config.yml）：每插件一张卡，点开为子卡
 */
Object.assign(Config, {
    pluginSchemas: {},
    pluginConfigs: {},

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
        // 文本/密码字段直接用 api_platforms.js 提供的"直接拼 HTML"，绕开所有拦截层。
        if ((type === 'password' || type === 'text') && this._rawField) {
            const v = this._val(path, def);
            return this._rawField(label, path, v == null ? '' : v, type === 'password', help);
        }
        if (type === 'check') return this._check(label, path, def, help);
        if (type === 'num') return this._num(label, path, def, f.min, f.max, f.step, help);
        if (type === 'select') return this._select(label, path, f.options || [], def, help);
        if (type === 'list') return this._list(label, path, def, help);
        if (type === 'area') return this._area(label, path, def, help);
        const rawText = this._baseText || this._text;
        const rawPassword = this._basePassword || this._password;
        if (type === 'password') return rawPassword.call(this, label, path, def, help);
        return rawText.call(this, label, path, def, help);
    },

    applyPluginUpdates(id, updates) {
        const cfg = this.pluginConfigs[id] || (this.pluginConfigs[id] = {});
        this.applyUpdates(updates, cfg);
        return cfg;
    },
});
