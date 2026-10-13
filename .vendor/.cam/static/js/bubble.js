export class Bubble {
  constructor(el) {
    this.el = el;
    this.rect = null;
    this._hideTimer = null;
  }

  setPetRect(rect) {
    this.rect = rect;
    if (!this.el.classList.contains('hidden')) this._place();
  }

  show(text, who) {
    if (!text) return;
    this.el.textContent = String(text);
    this.el.className = 'bubble ' + (who === 'user' ? 'user' : 'ai');
    this._place();
    if (this._hideTimer) clearTimeout(this._hideTimer);
    this._hideTimer = setTimeout(() => this.hide(), 12000);
  }

  hide() {
    this.el.classList.add('hidden');
  }

  _place() {
    const r = this.rect;
    const vh = window.innerHeight;
    let top = vh * 0.42;
    if (r && r.w > 0) top = r.y - 8;
    top = Math.max(72, Math.min(vh - 120, top));
    const el = this.el;
    // 内联写死整屏几何：即便缓存了旧样式表，也不会被 max-width/left 影响
    el.style.left = '0px';
    el.style.right = '0px';
    el.style.width = 'auto';
    el.style.maxWidth = 'none';
    el.style.transform = 'translateY(-100%)';
    el.style.top = top + 'px';
    el.classList.remove('hidden');
  }
}
