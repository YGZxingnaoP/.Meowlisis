export class Chat {
  constructor(username) {
    this.username = username;
    this.onUser = null;
    this.onError = null;
    this._audioBusy = false;
    this._timer = null;
  }

  setUsername(name) {
    this.username = name;
  }

  send(text) {
    const msg = String(text || '').trim();
    if (!msg) return false;
    if (typeof this.onUser === 'function') this.onUser(msg);
    fetch('/api/chat?text=' + encodeURIComponent(msg)
      + '&username=' + encodeURIComponent(this.username)
      + '&source=phone')
      .then((resp) => {
        if (resp.ok) return null;
        return resp.text().then((body) => {
          let m = '发送失败（HTTP ' + resp.status + '）';
          try {
            const d = JSON.parse(body);
            if (d && d.message) m = d.message;
          } catch (e) {}
          throw new Error(m);
        });
      })
      .catch((err) => {
        if (typeof this.onError === 'function') this.onError(err && err.message ? err.message : '网络异常');
      });
    return true;
  }

  start() {
    if (this._timer) return;
    this._timer = setInterval(() => this._pollAudio(), 500);
  }

  stop() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  _pollAudio() {
    if (this._audioBusy) return;
    this._audioBusy = true;
    fetch('/api/phone/audio')
      .then((r) => r.text())
      .then((raw) => {
        const d = parseReply(raw);
        if (d && d.text && typeof this.onUser === 'function') {
          this.onUser(String(d.text), true);
        }
      })
      .catch(() => {})
      .finally(() => {
        this._audioBusy = false;
      });
  }
}

export function parseReply(raw) {
  if (!raw) return null;
  let s = String(raw).trim();
  if (s.charAt(0) === '(') s = s.slice(1);
  if (s.charAt(s.length - 1) === ')') s = s.slice(0, -1);
  try {
    return JSON.parse(s);
  } catch (e) {
    return null;
  }
}
