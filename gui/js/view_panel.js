/**
 * 通用 WebSocket 视频查看器（WebCodecs 解码 + canvas 绘制）
 *
 * 两路流共用同一套帧格式：[标志 1B][时间戳 8B][编码数据]
 *   - 标志 & 0x01 = 关键帧
 *   - 首字节 0x03 表示手机上行音频旁路帧，直接丢弃
 *
 * 用法：
 *   const v = new GuiWsViewer({ canvas, idleEl, metaEl });
 *   v.start(url);   // 连接并开始解码
 *   v.stop();       // 断开并释放解码器
 *   v.setFit('cover' | 'contain');
 */
(function () {
    'use strict';

    function GuiWsViewer(opts) {
        opts = opts || {};
        this.canvas = opts.canvas;
        this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
        this.idleEl = opts.idleEl || null;
        this.metaEl = opts.metaEl || null;
        this.url = '';
        this.ws = null;
        this.decoder = null;
        this.codec = '';
        this.needKey = true;
        this.size = null;
        this.retry = 0;
        this.closing = true;
        this.decoded = 0;
        this.frames = 0;
        this.fpsTs = 0;
        this.lastTs = 0;
        this.onStatus = opts.onStatus || null;
    }

    GuiWsViewer.prototype.setFit = function (mode) {
        if (!this.canvas) return;
        this.canvas.style.objectFit = (mode === 'contain') ? 'contain' : 'cover';
    };

    GuiWsViewer.prototype._meta = function (text) {
        if (this.metaEl) this.metaEl.textContent = text;
    };

    GuiWsViewer.prototype._idle = function (show) {
        if (this.idleEl) this.idleEl.classList.toggle('hidden', !show);
    };

    GuiWsViewer.prototype._applySize = function (w, h) {
        if (!(w > 0) || !(h > 0)) return;
        if (this.size && this.size[0] === w && this.size[1] === h) return;
        this.size = [w, h];
        this.canvas.width = w;
        this.canvas.height = h;
    };

    GuiWsViewer.prototype._requestKey = function () {
        if (this.ws && this.ws.readyState === 1) {
            try { this.ws.send(JSON.stringify({ t: 'reqkey' })); } catch (e) { /* ignore */ }
        }
    };

    GuiWsViewer.prototype._closeDecoder = function () {
        if (!this.decoder) return;
        try { this.decoder.close(); } catch (e) { /* ignore */ }
        this.decoder = null;
        this.needKey = true;
        this.lastTs = 0;
    };

    GuiWsViewer.prototype._configure = function (codec) {
        var self = this;
        self._closeDecoder();
        if (typeof VideoDecoder === 'undefined') {
            self._idle(true);
            self._meta('浏览器不支持 WebCodecs');
            return;
        }
        var candidates = [
            { codec: codec, hardwareAcceleration: 'prefer-hardware', optimizeForLatency: true },
            { codec: codec, optimizeForLatency: true },
            { codec: codec }
        ];
        var pick = null;
        var index = 0;
        function tryNext() {
            if (index >= candidates.length) {
                if (!pick) {
                    self._meta('解码配置不受支持：' + codec);
                    self._idle(true);
                    return;
                }
                self.decoder = new VideoDecoder({
                    output: function (frame) { self._onFrame(frame); },
                    error: function () { self.needKey = true; self._requestKey(); }
                });
                self.decoder.configure(pick);
                self.codec = codec;
                self._idle(true);
                self._meta(codec + ' · 等待画面…');
                self._requestKey();
                return;
            }
            var cand = candidates[index++];
            VideoDecoder.isConfigSupported(cand).then(function (res) {
                if (res && res.supported && !pick) pick = cand;
                tryNext();
            }).catch(function () {
                if (!pick) pick = cand;
                tryNext();
            });
        }
        tryNext();
    };

    GuiWsViewer.prototype._onFrame = function (frame) {
        try {
            var ts = Number(frame.timestamp) || 0;
            if (ts && this.lastTs && ts < this.lastTs) return;
            if (ts) this.lastTs = ts;
            var w = frame.displayWidth || frame.codedWidth;
            var h = frame.displayHeight || frame.codedHeight;
            this._applySize(w, h);
            if (this.ctx) this.ctx.drawImage(frame, 0, 0, this.canvas.width, this.canvas.height);
            this._idle(false);
            this.decoded += 1;
            this.frames += 1;
            var now = performance.now();
            if (!this.fpsTs) this.fpsTs = now;
            if (now - this.fpsTs >= 1000 && this.size) {
                var fps = Math.round(this.decoded * 1000 / (now - this.fpsTs));
                this._meta(this.codec + ' · ' + this.size[0] + 'x' + this.size[1] + ' · ' + fps + 'fps');
                this.decoded = 0;
                this.fpsTs = now;
            }
        } finally {
            try { frame.close(); } catch (e) { /* ignore */ }
        }
    };

    GuiWsViewer.prototype._onBinary = function (buffer) {
        var data = new Uint8Array(buffer);
        if (data.length && data[0] === 0x03) return;
        if (!this.decoder || buffer.byteLength < 10) return;
        var view = new DataView(buffer);
        var flags = data[0];
        var isKey = (flags & 0x01) === 1;
        var ts = Number(view.getBigUint64(1, false));
        if (!isKey && this.needKey) return;
        var queue = 0;
        try { queue = this.decoder.decodeQueueSize || 0; } catch (e) { /* ignore */ }
        if (!isKey && queue > 2) {
            if (queue > 8) { try { this.decoder.reset(); } catch (e) { /* ignore */ } this.needKey = true; this._requestKey(); }
            return;
        }
        if (isKey) this.needKey = false;
        try {
            this.decoder.decode(new EncodedVideoChunk({
                type: isKey ? 'key' : 'delta', timestamp: ts, data: data.subarray(9)
            }));
        } catch (e) {
            this.needKey = true;
            this._requestKey();
        }
    };

    GuiWsViewer.prototype._schedule = function () {
        var self = this;
        if (self.closing) return;
        self.retry = Math.min(self.retry + 1, 6);
        setTimeout(function () { self._connect(); }, 500 * self.retry);
    };

    GuiWsViewer.prototype._connect = function () {
        var self = this;
        if (self.closing || !self.url) return;
        var socket;
        try { socket = new WebSocket(self.url); } catch (e) { self._schedule(); return; }
        self.ws = socket;
        socket.binaryType = 'arraybuffer';
        socket.onopen = function () {
            self.retry = 0;
            try { socket.send(JSON.stringify({ t: 'hello', role: 'viewer', src: 'screen' })); } catch (e) { /* ignore */ }
            self._meta('已连接，等待画面…');
            if (self.onStatus) self.onStatus(true);
        };
        socket.onmessage = function (event) {
            if (typeof event.data === 'string') {
                var msg = null;
                try { msg = JSON.parse(event.data); } catch (e) { return; }
                if (msg.t === 'vcfg' && msg.codec) self._configure(msg.codec);
                else if (msg.t === 'vstop') { self._closeDecoder(); self._idle(true); self._meta('手机已停止推流'); }
                else if (msg.t === 'hello') self._meta('已连接，等待画面…');
                else if (msg.t === 'error' && self.metaEl) self._meta('中继返回错误：' + (msg.code || ''));
                return;
            }
            self._onBinary(event.data);
        };
        socket.onclose = function () {
            self.ws = null;
            self._closeDecoder();
            self._idle(true);
            if (self.onStatus) self.onStatus(false);
            self._schedule();
        };
        socket.onerror = function () { /* onclose 会跟上 */ };
    };

    GuiWsViewer.prototype.start = function (url) {
        this.url = url || '';
        this.closing = false;
        this.retry = 0;
        this._idle(true);
        this._meta('连接中…');
        this._connect();
    };

    GuiWsViewer.prototype.setUrl = function (url) {
        if (!url || url === this.url) return;
        var running = !this.closing;
        this.stop();
        if (running) this.start(url);
        else this.url = url;
    };

    GuiWsViewer.prototype.stop = function () {
        this.closing = true;
        this._closeDecoder();
        var socket = this.ws;
        this.ws = null;
        if (socket) {
            socket.onopen = null;
            socket.onmessage = null;
            socket.onclose = null;
            socket.onerror = null;
            try { socket.close(); } catch (e) { /* ignore */ }
        }
    };

    window.GuiWsViewer = GuiWsViewer;
})();
