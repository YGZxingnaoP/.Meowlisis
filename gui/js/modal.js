/**
 * Modal window logic
 */
const Modal = {
    overlay: null,
    window: null,
    title: null,
    body: null,
    saveBtn: null,
    cancelBtn: null,
    closeBtn: null,
    onSave: null,
    /** 本次面板的来源卡片（Orbit 点击时写入），用于"从卡片位置放大" */
    source: null,

    init() {
        this.overlay = document.getElementById('modalOverlay');
        this.window = document.getElementById('modalWindow');
        this.title = document.getElementById('modalTitle');
        this.body = document.getElementById('modalBody');
        this.saveBtn = document.getElementById('modalSave');
        this.cancelBtn = document.getElementById('modalCancel');
        this.closeBtn = document.getElementById('modalClose');

        this.closeBtn.addEventListener('click', () => this.hide());
        this.cancelBtn.addEventListener('click', () => this.hide());
        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay) this.hide();
        });
        this.saveBtn.addEventListener('click', () => {
            if (this.onSave) this.onSave();
        });

        this.body.addEventListener('input', (e) => {
            if (e.target && e.target.classList && e.target.classList.contains('auto-grow')) {
                this.autoGrow(e.target);
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.hide();
        });
    },

    autoGrow(el) {
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = (el.scrollHeight + 2) + 'px';
    },

    initAutoGrow(scope) {
        (scope || this.body).querySelectorAll('.auto-grow').forEach(el => this.autoGrow(el));
    },

    show(title, contentHtml, onSaveCallback, fromEl) {
        this.title.textContent = (typeof I18n !== 'undefined' && I18n.text) ? I18n.text(title) : title;
        this.body.innerHTML = contentHtml;
        this.onSave = onSaveCallback;

        // 入场起点：显式传入的优先，其次用 Orbit 写入的最近点击卡片
        this._applyOrigin(fromEl || this.source);
        void this.window.offsetWidth;   // 强制重排，让起点先生效，再加 .show 触发过渡

        this.overlay.classList.add('show');
        document.body.style.overflow = 'hidden';
        document.body.classList.add('modal-open');   // 背景虚化压暗（css/modal.css）
        this.initAutoGrow();
    },

    /**
     * 把入场起点设到来源卡片的位置：CSS 用 --ox/--oy/--os 驱动
     * .modal-window 的 transform，变更变量即可让过渡自动从卡片长到中央。
     */
    _applyOrigin(src) {
        const win = this.window;
        const reset = () => {
            win.style.removeProperty('--ox');
            win.style.removeProperty('--oy');
            win.style.removeProperty('--os');
            win.style.removeProperty('--theme-a');
            win.style.removeProperty('--theme-b');
            win.classList.remove('from-card');
        };
        if (!src || typeof src.getBoundingClientRect !== 'function') { reset(); return; }

        const r = src.getBoundingClientRect();
        // 用布局值取窗口中心（offset* 不含 transform），避免读到入场 transform 造成的偏移
        const wcx = win.offsetLeft + win.offsetWidth / 2;
        const wcy = win.offsetTop + win.offsetHeight / 2;
        if (!r.width || !r.height || !win.offsetWidth) { reset(); return; }

        win.style.setProperty('--ox', ((r.left + r.width / 2) - wcx).toFixed(1) + 'px');
        win.style.setProperty('--oy', ((r.top + r.height / 2) - wcy).toFixed(1) + 'px');
        win.style.setProperty('--os', '0.22');
        win.classList.add('from-card');

        // 头部按卡片主题着色
        const cardId = src.dataset ? src.dataset.card : null;
        const th = (cardId && window.Cards) ? Cards.theme(cardId) : null;
        if (th) {
            win.style.setProperty('--theme-a', th.a);
            win.style.setProperty('--theme-b', th.b);
        } else {
            win.style.removeProperty('--theme-a');
            win.style.removeProperty('--theme-b');
        }
    },

    hide() {
        // 关面板时把来源卡翻回正面（翻牌动画的收尾）
        const src = this.source;
        if (src && typeof src.querySelector === 'function') {
            const card = src.querySelector('.card');
            if (card) card.classList.remove('flipped');
        }
        this.overlay.classList.remove('show');
        document.body.style.overflow = '';
        document.body.classList.remove('modal-open');
        document.body.classList.remove('modal-blank');
        this.onSave = null;
        this.source = null;   // 下次从中心弹出（--ox/--oy 保留，用于缩回卡片）
    },

    getBody() {
        return this.body;
    }
};
