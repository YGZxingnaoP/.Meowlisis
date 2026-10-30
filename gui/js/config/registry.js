/**
 * 配置面板注册表（配置界面的唯一入口）
 *
 * 一个面板只在这里声明一次：
 *   id / title / group / render 或 open
 * app/core、advanced、以及后续新增入口都通过 ConfigPanels.open(id) 打开。
 *
 * 复杂面板（CatPaws、TTS 参考音频、Flux 工作流等）用 open 挂现有异步面板；
 * 普通字段面板用 render 挂 Config.* 生成函数。两种都叫“面板”，不再散落 if/else。
 */
(function () {
    if (window.ConfigPanels) return;

    const GROUP_ORDER = ['基础', '语音', '大脑', '形象', '娱乐', '工具箱'];
    const panels = new Map();

    const ConfigPanels = {
        register(def) {
            if (!def || !def.id) throw new Error('ConfigPanels: panel.id required');
            if (!def.title) throw new Error('ConfigPanels: panel.title required for ' + def.id);
            if (!def.render && !def.open && !Array.isArray(def.fields)) {
                throw new Error('ConfigPanels: panel needs render(), open() or fields[] for ' + def.id);
            }
            def.group = def.group || '其他';
            def.order = Number(def.order || 0);
            panels.set(def.id, def);
            return def;
        },

        get(id) {
            return panels.get(id) || null;
        },

        has(id) {
            return panels.has(id);
        },

        all() {
            return Array.from(panels.values());
        },

        /** 打开面板：自定义 open 优先，其次用 App 的标准 Modal 流程 */
        async open(id) {
            const panel = panels.get(id);
            if (!panel) return false;
            if (typeof panel.load === 'function') {
                try {
                    panel.data = await panel.load(panel);
                } catch (e) {
                    console.error('[ConfigPanels] load failed:', id, e);
                    if (window.App && App.showToast) App.showToast('面板加载失败: ' + (e && e.message ? e.message : e), true);
                    return false;
                }
            }
            if (typeof panel.open === 'function') {
                await panel.open(panel);
                return true;
            }
            if (typeof panel.render === 'function') {
                if (!window.App || typeof App._openConfigPanel !== 'function') {
                    throw new Error('App._openConfigPanel unavailable');
                }
                App._openConfigPanel(panel.title, panel.render, panel.save);
                return true;
            }
            if (Array.isArray(panel.fields)) {
                if (!window.ConfigForm || typeof window.ConfigForm.render !== 'function') {
                    throw new Error('ConfigForm unavailable');
                }
                window.App._openConfigPanel(panel.title, () => window.ConfigForm.render(panel), panel.save);
                return true;
            }
            return false;
        },

        /** 高级设置侧栏：按 group 聚合；extra 用于插入 identity_users / raw_config 等非卡片项 */
        advancedGroups(extra) {
            const groups = new Map();
            GROUP_ORDER.forEach(g => groups.set(g, []));
            this.all()
                .forEach(p => {
                    if (p.advanced === false) return;
                    if (!groups.has(p.group)) groups.set(p.group, []);
                    groups.get(p.group).push({
                        id: p.id,
                        t: p.title,
                        kind: 'panel',
                        panel: p,
                    });
                });

            (extra || []).forEach(ex => {
                if (!groups.has(ex.group)) groups.set(ex.group, []);
                const arr = groups.get(ex.group);
                if (ex.prepend) arr.unshift.apply(arr, ex.prepend);
                if (ex.append) arr.push.apply(arr, ex.append);
            });

            const out = [];
            groups.forEach((items, title) => {
                if (items.length) out.push({ t: title, items: items });
            });
            return out;
        },
    };

    window.ConfigPanels = ConfigPanels;
})();
