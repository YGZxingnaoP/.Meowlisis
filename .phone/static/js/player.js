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
    this._firstBatch = true;
    this.volume = 1;
    this.gain = null;
    this._timer = null;
    this._idleSrc = null;
    this._keep = null;
    this._lastTrace = '';
  }

  /** 0~1：调 WebAudio 增益（在 MediaStreamDestination 之前，改的是进流的 PCM，iOS 拦不住），
   *  同时设 <audio>.muted（iOS 唯一一定认的静音开关）和 .volume（桌面/安卓） */
  setVolume(v) {
    const n = Number(v);
    this.volume = Math.max(0, Math.min(1, isNaN(n) ? 1 : n));
    this._applyGain();
    this._applyAudio();
    return this.volume;
  }

  _applyAudio() {
    if (!this.audio) return;
    try {
      this.audio.volume = this.volume;
      this.audio.muted = this.volume <= 0.001;
    } catch (e) {}
  }

  unlock() {
    if (this.on) return true;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    try {
      if (!this.ctx) this.ctx = new AC();
      if (!this.dest) this.dest = this.ctx.createMediaStreamDestination();
      this._out();
      if (!this.audio) this.audio = document.getElementById('phoneAudio');
      if (!this.audio) {
        this.audio = new Audio();
        this.audio.setAttribute('playsinline', '');
        document.body.appendChild(this.audio);
      }
      try {
        this.audio.volume = this.volume;
        this.audio.muted = this.volume <= 0.001;
      } catch (e) {}
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
    // 静音时不算"在播"：不要再压手机麦克风（否则静音后你说话会被丢掉）
    if (this.volume <= 0.001) return false;
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
      if (!this.on) {
        try {
          this.unlock();
        } catch (e) {}
      }
      if (this.ctx && this.ctx.state === 'suspended') {
        try {
          this.ctx.resume();
        } catch (e) {}
      }
      if (this.audio && this.audio.paused) {
        const p = this.audio.play();
        if (p && p.catch) p.catch(() => {});
      }
    }, 5000);
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
    try {
      if (d.filtered > 0 && d.mode === 'chat' && typeof this.onFiltered === 'function') {
        this.onFiltered(d.filtered);
      }
    } catch (e) {}
    try {
      if (meta.sample_rate) this._sr = Number(meta.sample_rate) || this._sr;
      if (meta.text && typeof this.onMeta === 'function') {
        const key = String(d.mid || 0) + '|' + String(meta.text);
        if (key !== this._lastTrace) {
          this._lastTrace = key;
          this.onMeta(meta);
        }
      }
    } catch (e) {}
    if (!blocks.length) return;
    if (this._firstBatch) {
      this._firstBatch = false;
      // 首次拿到数据：对齐到"最新位置"（只回退几块当缓冲），避免重放缓冲里的旧语音
      const newest = Math.max(0, Number(d.seq || 0) - 1);
      this._lastSeq = Math.max(-1, newest - 4);
    }
    for (const b of blocks) {
      if (b.seq > this._lastSeq) {
        this._lastSeq = b.seq;
        try {
          this._schedule(b.pcm);
        } catch (e) {}
      }
    }
  }

  _schedule(b64) {
    const ctx = this.ctx;
    if (!ctx || !this.dest || !b64) return;
    if (this.volume <= 0.001) return;   // 静音：完全不排音频（最硬的一道）
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
      src.connect(this._out());
      let t = this._nextStart;
      if (t < ctx.currentTime) t = ctx.currentTime + 0.02;
      src.start(t);
      this._nextStart = t + f32.length / sr;
    } catch (e) {}
  }

  /** 输出节点：iOS 上 MediaStream 型 <audio> 的 volume 属性无效，
   *  所以音量/静音必须做在 WebAudio 图里（buffer -> gain -> dest） */
  _out() {
    if (!this.ctx) return this.dest;
    if (!this.gain) {
      try {
        this.gain = this.ctx.createGain();
        this.gain.gain.value = this.volume;
        this.gain.connect(this.dest);
      } catch (e) {
        this.gain = null;
        return this.dest;
      }
    }
    this._applyGain();
    return this.gain;
  }

  _applyGain() {
    const g = this.gain;
    if (!g) return;
    try {
      const t = this.ctx ? this.ctx.currentTime : 0;
      if (g.gain.setValueAtTime) g.gain.setValueAtTime(this.volume, t);
      else g.gain.value = this.volume;
    } catch (e) {}
  }
}
