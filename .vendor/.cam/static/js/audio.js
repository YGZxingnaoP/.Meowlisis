export class Mic {
  constructor(bus, gate, opts) {
    this.bus = bus;
    this.gate = gate || null;
    // AI 说话时是否掐掉手机麦克风（音频回声消除足够好时可以关掉，避免"你说话被吞"）
    this.gateOn = !(opts && opts.gateOn === false);
    this.stream = null;
    this.ctx = null;
    this.node = null;
    this.source = null;
    this.gain = null;
    this.on = false;
    this.onError = null;
    this._holdUntil = 0;
    this._watch = 0;
    this._restarts = 0;
    this.held = 0;
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
    this._restarts = 0;
    this.bus.send({ t: 'acfg', rate: ctx.sampleRate, ch: 1 });
    this._watch = setInterval(() => this._check(), 2000);
  }

  /** 看门狗：iOS 来电/Siri/切后台会让音频上下文挂起或轨道结束，自动救回来 */
  async _check() {
    if (!this.on) return;
    try {
      if (this.ctx && this.ctx.state === 'suspended') {
        await this.ctx.resume();
      }
    } catch (e) {}
    const track = this.stream ? this.stream.getAudioTracks()[0] : null;
    if (!track || track.readyState === 'ended') {
      if (this._restarts >= 5) return;
      this._restarts += 1;
      if (this.onError) {
        try {
          this.onError(new Error('麦克风中断，正在自动恢复(' + this._restarts + ')'));
        } catch (e) {}
      }
      try {
        await this.stop();
        await this.start();
      } catch (e) {}
    }
  }

  async stop() {
    if (!this.on && !this.stream) return;
    this.on = false;
    if (this._watch) {
      clearInterval(this._watch);
      this._watch = 0;
    }
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
    if (this.gateOn && this.gate && this.gate()) this._holdUntil = now + 150;
    if (now < this._holdUntil) {
      this.held += 1;
      return;
    }
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
