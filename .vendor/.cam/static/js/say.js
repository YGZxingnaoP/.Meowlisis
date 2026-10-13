export class Say {
  constructor(el, holdMs) {
    this.el = el;
    this.holdMs = holdMs || 6000;
    this._timer = null;
  }

  show(text) {
    const msg = String(text || '').trim();
    if (!this.el) return;
    if (!msg) return;
    this.el.textContent = msg;
    this.el.classList.remove('hidden');
    if (this._timer) clearTimeout(this._timer);
    this._timer = setTimeout(() => this.hide(), this.holdMs);
  }

  hide() {
    if (this._timer) clearTimeout(this._timer);
    this._timer = null;
    if (this.el) this.el.classList.add('hidden');
  }
}
