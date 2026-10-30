/**
 * 通用字段渲染器
 *
 * 面板只用声明 fields，不再手写 HTML。复杂控件通过 type:'custom' 挂 widget。
 * 字段对象：
 *   { type:'number', path:'a.b', label, default, min, max, step, help }
 *   { type:'text'|'password'|'check'|'select'|'area'|'list', ... }
 *   { type:'section', label }
 *   { type:'fold', label, fields:[...], open:true }
 *   { type:'tabs', tabs:[{id,label,fields:[...]}] }
 *   { type:'custom', render:() => html }
 */
(function () {
    const ConfigForm = {
        render(panel) {
            this._panel = panel || null;
            return this.renderFields((panel && panel.fields) || []);
        },

        renderFields(fields) {
            if (!Array.isArray(fields)) return '';
            return fields.map(f => this.renderField(f)).join('');
        },

        renderField(f) {
            if (!f) return '';
            const type = f.type || 'text';
            if (type === 'section') return Config._section(f.label);
            if (type === 'fold') {
                return Config._fold(f.label, this.renderFields(f.fields), f.open);
            }
            if (type === 'tabs') {
                const tabs = f.tabs || [];
                const activeId = typeof f.active === 'function'
                    ? String(f.active(this._panel || {}, Config) || '')
                    : String(f.active || '');
                const isActive = (t, i) => activeId ? t.id === activeId : i === 0;
                const buttons = tabs.map((t, i) =>
                    '<button type="button" class="modal-tab' + (isActive(t, i) ? ' active' : '') +
                    '" data-tab="' + U.escAttr(f.id + '_' + t.id) + '">' +
                    Config._t(t.label) + '</button>').join('');
                const contents = tabs.map((t, i) =>
                    '<div class="tab-content' + (isActive(t, i) ? ' active' : '') +
                    '" data-tab-content="' + U.escAttr(f.id + '_' + t.id) + '">' +
                    this.renderFields(t.fields) + '</div>').join('');
                return '<div class="modal-tabs">' + buttons + '</div>' + contents;
            }
            if (type === 'custom') {
                return typeof f.render === 'function'
                    ? f.render(this._panel || {}, this)
                    : (f.html || '');
            }
            const path = f.path;
            if (!path) return '';
            const label = f.label || path;
            const def = f.default;
            const help = f.help || '';
            if (type === 'number' || type === 'num') {
                return Config._num(label, path, def, f.min, f.max, f.step, help);
            }
            if (type === 'check' || type === 'checkbox') {
                return Config._check(label, path, def, help);
            }
            if (type === 'select') {
                return Config._select(label, path, f.options || [], def, help, f.extraAttr);
            }
            if (type === 'password') {
                return Config._password(label, path, def, help);
            }
            if (type === 'area' || type === 'textarea') {
                return Config._area(label, path, def, help);
            }
            if (type === 'list') {
                return Config._list(label, path, def, help);
            }
            return Config._text(label, path, def, help);
        },
    };

    window.ConfigForm = ConfigForm;
})();
