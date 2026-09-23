import { MEDIA } from './config.js';

export class Camera {
  constructor(bus, video, view) {
    this.bus = bus;
    this.video = video;
    this.view = view || null;
    this.stream = null;
    this.encoder = null;
    this.on = false;
    this.facing = 'environment';
    this.onError = null;
    this._raf = 0;
    this._last = -1;
    this._lastKey = 0;
    this._forceKey = true;
    this._busy = false;
    this._canvas = null;
    this._cctx = null;
    this._w = MEDIA.videoWidth;
    this._h = MEDIA.videoHeight;
  }

  async start() {
    if (this.on) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('当前浏览器不支持摄像头');
    }
    if (typeof VideoEncoder === 'undefined') {
      throw new Error('当前浏览器不支持 WebCodecs H.264 编码');
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: this.facing },
        width: { ideal: MEDIA.videoWidth },
        height: { ideal: MEDIA.videoHeight },
        frameRate: { ideal: MEDIA.videoFps, max: MEDIA.videoFps }
      },
      audio: false
    });
    this.stream = stream;
    this.video.srcObject = stream;
    try {
      await this.video.play();
    } catch (e) {}
    await this._waitSize();
    const size = this._liveSize();
    this._w = size[0];
    this._h = size[1];
    this._resetCanvas();
    await this._setupEncoder(this._w, this._h);
    this.on = true;
    this._last = -1;
    this._lastKey = 0;
    this._forceKey = true;
    this._loop();
  }

  async stop() {
    if (!this.on && !this.stream) return;
    this.on = false;
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
    if (this.encoder) {
      try {
        this.encoder.close();
      } catch (e) {}
      this.encoder = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((t) => {
        try {
          t.stop();
        } catch (e) {}
      });
      this.stream = null;
    }
    this.video.srcObject = null;
    this._clearCanvas();
    this.bus.send({ t: 'vstop' });
  }

  async flip() {
    const next = this.facing === 'environment' ? 'user' : 'environment';
    if (this.on) {
      await this.stop();
      this.facing = next;
      await this.start();
    } else {
      this.facing = next;
    }
  }

  requestKeyframe() {
    this._forceKey = true;
  }

  _liveSize() {
    const track = this.stream ? this.stream.getVideoTracks()[0] : null;
    const st = (track && track.getSettings) ? track.getSettings() : {};
    const w = this.video.videoWidth || st.width || MEDIA.videoWidth;
    const h = this.video.videoHeight || st.height || MEDIA.videoHeight;
    return [this._even(w), this._even(h)];
  }

  _waitSize() {
    return new Promise((resolve) => {
      const done = () => {
        this.video.removeEventListener('loadedmetadata', done);
        this.video.removeEventListener('resize', done);
        resolve();
      };
      if (this.video.videoWidth > 0 && this.video.videoHeight > 0) {
        resolve();
        return;
      }
      this.video.addEventListener('loadedmetadata', done);
      this.video.addEventListener('resize', done);
      setTimeout(done, 1500);
    });
  }

  _sync() {
    if (this._busy || !this.on) return;
    const size = this._liveSize();
    if (size[0] === this._w && size[1] === this._h) return;
    this._busy = true;
    this._w = size[0];
    this._h = size[1];
    if (this.encoder) {
      try {
        this.encoder.close();
      } catch (e) {}
      this.encoder = null;
    }
    this._resetCanvas();
    this._setupEncoder(this._w, this._h).then(() => {
      this._forceKey = true;
      this._lastKey = 0;
    }).catch((e) => {
      if (this.onError) this.onError(e);
    }).finally(() => {
      this._busy = false;
    });
  }

  async _setupEncoder(w, h) {
    const base = {
      codec: MEDIA.h264Codec,
      width: w,
      height: h,
      bitrate: MEDIA.videoBitrate,
      framerate: MEDIA.videoFps,
      latencyMode: 'realtime'
    };
    const candidates = [
      Object.assign({}, base, { hardwareAcceleration: 'prefer-hardware', avc: { format: 'annexb' } }),
      Object.assign({}, base, { avc: { format: 'annexb' } }),
      Object.assign({}, base, { hardwareAcceleration: 'prefer-hardware' }),
      Object.assign({}, base)
    ];
    let chosen = null;
    for (const cand of candidates) {
      try {
        const res = await VideoEncoder.isConfigSupported(cand);
        if (res && res.supported) {
          chosen = cand;
          break;
        }
      } catch (e) {}
    }
    if (!chosen) throw new Error('设备不支持 H.264 (avc1.42E01E) 编码');
    this.encoder = new VideoEncoder({
      output: (chunk) => this._pushChunk(chunk),
      error: (e) => {
        if (this.onError) this.onError(e);
      }
    });
    this.encoder.configure(chosen);
    this.bus.send({ t: 'vcfg', codec: chosen.codec, w, h, fps: MEDIA.videoFps });
  }

  _pushChunk(chunk) {
    const size = chunk.byteLength;
    const buf = new Uint8Array(10 + size);
    buf[0] = 0x01;
    buf[1] = chunk.type === 'key' ? 1 : 0;
    const dv = new DataView(buf.buffer);
    dv.setBigUint64(2, BigInt(Math.round(chunk.timestamp)), false);
    try {
      chunk.copyTo(buf.subarray(10));
    } catch (e) {
      return;
    }
    this.bus.sendBin(buf.buffer);
  }

  _makeFrame(ts) {
    if (!this._cctx) this._resetCanvas();
    this._cctx.drawImage(this.video, 0, 0, this._w, this._h);
    return new VideoFrame(this._canvas, { timestamp: ts });
  }

  _resetCanvas() {
    this._canvas = this.view || document.createElement('canvas');
    this._canvas.width = this._w;
    this._canvas.height = this._h;
    this._cctx = this._canvas.getContext('2d', { alpha: false });
  }

  _clearCanvas() {
    if (!this._cctx) return;
    this._cctx.fillStyle = '#000';
    this._cctx.fillRect(0, 0, this._canvas.width, this._canvas.height);
  }

  _loop() {
    const step = () => {
      if (!this.on) {
        this._raf = 0;
        return;
      }
      this._raf = requestAnimationFrame(step);
      this._sync();
      const enc = this.encoder;
      if (!enc || this._busy) return;
      const now = performance.now();
      const interval = 1000 / MEDIA.videoFps;
      if (this._last < 0 || now - this._last >= interval - 1) {
        this._last = now;
        let key = false;
        if (this._forceKey || (now - this._lastKey) > MEDIA.keyframeSecs * 1000) {
          key = true;
          this._forceKey = false;
          this._lastKey = now;
        }
        let frame = null;
        try {
          frame = this._makeFrame(Math.round(now * 1000));
          enc.encode(frame, { keyFrame: key });
        } catch (e) {
        } finally {
          if (frame) {
            try {
              frame.close();
            } catch (e) {}
          }
        }
      }
    };
    this._raf = requestAnimationFrame(step);
  }

  _even(v) {
    const n = Math.max(2, Math.round(v || 0));
    return n % 2 === 0 ? n : n - 1;
  }
}
