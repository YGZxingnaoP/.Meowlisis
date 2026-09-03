/**
 * i18n 运行时（模块化、零依赖）
 * - 语言包由 locales/zh-CN.js 与 locales/en.js 定义在 window.__LOCALES__ 上（同步，无时序问题）；
 * - key = 代码/HTML 中出现的原文；当前语言词典查不到 → 回退显示原文（中文兜底），渐进改造零风险；
 * - 切换语言：右上角 #langSel 下拉 → 记忆到 localStorage(gui_lang) → 整页刷新重渲。
 */
const I18n = (() => {
    const LANG_KEY = 'gui_lang';
    const ZH = 'zh-CN';
    const EN = 'en';

    function dicts() {
        return (window.__LOCALES__) || {};
    }

    function current() {
        let saved = null;
        try { saved = localStorage.getItem(LANG_KEY); } catch (e) { /* ignore */ }
        if (saved === ZH || saved === EN) return saved;
        try {
            if (navigator.language && String(navigator.language).toLowerCase().startsWith('en')) return EN;
        } catch (e) { /* ignore */ }
        return ZH;
    }

    /** 取当前语言的译文；缺词条则返回原文（中文兜底） */
    function text(s, vars) {
        if (typeof s !== 'string' || !s) return s;
        const d = dicts()[current()] || {};
        let out = Object.prototype.hasOwnProperty.call(d, s) ? d[s] : s;
        if (vars) {
            for (const k in vars) {
                out = String(out).split('{' + k + '}').join(vars[k]);
            }
        }
        return out;
    }

    function applyStatic(root) {
        const scope = root || document;
        scope.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = text(el.dataset.i18n); });
        scope.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = text(el.dataset.i18nTitle); });
        scope.querySelectorAll('[data-i18n-alt]').forEach(el => { el.setAttribute('alt', text(el.dataset.i18nAlt)); });
    }

    function init() {
        const lang = current();
        document.documentElement.setAttribute('lang', lang);
        const metaTitle = text('喵呜配置管理器');
        if (document.title) document.title = metaTitle;
        applyStatic();

        // 右上角白色圆角按钮组切换语言
        const sw = document.getElementById('langSwitch');
        if (sw) {
            sw.querySelectorAll('button[data-lang]').forEach(btn => {
                const active = btn.dataset.lang === lang;
                btn.style.border = 'none';
                btn.style.borderRadius = '999px';
                btn.style.padding = '4px 12px';
                btn.style.fontSize = '12px';
                btn.style.cursor = 'pointer';
                btn.style.background = active ? '#ff6b9d' : 'transparent';
                btn.style.color = active ? '#fff' : '#333';
                if (!active) {
                    btn.addEventListener('click', () => {
                        try { localStorage.setItem(LANG_KEY, btn.dataset.lang); } catch (e) { /* ignore */ }
                        location.reload();
                    });
                }
            });
        }
        if (window.App && typeof window.App.onLangReady === 'function') {
            window.App.onLangReady(lang);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { text, current, init, applyStatic };
})();

window.I18n = I18n;
// 全局兜底：任何 this=window/普通函数 的渲染模板都能用 _t()（如 app/*.js 模板）
window._t = function (s, vars) { return I18n.text(s, vars); };
