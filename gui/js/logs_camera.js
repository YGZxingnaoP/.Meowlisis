/**
 * 日志中心 · 手机摄像头面板（.vendor/.cam 的观看端）
 *
 * 画面走 .cam 的纯 HTTP 观察端口（PET_HTTP_PORT，默认 8445）：
 *   ws://<host>:8445/ws  —— 手机上行 H.264，WebCodecs 解码
 * 尺寸规则：横屏、竖屏都按 cover 撑满面板（不缩小、不拉伸，超出部分裁掉）。
 */
(function () {
    'use strict';

    var HOST = location.hostname || '127.0.0.1';
    var CAM_PORT = 8445;

    var Panel = {
        el: null,
        viewer: null,
        hintTimer: null,
        lastFrames: 0,
        idleTicks: 0
    };

    Panel._html = function () {
        return '' +
            '<div class="cam-panel">' +
            '  <canvas id="camView"></canvas>' +
            '  <div class="cam-idle" id="camIdle">等待手机画面…</div>' +
            '  <div class="cam-hud">' +
            '    <span class="cam-dot"></span>' +
            '    <span class="cam-meta" id="camMeta">连接中…</span>' +
            '    <span class="cam-grow"></span>' +
            '    <button class="cw-btn" id="camFull">撑满/适应</button>' +
            '  </div>' +
            '  <div class="cam-hint" id="camHint" hidden></div>' +
            '</div>';
    };

    Panel.mount = function (host) {
        this.unmount();
        this.el = host;
        host.innerHTML = this._html();
        host.hidden = false;
        var canvas = host.querySelector('#camView');
        this.viewer = new window.GuiWsViewer({
            canvas: canvas,
            idleEl: host.querySelector('#camIdle'),
            metaEl: host.querySelector('#camMeta')
        });
        this.viewer.setFit('cover');
        this.viewer.start('ws://' + HOST + ':' + CAM_PORT + '/ws');
        var self = this;
        var btn = host.querySelector('#camFull');
        if (btn) {
            btn.addEventListener('click', function () {
                var cover = self.viewer.canvas.style.objectFit !== 'contain';
                self.viewer.setFit(cover ? 'contain' : 'cover');
                btn.textContent = cover ? '撑满' : '适应';
            });
        }
        this._hintService();
        this.lastFrames = 0;
        this.idleTicks = 0;
        this.hintTimer = setInterval(function () {
            self._watchFrames();
        }, 2500);
    };

    Panel.unmount = function () {
        if (this.hintTimer) clearInterval(this.hintTimer);
        this.hintTimer = null;
        if (this.viewer) this.viewer.stop();
        this.viewer = null;
        if (this.el) this.el.innerHTML = '';
        this.el = null;
    };

    Panel._watchFrames = function () {
        if (!this.el || !this.viewer) return;
        var frames = this.viewer.frames || 0;
        var grown = frames > this.lastFrames;
        this.lastFrames = frames;
        var hint = this.el.querySelector('#camHint');
        if (grown) {
            this.idleTicks = 0;
            if (hint) hint.hidden = true;
            return;
        }
        this.idleTicks += 1;
        if (this.idleTicks < 3 || !hint) return;
        hint.hidden = false;
        hint.textContent = '还没收到画面：手机要用浏览器打开 https://<电脑IP>:8443 并允许摄像头；'
            + '电脑端观看端口是 8445；服务没起就在左侧点 ▶ 启动「手机接口」';
    };

    Panel._hintService = function () {
        var self = this;
        fetch('/api/logs/services', { cache: 'no-store' })
            .then(function (r) { return r.json().catch(function () { return {}; }); })
            .then(function (j) {
                var phone = ((j && j.items) || []).filter(function (x) { return x.key === 'phone'; })[0];
                var idle = self.el && self.el.querySelector('#camIdle');
                if (phone && !phone.running && idle) idle.textContent = '手机接口服务未启动（左侧 ▶ 启动）';
            })
            .catch(function () { /* ignore */ });
    };

    window.CameraPanel = Panel;
})();
