import { wsUrl } from './config.js';

export class Bus {
  constructor(role = 'phone', opts) {
    this.role = role;
    this.url = wsUrl();
    this.ws = null;
    this.ready = false;
    // queueBin=false：二进制帧在断线时直接丢（不做陈旧重放）
    this.queueBin = !(opts && opts.queueBin === false);
    this._queue = [];
    this._text = [];
    this._bin = [];
    this._open = [];
    this._status = [];
    this._retry = 0;
    this._closed = false;
    this.dropped = 0;
  }

  /** 当前待发送字节数（拥塞判断用） */
  backlog() {
    const ws = this.ws;
    if (!ws) return 0;
    try {
      return ws.bufferedAmount || 0;
    } catch (e) {
      return 0;
    }
  }

  onText(cb) {
    this._text.push(cb);
    return this;
  }

  onBin(cb) {
    this._bin.push(cb);
    return this;
  }

  onOpen(cb) {
    this._open.push(cb);
    return this;
  }

  onStatus(cb) {
    this._status.push(cb);
    return this;
  }

  connect() {
    if (this._closed) return;
    let ws;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      this._retryLater();
      return;
    }
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    ws.onopen = () => {
      this.ready = true;
      this._retry = 0;
      this._emit(this._status, true);
      this.send({ t: 'hello', role: this.role });
      const q = this._queue;
      this._queue = [];
      for (const item of q) {
        if (typeof item !== 'string') continue;
        try {
          ws.send(item);
        } catch (e) {}
      }
      this._emit(this._open, null);
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        let obj = null;
        try {
          obj = JSON.parse(ev.data);
        } catch (e) {
          return;
        }
        this._emit(this._text, obj);
      } else {
        this._emit(this._bin, ev.data);
      }
    };
    ws.onclose = () => {
      this.ready = false;
      this._emit(this._status, false);
      this._retryLater();
    };
    ws.onerror = () => {};
  }

  send(obj) {
    this._raw(JSON.stringify(obj));
  }

  sendBin(buf) {
    this._raw(buf);
  }

  close() {
    this._closed = true;
    try {
      if (this.ws) this.ws.close();
    } catch (e) {}
  }

  _raw(payload) {
    const ws = this.ws;
    if (ws && ws.readyState === 1) {
      try {
        ws.send(payload);
        return true;
      } catch (e) {}
    }
    // 断线时不缓存媒体帧（重连后灌回旧帧只会加重延迟/串音）
    if (typeof payload !== 'string' && !this.queueBin) {
      this.dropped += 1;
      return false;
    }
    if (this._queue.length < 240) this._queue.push(payload);
    return false;
  }

  _retryLater() {
    if (this._closed) return;
    this._retry = Math.min(this._retry + 1, 8);
    setTimeout(() => this.connect(), 400 * this._retry);
  }

  _emit(list, arg) {
    for (const cb of list) {
      try {
        cb(arg);
      } catch (e) {}
    }
  }
}
