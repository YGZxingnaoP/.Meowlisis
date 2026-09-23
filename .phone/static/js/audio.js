export class Mic {
  constructor(bus, gate) {
    this.bus = bus;
    this.gate = gate || null;
    this.stream = null;
    this.ctx = null;
    this.node = null;
    this.source = null;
    this.gain = null;
    this.on = false;
    this.onError = null;
    this._holdUntil = 0;
  }

  async start() {
    if (this.on) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('当前浏览器不支持麦克风');
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error('当前浏览器不支持 AudioContext');
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    });
    const ctx = new AC();
    if (ctx.state === 'suspended') {
      try {
        await ctx.resume();
      } catch (e) {}
    }
    await ctx.audioWorklet.addModule('/static/js/pcm-worklet.js');
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, 'pcm-capture');
    node.port.onmessage = (ev) => this._onPcm(ev.data);
    const gain = ctx.createGain();
    gain.gain.value = 0;
    source.connect(node);
    node.connect(gain);
    gain.connect(ctx.destination);
    this.stream = stream;
    this.ctx = ctx;
    this.node = node;
    this.source = source;
    this.gain = gain;
    this.on = true;
    this.bus.send({ t: 'acfg', rate: ctx.sampleRate, ch: 1 });
  }

  async stop() {
    if (!this.on && !this.stream) return;
    this.on = false;
    if (this.node) {
      try {
        this.node.port.onmessage = null;
      } catch (e) {}
      try {
        this.node.disconnect();
      } catch (e) {}
    }
    if (this.source) {
      try {
        this.source.disconnect();
      } catch (e) {}
    }
    if (this.gain) {
      try {
        this.gain.disconnect();
      } catch (e) {}
    }
    if (this.stream) {
      this.stream.getTracks().forEach((t) => {
        try {
          t.stop();
        } catch (e) {}
      });
    }
    if (this.ctx) {
      try {
        await this.ctx.close();
      } catch (e) {}
    }
    this.stream = null;
    this.ctx = null;
    this.node = null;
    this.source = null;
    this.gain = null;
  }

  _onPcm(f32) {
    const now = performance.now();
    if (this.gate && this.gate()) this._holdUntil = now + 150;
    if (now < this._holdUntil) return;
    const n = f32.length;
    const pcm = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    const out = new Uint8Array(1 + pcm.byteLength);
    out[0] = 0x02;
    out.set(new Uint8Array(pcm.buffer), 1);
    this.bus.sendBin(out.buffer);
  }
}
