export class MonitorAudio {
  constructor() {
    this.ctx = null;
    this.on = false;
    this._next = 0;
    this._frames = 0;
    this.onLevel = null;
  }

  unlock() {
    if (this.on) return true;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    try {
      if (!this.ctx) this.ctx = new AC();
      if (this.ctx.state === 'suspended') this.ctx.resume();
      this._next = 0;
      this.on = true;
      return true;
    } catch (e) {
      return false;
    }
  }

  mute() {
    this.on = false;
  }

  toggle() {
    if (this.on) {
      this.mute();
      return false;
    }
    return this.unlock();
  }

  get locked() {
    return !this.on;
  }

  /** 0x03 帧：[0x03][rate u32 BE][s16le PCM] */
  feed(buf) {
    if (!this.on) return;
    const ctx = this.ctx;
    if (!ctx) return;
    if (ctx.state === 'suspended') {
      try {
        ctx.resume();
      } catch (e) {}
    }
    if (buf.byteLength < 7) return;
    const dv = new DataView(buf);
    const sr = dv.getUint32(1, false) || 16000;
    const n = (buf.byteLength - 5) >> 1;
    if (n <= 0) return;
    const bytes = new Uint8Array(buf, 5);
    let f32;
    try {
      f32 = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        let s = bytes[i * 2] | (bytes[i * 2 + 1] << 8);
        if (s > 32767) s -= 65536;
        f32[i] = s / 32768;
      }
    } catch (e) {
      return;
    }
    try {
      const b = ctx.createBuffer(1, n, sr);
      b.copyToChannel(f32, 0);
      const src = ctx.createBufferSource();
      src.buffer = b;
      src.connect(ctx.destination);
      let t = this._next;
      if (t < ctx.currentTime) t = ctx.currentTime + 0.02;
      src.start(t);
      this._next = t + n / sr;
      this._frames += 1;
      if (typeof this.onLevel === 'function' && (this._frames % 20) === 0) {
        this.onLevel(this._next - ctx.currentTime);
      }
    } catch (e) {}
  }
}
