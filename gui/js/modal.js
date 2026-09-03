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

    show(title, contentHtml, onSaveCallback) {
        this.title.textContent = (typeof I18n !== 'undefined' && I18n.text) ? I18n.text(title) : title;
        this.body.innerHTML = contentHtml;
        this.onSave = onSaveCallback;
        this.overlay.classList.add('show');
        document.body.style.overflow = 'hidden';
        this.initAutoGrow();
    },

    hide() {
        this.overlay.classList.remove('show');
        document.body.style.overflow = '';
        this.onSave = null;
    },

    getBody() {
        return this.body;
    }
};
