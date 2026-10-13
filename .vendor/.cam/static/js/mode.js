const TEXT = {
  chat: '聊天模式 · 手机只听你自己的对话',
  call: '通话模式 · 手机听全部语音（含弹幕/视觉/主动回复）'
};

const LABEL = {
  chat: '聊天·仅我',
  call: '通话·全部'
};

export class Mode {
  constructor(el, toast) {
    this.el = el;
    this.toast = toast || null;
    this.mode = 'call';
    this.onChange = null;
    this._toastTimer = null;
    this._hintAt = 0;
  }

  load() {
    fetch('/api/mode')
      .then((r) => r.json())
      .then((d) => this._apply(d && d.mode, true))
      .catch(() => {});
  }

  hintFiltered(n) {
    const now = Date.now();
    if (now - this._hintAt < 8000) return;
    this._hintAt = now;
    this._say('已忽略 ' + n + ' 条电脑端语音 · 点顶部胶囊切「通话」就能听到');
  }

  toggle() {
    const next = this.mode === 'call' ? 'chat' : 'call';
    fetch('/api/mode?mode=' + next, { method: 'POST' })
      .then((r) => r.json())
      .then((d) => this._apply(d && d.mode, true))
      .catch(() => {});
  }

  _apply(mode, announce) {
    this.mode = mode === 'call' ? 'call' : 'chat';
    if (this.el) {
      this.el.textContent = LABEL[this.mode];
      this.el.classList.toggle('on', this.mode === 'call');
    }
    if (announce) this._say(TEXT[this.mode]);
    if (typeof this.onChange === 'function') this.onChange(this.mode);
  }

  _say(text) {
    if (!this.toast || !text) return;
    this.toast.textContent = text;
    this.toast.classList.remove('hidden');
    if (this._toastTimer) clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => this.toast.classList.add('hidden'), 2600);
  }
}
