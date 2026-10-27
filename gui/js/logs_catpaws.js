/**
 * 日志中心 · 手机操作（CatPaws）面板
 *
 * 数据来源：gui/tools/catpaws_hub.py 的代理接口
 *   /api/catpaws/status   服务端 + 模块 + Runner 状态
 *   /api/catpaws/replies  增量事件（角色说的话、工具调用、阶段）
 *   /api/catpaws/start|stop|answer|launcher|screenshot|stream
 * 画面来源：CatPaws 中继 ws://<host>:<relay_port>/ws?role=viewer
 */
(function () {
    'use strict';

    var HOST = location.hostname || '127.0.0.1';
    var STATUS_MS = 2000;
    var REPLY_MS = 1200;

    var PHASE_TEXT = { control: '操作中', recording: '反思中', end: '已结束', idle: '空闲' };

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function api(path, opt) {
        opt = opt || {};
        opt.cache = 'no-store';
        return fetch(path, opt).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) throw new Error(j.message || ('HTTP ' + r.status));
                return j;
            });
        });
    }

    var Panel = {
        el: null,
        viewer: null,
        statusTimer: null,
        replyTimer: null,
        shotTimer: null,
        seq: 0,
        session: '',
        streamAsked: false,
        lastStreamAsk: 0,
        noFrameTicks: 0,
        busy: false,
        lastQuestion: ''
    };

    Panel._html = function () {
        return '' +
            '<div class="cw-panel">' +
            '  <div class="cw-left">' +
            '    <div class="cw-pills">' +
            '      <span class="cw-pill" id="cwDevice">设备 --</span>' +
            '      <span class="cw-pill" id="cwSession">链路 --</span>' +
            '      <span class="cw-pill" id="cwStream">画面 --</span>' +
            '      <span class="cw-pill" id="cwRunner">Runner --</span>' +
            '    </div>' +
            '    <div class="cw-screen">' +
            '      <canvas id="cwView"></canvas>' +
            '      <img id="cwShot" class="cw-shot hidden" alt="">' +
            '      <div class="cw-idle" id="cwIdle">等待手机画面…</div>' +
            '    </div>' +
            '    <div class="cw-meta" id="cwMeta">未连接</div>' +
            '    <div class="cw-hint" id="cwHint"></div>' +
            '  </div>' +
            '  <div class="cw-right">' +
            '    <div class="cw-actions">' +
            '      <input type="text" id="cwGoal" class="cw-input" placeholder="目标，例如：打开美团点一份麦当劳" autocomplete="off">' +
            '      <button class="cw-btn primary" id="cwStart">开始</button>' +
            '      <button class="cw-btn danger" id="cwStop">停止</button>' +
            '    </div>' +
            '    <div class="cw-actions small">' +
            '      <button class="cw-btn" id="cwShot">截图</button>' +
            '      <button class="cw-btn" id="cwLauncher">拉起 catpaws-launcher</button>' +
            '      <button class="cw-btn" id="cwService">启动 CatPaws 服务</button>' +
            '    </div>' +
            '    <div class="cw-ask" id="cwAsk" hidden>' +
            '      <div class="cw-ask-q" id="cwAskQ"></div>' +
            '      <div class="cw-actions small">' +
            '        <input type="text" id="cwAskInput" class="cw-input" placeholder="回答…" autocomplete="off">' +
            '        <button class="cw-btn primary" id="cwAskSend">回答</button>' +
            '      </div>' +
            '    </div>' +
            '    <div class="cw-log" id="cwLog"></div>' +
            '  </div>' +
            '</div>';
    };

    Panel.mount = function (host) {
        this.unmount();
        this.el = host;
        host.innerHTML = this._html();
        host.hidden = false;
        this._bind();
        this.viewer = new window.GuiWsViewer({
            canvas: host.querySelector('#cwView'),
            idleEl: host.querySelector('#cwIdle'),
            metaEl: host.querySelector('#cwMeta')
        });
        this.viewer.setFit('contain');
        this._pollStatus();
        this._pollReplies();
        var self = this;
        this.statusTimer = setInterval(function () { self._pollStatus(); }, STATUS_MS);
        this.replyTimer = setInterval(function () { self._pollReplies(); }, REPLY_MS);
    };

    Panel.unmount = function () {
        if (this.statusTimer) clearInterval(this.statusTimer);
        if (this.replyTimer) clearInterval(this.replyTimer);
        this.statusTimer = null;
        this.replyTimer = null;
        this._stopShot();
        if (this.viewer) this.viewer.stop();
        this.viewer = null;
        if (this.streamAsked) this._stream(false);
        this.streamAsked = false;
        this.seq = 0;
        this.session = '';
        this.lastQuestion = '';
        this.noFrameTicks = 0;
        if (this.el) this.el.innerHTML = '';
        this.el = null;
    };

    Panel._hint = function (text) {
        var node = this.el && this.el.querySelector('#cwHint');
        if (!node) return;
        node.textContent = text || '';
        node.style.display = text ? '' : 'none';
    };

    Panel._startShot = function (hint) {
        var self = this;
        this._hint(hint);
        var img = this.el && this.el.querySelector('#cwShot');
        if (!img) return;
        img.classList.remove('hidden');
        if (this.shotTimer) return;
        var refresh = function () {
            if (!self.el) return;
            var node = self.el.querySelector('#cwShot');
            if (!node) return;
            var next = new Image();
            next.onload = function () {
                if (self.el && self.el.querySelector('#cwShot')) {
                    node.src = next.src;
                    var idle = self.el.querySelector('#cwIdle');
                    if (idle) idle.classList.add('hidden');
                }
            };
            next.src = '/api/catpaws/screenshot?max_edge=720&t=' + Date.now();
        };
        refresh();
        this.shotTimer = setInterval(refresh, 1500);
    };

    Panel._stopShot = function () {
        if (this.shotTimer) clearInterval(this.shotTimer);
        this.shotTimer = null;
        var img = this.el && this.el.querySelector('#cwShot');
        if (img) {
            img.classList.add('hidden');
            img.removeAttribute('src');
        }
        this._hint('');
    };

    Panel._bind = function () {
        var self = this;
        var $ = function (id) { return self.el.querySelector('#' + id); };
        $('cwStart').addEventListener('click', function () {
            var goal = ($('cwGoal').value || '').trim();
            if (!goal) { $('cwGoal').focus(); return; }
            self._start(goal);
        });
        $('cwGoal').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') $('cwStart').click();
        });
        $('cwStop').addEventListener('click', function () { self._stop(); });
        $('cwShot').addEventListener('click', function () {
            window.open('/api/catpaws/screenshot?max_edge=1280&t=' + Date.now(), '_blank');
        });
        $('cwLauncher').addEventListener('click', function () {
            self._post('/api/catpaws/launcher').then(function (j) {
                self._toast(j.message || '已拉起');
                self._pollStatus();
            }).catch(function (e) { self._toast('拉起失败：' + e.message, true); });
        });
        $('cwService').addEventListener('click', function () {
            self._post('/api/logs/start?svc=catpaw').then(function (j) {
                self._toast(j.message || '已启动 CatPaws 服务');
                setTimeout(function () { self._pollStatus(); }, 1500);
            }).catch(function (e) { self._toast('启动失败：' + e.message, true); });
        });
        $('cwAskSend').addEventListener('click', function () {
            var text = ($('cwAskInput').value || '').trim();
            if (!text) return;
            $('cwAskInput').value = '';
            self._post('/api/catpaws/answer', { text: text }).then(function () {
                self._appendLine('answer', '你：' + text);
                self._pollStatus();
            }).catch(function (e) { self._toast('回答失败：' + e.message, true); });
        });
        $('cwAskInput').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') $('cwAskSend').click();
        });
    };

    Panel._post = function (path, body) {
        return api(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {})
        });
    };

    Panel._toast = function (msg, isErr) {
        if (window.Logs && Logs.toast) Logs.toast(msg, isErr);
        else console.log('[catpaws]', msg);
    };

    Panel._pill = function (id, text, cls) {
        var node = this.el && this.el.querySelector('#' + id);
        if (!node) return;
        node.textContent = text;
        node.className = 'cw-pill' + (cls ? ' ' + cls : '');
    };

    Panel._stream = function (on) {
        return this._post('/api/catpaws/stream', { on: !!on }).catch(function () { return {}; });
    };

    Panel._start = function (goal) {
        var self = this;
        if (self.busy) return;
        self.busy = true;
        self._appendLine('phase', '→ 开始：' + goal);
        self._post('/api/catpaws/start', { goal: goal }).then(function (j) {
            if (j.status === 'error') self._toast(j.message || '启动失败', true);
            else self._toast('已接管手机');
            setTimeout(function () { self._pollStatus(); }, 800);
        }).catch(function (e) {
            self._toast('启动失败：' + e.message, true);
        }).then(function () { self.busy = false; });
    };

    Panel._stop = function () {
        var self = this;
        self._post('/api/catpaws/stop').then(function () {
            self._toast('已停止手机操作');
            self._appendLine('phase', '→ 你要求停止');
            setTimeout(function () { self._pollStatus(); }, 500);
        }).catch(function (e) { self._toast('停止失败：' + e.message, true); });
    };

    Panel._pollStatus = function () {
        var self = this;
        if (!self.el) return;
        api('/api/catpaws/status').then(function (j) {
            self._render(j || {});
        }).catch(function () {
            self._pill('cwDevice', '设备 未知', 'off');
        });
    };

    Panel._render = function (payload) {
        var server = payload.server || {};
        var data = server.data || {};
        var module = payload.module || {};
        var runner = payload.runner || {};
        if (!server.ok) {
            this._pill('cwDevice', '服务未启动', 'off');
            this._pill('cwSession', '链路 --');
            this._pill('cwStream', '画面 --');
            this._stopShot();
            this._hint('CatPaws 服务没启动：点下面「启动 CatPaws 服务」，或用启动球「手机操作」');
        } else {
            var device = data.device || {};
            var info = device.info || {};
            var screen = info.screen || {};
            var pixel = (screen.pixel || []).join('x');
            if (device.error || device.mock) this._pill('cwDevice', '设备 未连接', 'off');
            else this._pill('cwDevice', '设备 ' + (pixel || '就绪'), 'on');

            var session = data.session || {};
            var phase = session.phase || 'idle';
            var text = PHASE_TEXT[phase] || phase;
            if (phase === 'control' || phase === 'recording') text += ' ' + (session.elapsed_sec || 0) + 's';
            this._pill('cwSession', '链路 ' + text,
                (phase === 'control' || phase === 'recording') ? 'busy' : (phase === 'end' ? 'done' : ''));

            var relay = data.relay || {};
            this._pill('cwStream',
                '画面 ' + (relay.device_online ? (relay.streaming ? relay.fps + 'fps' : '已连·关') : '未连'),
                relay.streaming ? 'on' : '');
            this._ensureStream(relay);
            this._checkPicture(relay);
            this._renderQuestion(data.pending_question);
        }
        this._pill('cwRunner', runner.ok
            ? ('Runner 就绪' + (runner.version ? ' v' + runner.version : ''))
            : 'Runner 未连接', runner.ok ? 'on' : 'off');
        var mod = module.data || {};
        if (mod.module && mod.module.active && !(data.session || {}).phase) {
            this._pill('cwSession', '主程序已接管', 'busy');
        }
    };

    Panel._ensureStream = function (relay) {
        var port = relay.port;
        if (!port || !this.viewer) return;
        var token = relay.token || '';
        var url = 'ws://' + HOST + ':' + port + '/ws?role=viewer&src=screen&token=' + encodeURIComponent(token);
        if (this.viewer.closing) this.viewer.start(url);
        else this.viewer.setUrl(url);
        var now = Date.now();
        if (!this.streamAsked || (!relay.streaming && now - this.lastStreamAsk > 10000)) {
            this.streamAsked = true;
            this.lastStreamAsk = now;
            if (!relay.streaming) this._stream(true);
        }
    };

    Panel._checkPicture = function (relay) {
        var live = !!(relay.device_online && relay.streaming && (relay.fps || 0) > 0);
        if (live) {
            this.noFrameTicks = 0;
            if (this.shotTimer) this._stopShot();
            return;
        }
        this.noFrameTicks += 1;
        if (this.noFrameTicks < 2) return;
        var hint;
        if (!relay.device_online) {
            hint = '手机没连上视频中继（手机端 CatCam 未推屏），先用截图轮询顶上';
        } else if (!relay.streaming) {
            hint = '推流还没开起来（正在自动请求），先用截图轮询顶上';
        } else {
            hint = '中继已连但没有视频帧（手机端录屏/推流未开），先用截图轮询顶上';
        }
        this._startShot(hint);
    };

    Panel._renderQuestion = function (question) {
        var box = this.el && this.el.querySelector('#cwAsk');
        if (!box) return;
        var text = question && question.question ? String(question.question) : '';
        if (!text) {
            box.hidden = true;
            this.lastQuestion = '';
            return;
        }
        box.hidden = false;
        var q = this.el.querySelector('#cwAskQ');
        if (q) q.textContent = '❓ ' + text;
        if (text !== this.lastQuestion) {
            this.lastQuestion = text;
            this._appendLine('ask', '角色问：' + text);
            var input = this.el.querySelector('#cwAskInput');
            if (input && document.activeElement !== input) input.focus();
        }
    };

    Panel._pollReplies = function () {
        var self = this;
        if (!self.el) return;
        api('/api/catpaws/replies?since=' + self.seq + '&limit=200').then(function (j) {
            if (!j || j.ok === false) return;
            var session = j.session || '';
            if (session && session !== self.session) {
                self.session = session;
                self.seq = 0;
                var log = self.el && self.el.querySelector('#cwLog');
                if (log) log.innerHTML = '';
            }
            var items = j.items || [];
            items.forEach(function (item) {
                var seq = Number(item.seq || 0);
                if (seq > self.seq) self.seq = seq;
                self._append(item);
            });
        }).catch(function () { /* 服务端没起来时忽略 */ });
    };

    Panel._append = function (item) {
        var kind = item.kind || '';
        var text = '';
        if (kind === 'assistant') text = item.text || '';
        else if (kind === 'phase') {
            var label = PHASE_TEXT[item.phase] || item.phase || '';
            text = '阶段 → ' + label + (item.reason ? '（' + item.reason + '）' : '');
        } else if (kind === 'tool_call') text = '· ' + (item.tool || '') + ' ' + JSON.stringify(item.args || {});
        else if (kind === 'single' || kind === 'sequence') {
            text = '· ' + (item.action || (item.steps || []).join(' → ')) + (item.ok ? ' ✓' : ' ✗ ' + (item.code || ''));
        } else if (kind === 'observe') {
            text = '· 看屏幕 ' + ((item.texts || []).slice(0, 6).join(' / ') || ((item.screen || {}).pixel || []).join('x'));
        } else if (kind === 'ask') text = '❓ ' + (item.question || '');
        else if (kind === 'answer') text = '💬 ' + (item.answer || '（没回答）');
        else if (kind === 'task_done') text = '✔ 收尾：' + (item.summary || '');
        else if (kind === 'write_confirm') text = '✍ 写脚本确认：' + (item.title || '');
        else if (kind === 'action_created' || kind === 'action_updated') text = '✍ ' + kind + ' ' + (item.action_id || '');
        else if (kind === 'error') text = '⚠ ' + (item.code || '') + ' ' + (item.message || '');
        else if (kind === 'stop' || kind === 'stop_request') text = '🛑 停止（' + (item.reason || '') + '）';
        else if (kind === 'keep_awake') text = '· 空闲防息屏：轻点一下';
        else if (kind === 'device_locked') text = '🔒 手机锁屏，等你解锁';
        else if (kind === 'instruction') text = '你：' + (item.text || '');
        if (!text) return;
        this._appendLine(kind, text);
    };

    Panel._appendLine = function (cls, text) {
        var log = this.el && this.el.querySelector('#cwLog');
        if (!log) return;
        var row = document.createElement('div');
        row.className = 'cw-line' + (cls ? ' ' + cls : '');
        var time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
        row.innerHTML = '<span class="cw-t">' + esc(time) + '</span>' +
            '<span class="cw-b">' + esc(text) + '</span>';
        log.appendChild(row);
        while (log.childElementCount > 400) log.removeChild(log.firstChild);
        log.scrollTop = log.scrollHeight;
    };

    window.CatPawsPanel = Panel;
})();
