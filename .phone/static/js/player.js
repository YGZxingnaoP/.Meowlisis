export class Player {
  constructor() {
    this.ctx = null;
    this.dest = null;
    this.audio = null;
    this.on = false;
    this.onMeta = null;
    this.onStatus = null;
    this.onFiltered = null;
    this._sr = 32000;
    this._nextStart = 0;
    this._lastSeq = -1;
    this._inflight = false;
    this._timer = null;
    this._idleSrc = null;
    this._keep = null;
    this._lastTrace = '';
  }

  unlock() {
    if (this.on) return true;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    try {
      if (!this.ctx) this.ctx = new AC();
      if (!this.dest) this.dest = this.ctx.createMediaStreamDestination();
      if (!this.audio) this.audio = document.getElementById('phoneAudio');
      if (!this.audio) {
        this.audio = new Audio();
        this.audio.setAttribute('playsinline', '');
        document.body.appendChild(this.audio);
      }
      if (this.audio.srcObject !== this.dest.stream) this.audio.srcObject = this.dest.stream;
      const p = this.audio.play();
      if (p && p.catch) p.catch(() => {});
      if (this.ctx.state === 'suspended') this.ctx.resume();
      this._idle();
      this.on = true;
      this._keepAlive();
      if (this.onStatus) this.onStatus(true);
      return true;
    } catch (e) {
      return false;
    }
  }

  start() {
    if (this._timer) return;
    this._timer = setInterval(() => this._poll(), 150);
  }

  isPlaying() {
    if (!this.ctx || !this.dest) return false;
    return this._nextStart > this.ctx.currentTime + 0.02;
  }

  stop() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  _idle() {
    if (this._idleSrc || !this.ctx) return;
    try {
      const frames = Math.max(1, Math.floor(this.ctx.sampleRate * 0.25));
      const buf = this.ctx.createBuffer(1, frames, this.ctx.sampleRate);
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.loop = true;
      src.connect(this.dest);
      src.start(0);
      this._idleSrc = src;
    } catch (e) {}
  }

  _keepAlive() {
    if (this._keep) return;
    this._keep = setInterval(() => {
      if (this.ctx && this.ctx.state === 'suspended') {
        try {
          this.ctx.resume();
        } catch (e) {}
      }
      if (this.audio && this.audio.paused) {
        const p = this.audio.play();
        if (p && p.catch) p.catch(() => {});
      }
    }, 10000);
  }

  _poll() {
    if (this._inflight) return;
    this._inflight = true;
    fetch('/api/tts/pending?seq=' + this._lastSeq)
      .then((r) => r.json())
      .then((d) => this._handle(d))
      .catch(() => {})
      .finally(() => {
        this._inflight = false;
      });
  }

  _handle(d) {
    if (!d) return;
    const meta = d.meta || {};
    const blocks = d.blocks || [];
    if (d.filtered > 0 && d.mode === 'chat' && typeof this.onFiltered === 'function') {
      this.onFiltered(d.filtered);
    }
    if (meta.sample_rate) this._sr = Number(meta.sample_rate) || this._sr;
    if (meta.text && typeof this.onMeta === 'function') {
      const key = String(d.mid || 0) + '|' + String(meta.text);
      if (key !== this._lastTrace) {
        this._lastTrace = key;
        this.onMeta(meta);
      }
    }
    for (const b of blocks) {
      if (b.seq > this._lastSeq) {
        this._schedule(b.pcm);
        this._lastSeq = b.seq;
      }
    }
  }

  _schedule(b64) {
    const ctx = this.ctx;
    if (!ctx || !this.dest || !b64) return;
    if (ctx.state === 'suspended') {
      try {
        ctx.resume();
      } catch (e) {}
    }
    let f32;
    try {
      const bin = atob(b64);
      const n = bin.length >> 1;
      f32 = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        const lo = bin.charCodeAt(i * 2);
        const hi = bin.charCodeAt(i * 2 + 1);
        let s = lo | (hi << 8);
        if (s > 32767) s -= 65536;
        f32[i] = s / 32768;
      }
    } catch (e) {
      return;
    }
    const sr = this._sr || 32000;
    try {
      const buf = ctx.createBuffer(1, f32.length, sr);
      buf.copyToChannel(f32, 0);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.dest);
      let t = this._nextStart;
      if (t < ctx.currentTime) t = ctx.currentTime + 0.02;
      src.start(t);
      this._nextStart = t + f32.length / sr;
    } catch (e) {}
  }
}
