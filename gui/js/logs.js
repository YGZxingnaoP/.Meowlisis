/**
 * 日志中心前端（/logs）
 *
 * 设计原则：这里是"她干了什么"的事件流，不是工程日志查看器。
 *   - 后端把每行判成 story / warn / error / bg 四层（见 gui/tools/log_rules.py）
 *   - 默认只渲染前三层，一行一个事件（图标 + 一句话 + 时间）
 *   - 后台层（管道/参数/轮询/进度条/已知无害断连）只折叠计数，一键可展开
 *   - 点一行 → 右侧抽屉看原文/堆栈（不再占三行常驻）
 *
 * 接口：GET /api/logs/tail?svc=&since=&bg=1
 *   lines: [{tier, scene, icon, t, d, ts, src, txt, n, more, fault, lv}]
 *   noise: {类别: 折叠行数}
 */
(function () {
    'use strict';

    var MAX_LINES = 3000;          // 页面最多保留多少条事件，防内存膨胀
    var TAIL_MS = 1000;            // 日志轮询间隔
    var LIST_MS = 3000;            // 服务状态轮询间隔
    var MERGE_MS = 30000;          // 同一条事件在这个时间窗内合并成 ×N

    var $ = function (id) { return document.getElementById(id); };

    function _t(s, vars) {
        try { if (window.I18n && I18n.text) return I18n.text(s, vars); } catch (e) { /* ignore */ }
        return s;
    }

    // 场景 → 图标（页面上的页签）
    var SCENES = [
        ['', '全部', '📋'],
        ['chat', '聊天', '💬'],
        ['voice', '语音', '🎤'],
        ['phone', '手机', '📱'],
        ['paint', '画图', '🎨'],
        ['sing', '唱歌', '🎵'],
        ['mind', '心情', '💗'],
        ['sys', '系统', '⚙️']
    ];

    // 事件图标键 → 字符
    var ICONS = {
        'in': '📥', 'say': '🗣', 'out': '💬', 'pic': '🖼', 'file': '📎', 'emoji': '😊',
        'phone': '📱', 'paint': '🎨', 'music': '🎵', 'heart': '💗', 'mic': '🎤',
        'eye': '👁', 'power': '🔌', 'link': '🔗', 'tool': '🔧', 'gear': '⚙️',
        'warn': '⚠️', 'error': '❗', 'dot': '·'
    };

    // 折叠类别 → 中文（只用于"已折叠 N 行"的明细）
    var NOISE_LABEL = {
        'access': '访问日志', 'frame': '帧注入', 'progress': '进度条',
        'tts-pipe': '语音管道', 'conn-quiet': '连接抖动', 'retry': '重连重试',
        'boundary': '说话边界', 'known-fail': '已知失败', 'judge': '判定细节',
        'banner': '分隔行', 'diag': '诊断', 'module': '模块内部',
        'other': '未分类', 'empty': '空行'
    };

    var elList = $('svcList'), elLines = $('lines'), elView = $('view');
    var elCurName = $('curName'), elCurState = $('curState'), elCurFile = $('curFile');
    var elFilter = $('filter'), elEmpty = $('empty'), elScenes = $('scenes');
    var elPanel = $('svcPanel'), elBudget = $('budget'), elOnlyProb = $('onlyProblems');
    var elDrawer = $('drawer'), elDrawerTitle = $('drawerTitle'), elDrawerRaw = $('drawerRaw');
    var elQrBox = $('qrBox'), elQrImg = $('qrImg'), elQrHint = $('qrHint');
    var elQrWebui = $('qrWebui'), elQrToken = $('qrToken');
    var elStatLines = $('statLines'), elStatBg = $('statBg'), elStatSize = $('statSize');
    var elStatRate = $('statRate'), elStatErr = $('statErr'), elTs = $('tsInfo');
    var elAuto = $('autoScroll');

    var cur = 'main';              // 当前服务
    var offset = null;             // 已读到的字节偏移
    var paused = false;
    var rate = 0, rateTick = 0, rateN = 0;
    var alive = true;
    var scene = '';                // 当前场景页签
    var onlyProblems = false;      // 只看问题
    var bgShown = false;           // 是否展开后台层
    var rawMode = false;           // 原始日志视图：不做折叠/合并，直接看每一行
    var noiseTotals = {};          // 折叠统计（本次会话累计）
    var counts = { story: 0, warn: 0, error: 0, bg: 0 };
    var lastRec = null;            // 上一条事件的 DOM/时间去重合并用
    var openedKey = '';            // 抽屉里当前是哪个事件

    // ---------------- 工具 ----------------
    function toast(msg, isErr) {
        var t = $('toast');
        t.textContent = msg;
        t.className = 'lh-toast show' + (isErr ? ' err' : '');
        clearTimeout(t._t);
        t._t = setTimeout(function () { t.className = 'lh-toast'; }, 2600);
    }

    function api(path, opt) {
        opt = opt || {};
        opt.headers = opt.headers || {};
        opt.cache = 'no-store';
        return fetch(path, opt).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) throw new Error(j.message || ('HTTP ' + r.status));
                return j;
            });
        });
    }

    function fmtSize(n) {
        if (!n) return '0 B';
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        return (n / 1024 / 1024).toFixed(2) + ' MB';
    }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function shortSrc(s) {
        var seg = String(s || '').split(/[\\/]/).pop() || '';
        return seg.length > 42 ? seg.slice(0, 42) + '…' : seg;
    }

    function fmtTime(d) {
        try {
            return d.toLocaleTimeString(I18n && I18n.current ? I18n.current() : 'zh-CN', { hour12: false });
        } catch (e) {
            return d.toLocaleTimeString();
        }
    }

    function hhmm(ts) {
        var m = /(\d{2}:\d{2}:\d{2})/.exec(String(ts || ''));
        return m ? m[1].slice(0, 5) : '';
    }

    function iconOf(rec) {
        return ICONS[rec.icon] || (rec.tier === 'error' ? '❗' : (rec.tier === 'warn' ? '⚠️' : '·'));
    }

    // ---------------- 过滤 ----------------
    var _fReKw = null, _fRe = null;
    function filterRe() {
        var kw = (elFilter.value || '').trim();
        if (kw === _fReKw) return _fRe;
        _fReKw = kw;
        _fRe = null;
        if (!kw) return null;
        var parts = kw.split('|').map(function (s) { return s.trim(); }).filter(Boolean);
        if (!parts.length) return null;
        try {
            _fRe = new RegExp(parts.map(function (p) {
                return p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            }).join('|'), 'i');
        } catch (e) { _fRe = null; }
        return _fRe;
    }

    function lineOk(rec) {
        if (rawMode) return true;      // 原始日志视图：不过滤层级/场景
        if (onlyProblems && !(rec.tier === 'warn' || rec.tier === 'error' || rec.fault)) return false;
        if (scene && rec.scene !== scene) return false;
        var re = filterRe();
        if (!re) return true;
        return re.test(rec.txt || rec.msg || '');
    }

    // ---------------- 计数 / 折叠预算 ----------------
    function updateCounts() {
        var visible = counts.story + counts.warn + counts.error;
        elStatLines.textContent = _t('{n} 条事件', { n: rawMode ? visible + counts.bg : visible });
        if (elStatBg) {
            var hidden = 0;
            Object.keys(noiseTotals).forEach(function (k) { hidden += noiseTotals[k]; });
            if (!rawMode) counts.bg = hidden;
            elStatBg.textContent = rawMode
                ? _t('{n} 行日志', { n: counts.bg })
                : _t('后台 {n} 行', { n: hidden });
        }
        renderBudget();
    }

    var _budgetSig = '';
    function renderBudget() {
        if (!elBudget) return;
        if (rawMode) {
            if (_budgetSig !== 'raw') {
                _budgetSig = 'raw';
                elBudget.innerHTML = '';
                elBudget.hidden = true;
            }
            return;
        }
        var keys = Object.keys(noiseTotals).sort(function (a, b) { return noiseTotals[b] - noiseTotals[a]; });
        var total = 0;
        keys.forEach(function (k) { total += noiseTotals[k]; });
        if (!total) {
            if (_budgetSig !== '') {
                _budgetSig = '';
                elBudget.innerHTML = '';
                elBudget.hidden = true;
            }
            return;
        }
        var sig = keys.map(function (k) { return k + ':' + noiseTotals[k]; }).join('|') + '|' + (bgShown ? 1 : 0);
        if (sig === _budgetSig) return;      // 每秒轮询不重建 DOM，避免闪烁/点不中
        _budgetSig = sig;
        elBudget.hidden = false;
        var detail = keys.slice(0, 5).map(function (k) {
            return esc(_t(NOISE_LABEL[k] || k)) + ' ' + noiseTotals[k];
        }).join(' · ');
        elBudget.innerHTML =
            '<span class="budget-t">' + esc(_t('已折叠 {n} 行技术日志', { n: total })) + '</span>' +
            '<span class="budget-d">' + detail + (keys.length > 5 ? ' …' : '') + '</span>' +
            '<button class="lh-btn budget-btn" id="btnBg">' +
            esc(bgShown ? _t('收起后台') : _t('展开后台')) + '</button>';
    }

    function addNoise(noise) {
        if (!noise) return;
        Object.keys(noise).forEach(function (k) {
            noiseTotals[k] = (noiseTotals[k] || 0) + noise[k];
        });
    }

    function resetCounts() {
        counts = { story: 0, warn: 0, error: 0, bg: 0 };
        noiseTotals = {};
        lastRec = null;
        _budgetSig = '';
        updateCounts();
    }

    function applyScenes() {
        if (!elScenes) return;
        Array.prototype.forEach.call(elScenes.querySelectorAll('.lh-scene'), function (b) {
            b.classList.toggle('on', (b.dataset.scene || '') === scene);
        });
        if (elOnlyProb) elOnlyProb.classList.toggle('on', onlyProblems);
    }

    // ---------------- 抽屉（原文） ----------------
    function openDrawer(rec) {
        if (!elDrawer) return;
        var head = (rec.t ? _t(rec.t) : _t('日志原文'));
        if (rec.d) head += '：' + rec.d;
        elDrawerTitle.textContent = head;
        var meta = [];
        if (rec.ts) meta.push(rec.ts);
        if (rec.src) meta.push(shortSrc(rec.src));
        if (rec.lv) meta.push(rec.lv);
        if (rec.n > 1) meta.push('×' + rec.n);
        elDrawerRaw.textContent = (meta.length ? meta.join(' · ') + '\n\n' : '') + (rec.txt || rec.msg || '');
        elDrawer.hidden = false;
        openedKey = (rec.ts || '') + (rec.txt || '').slice(0, 40);
    }

    function closeDrawer() {
        if (elDrawer) elDrawer.hidden = true;
        openedKey = '';
    }

    // ---------------- 渲染 ----------------
    function atBottom() {
        return elView.scrollTop + elView.clientHeight >= elView.scrollHeight - 24;
    }

    function stick(wasBottom) {
        if (elAuto.checked && wasBottom) elView.scrollTop = elView.scrollHeight;
    }

    /** 一条事件 = 图标 + 一句话 + ×N + 时间；点开看原文 */
    function lineNode(rec) {
        var d = document.createElement('div');
        d.className = 'lh-ev tier-' + (rec.tier || 'story') + (rec.fault ? ' fault' : '')
            + (rec.tier === 'bg' ? ' is-bg' : '');
        var text = rec.t ? _t(rec.t) : (rec.msg || '');
        if (rec.d) text += '：' + rec.d;
        var html = '<span class="ic">' + esc(iconOf(rec)) + '</span>';
        html += '<span class="tx">' + esc(text) + '</span>';
        if (rec.n > 1) html += '<span class="n">×' + rec.n + '</span>';
        if (rec.more) html += '<span class="n more">+' + rec.more + '</span>';
        html += '<span class="tm">' + esc(hhmm(rec.ts)) + '</span>';
        d.innerHTML = html;
        d.title = text + '\n' + _t('点开看原文');
        d.addEventListener('click', function () { openDrawer(rec); });
        return d;
    }

    /** 同一条事件在 30 秒内合并成 ×N（后端已经按形状合并过一轮，这里补时间窗） */
    function mergeInto(rec) {
        if (!lastRec || !lastRec.el || !lastRec.ms) return false;
        if (rec.tier === 'error') return false;
        var key = (rec.t || rec.msg || '') + '|' + (rec.d || '') + '|' + (rec.tier || '');
        if (key !== lastRec.key) return false;
        var ms = Date.parse((rec.ts || '').replace(',', '.'));
        if (isNaN(ms) || isNaN(lastRec.ms)) return false;
        if (Math.abs(ms - lastRec.ms) > MERGE_MS) return false;
        lastRec.n += 1;
        var el = lastRec.el;
        var badge = el.querySelector('.n');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'n';
            el.insertBefore(badge, el.querySelector('.tm'));
        }
        badge.textContent = '×' + lastRec.n;
        return true;
    }

    function append(records) {
        var keep = elAuto.checked ? atBottom() : false;
        var frag = document.createDocumentFragment(), added = 0;
        records.forEach(function (rec) {
            if (!lineOk(rec)) return;            // 先过滤再计数，页脚与可见行一致
            counts[rec.tier] = (counts[rec.tier] || 0) + 1;
            if (!rawMode && mergeInto(rec)) return;   // 原始视图不合并，保持逐行
            var el = lineNode(rec);
            frag.appendChild(el);
            lastRec = {
                el: el, n: rec.n || 1, tier: rec.tier,
                key: (rec.t || rec.msg || '') + '|' + (rec.d || '') + '|' + (rec.tier || ''),
                ms: Date.parse((rec.ts || '').replace(',', '.'))
            };
            added++;
        });
        updateCounts();
        if (added) {
            elEmpty.style.display = 'none';
            elLines.appendChild(frag);
            var over = elLines.childElementCount - MAX_LINES;
            while (over-- > 0 && elLines.firstChild) elLines.removeChild(elLines.firstChild);
            rateN += added;
            stick(keep);
        }
    }

    function renderAll(records) {
        elLines.innerHTML = '';
        resetCounts();
        elEmpty.style.display = 'none';
        append(records);
        elView.scrollTop = elView.scrollHeight;      // 首次直接到底
        // 这个服务这段时间没有任何"人话"事件 → 明确告诉用户，别以为坏了
        if (!elLines.childElementCount) {
            elEmpty.style.display = '';
            var hidden = 0;
            Object.keys(noiseTotals).forEach(function (k) { hidden += noiseTotals[k]; });
            if (rawMode) {
                elEmpty.textContent = _t('这段时间日志为空');
            } else {
                elEmpty.textContent = hidden
                    ? _t('这段时间只有技术日志（{n} 行，已折叠）· 点上方「原始日志」查看全部', { n: hidden })
                    : _t('这段时间没有事件');
            }
        }
    }

    function refilter() {
        offset = null;
        bgShown = bgShown;      // 保持用户选择
        loadOnce(true);
    }

    function toggleBg() {
        bgShown = !bgShown;
        offset = null;
        loadOnce(true);
    }

    function applyRawUi() {
        if (elLines) elLines.classList.toggle('raw-mode', rawMode);
        if (elScenes) elScenes.style.display = rawMode ? 'none' : '';
        if (elOnlyProb) elOnlyProb.style.display = rawMode ? 'none' : '';
        var b = $('btnRaw');
        if (b) {
            b.classList.toggle('lh-btn-primary', rawMode);
            var key = rawMode ? '事件视图' : '原始日志';
            b.setAttribute('data-i18n', key);
            b.textContent = _t(key);
        }
    }

    function toggleRaw() {
        rawMode = !rawMode;
        if (rawMode) bgShown = true;
        offset = null;
        applyRawUi();
        loadOnce(true);
    }

    // ---------------- 拉日志 ----------------
    function loadOnce(reset) {
        var q = '/api/logs/tail?svc=' + encodeURIComponent(cur) + '&limit=1500';
        if (offset !== null && !reset) q += '&since=' + offset;
        if (bgShown || rawMode) q += '&bg=1';
        if (rawMode) q += '&raw=1';
        return api(q).then(function (j) {
            offset = j.offset;
            elStatSize.textContent = _t('文件 {size}', { size: fmtSize(j.size) });
            var portTxt = j.port ? String(j.port) : ((j.ports || []).join(',') || '');
            if (j.running) {
                var extra = (j.pid ? ' pid ' + j.pid : '') +
                            (portTxt ? ' · ' + _t('端口 {ports}', { ports: portTxt }) : '');
                elCurState.textContent = _t('● 运行中') + extra;
            } else if (j.state === 'starting') {
                elCurState.textContent = _t('◌ 启动中') +
                    (portTxt ? ' · ' + _t('端口 {ports} 未监听', { ports: portTxt }) : '');
            } else {
                elCurState.textContent = _t('○ 未运行');
            }
            elCurState.className = 'lh-state' + (j.running ? ' run' : '');
            addNoise(j.noise);
            if (reset) renderAll(j.lines);
            else if (j.lines.length) append(j.lines);
            else updateCounts();
            elStatErr.textContent = '';
            return j;
        }).catch(function (e) {
            elStatErr.textContent = _t('读取失败: {msg}', { msg: e.message });
        });
    }

    function tick() {
        if (!alive) return;
        if (!paused && !document.hidden) loadOnce(false);
        else if (!document.hidden) refreshState();
        var now = Date.now();
        if (now - rateTick >= 2000) {
            rate = Math.round(rateN / ((now - rateTick) / 1000));
            rateN = 0; rateTick = now;
            elStatRate.textContent = rate ? _t('{n} 条/秒', { n: rate }) : '—';
        }
        setTimeout(tick, TAIL_MS);
    }

    // 暂停/只读状态栏：只刷运行状态，不动日志内容
    function refreshState() {
        api('/api/logs/tail?svc=' + encodeURIComponent(cur) + '&limit=50').then(function (j) {
            var portTxt = j.port ? String(j.port) : ((j.ports || []).join(',') || '');
            if (j.running) {
                var extra = (j.pid ? ' pid ' + j.pid : '') +
                            (portTxt ? ' · ' + _t('端口 {ports}', { ports: portTxt }) : '');
                elCurState.textContent = _t('● 运行中') + extra;
            } else if (j.state === 'starting') {
                elCurState.textContent = _t('◌ 启动中') +
                    (portTxt ? ' · ' + _t('端口 {ports} 未监听', { ports: portTxt }) : '');
            } else {
                elCurState.textContent = _t('○ 未运行');
            }
            elCurState.className = 'lh-state' + (j.running ? ' run' : '');
            elStatSize.textContent = _t('文件 {size}', { size: fmtSize(j.size) });
        }).catch(function () { /* 忽略：状态栏刷新失败不打扰 */ });
    }

    // ---------------- NapCat 二维码 ----------------
    var qrShown = '';
    function renderQr(it) {
        if (!it || !it.qr) { elQrBox.hidden = true; return; }
        elQrBox.hidden = false;
        var token = (it.qr.exists ? '?' : '') + 't=' + it.qr.mtime;
        if (qrShown !== it.qr.url + token) {
            qrShown = it.qr.url + token;
            if (it.qr.exists) {
                elQrImg.src = it.qr.url + token;
                elQrImg.style.display = '';
                elQrHint.textContent = _t('用手机 QQ 扫码登录（{time} 生成）',
                    { time: fmtTime(new Date(it.qr.mtime * 1000)) });
            } else {
                elQrImg.removeAttribute('src');
                elQrImg.style.display = 'none';
                elQrHint.textContent = _t('还没有二维码：点左侧 ▶ 启动 NapCat；若无需登录（已登录过）则不出现');
            }
        }
        if (it.webui) {
            elQrWebui.href = it.webui.url;
            elQrToken.textContent = it.webui.token ? _t('WebUI 令牌：{token}', { token: it.webui.token }) : '';
        }
    }

    // ---------------- 服务列表 ----------------
    var lastList = null;

    function rowSub(it) {
        var portTxt = it.port ? String(it.port) : ((it.ports || []).join(',') || '');
        if (it.running) {
            return _t('运行中 · {ports}', { ports: portTxt || '—' }) +
                   (it.pid ? ' · pid ' + it.pid : '');
        }
        if (it.state === 'starting') {
            return _t('启动中（端口 {ports} 未监听）', { ports: portTxt || '?' }) +
                   (it.proc_pid ? ' · pid ' + it.proc_pid : '');
        }
        return (it.log_exists ? fmtSize(it.size) + ' · ' : '') + _t('未运行');
    }

    function buildRow(it) {
        var row = document.createElement('div');
        row.className = 'lh-item';
        row.dataset.key = it.key;
        row.innerHTML =
            '<span class="lh-dot"></span>' +
            '<span class="lh-meta">' +
                '<span class="lh-name"></span>' +
                '<span class="lh-sub"></span>' +
            '</span>' +
            '<span class="lh-acts">' +
                '<button class="lh-act start" data-i18n-title="启动">▶</button>' +
                '<button class="lh-act stop" data-i18n-title="停止">■</button>' +
            '</span>';
        row.addEventListener('click', function (ev) {
            if (ev.target.closest('.lh-act')) return;
            select(it.key);
        });
        row.querySelector('.lh-act.start').addEventListener('click', function (ev) {
            ev.stopPropagation(); act('start', it.key);
        });
        row.querySelector('.lh-act.stop').addEventListener('click', function (ev) {
            ev.stopPropagation(); act('stop', it.key);
        });
        return row;
    }

    function updateRow(row, it) {
        row.classList.toggle('on', it.key === cur);
        row.dataset.running = it.running ? '1' : '0';
        var dot = row.querySelector('.lh-dot');
        if (dot) dot.className = 'lh-dot' + (it.running ? ' run' : '');
        var name = row.querySelector('.lh-name');
        var nameTxt = _t(it.name);
        if (name && name.textContent !== nameTxt) name.textContent = nameTxt;
        var sub = row.querySelector('.lh-sub');
        var subTxt = rowSub(it);
        if (sub && sub.textContent !== subTxt) sub.textContent = subTxt;
        var s = row.querySelector('.lh-act.start');
        var t = row.querySelector('.lh-act.stop');
        if (s && !s.querySelector('.lh-spin')) s.disabled = it.running || it.state === 'starting';
        if (t && !t.querySelector('.lh-spin')) t.disabled = false;
    }

    function renderList(items) {
        lastList = items;
        var seen = {};
        items.forEach(function (it) {
            seen[it.key] = 1;
            var row = elList.querySelector('.lh-item[data-key="' + it.key + '"]');
            if (!row) {
                row = buildRow(it);
                elList.appendChild(row);
            }
            updateRow(row, it);
        });
        Array.prototype.slice.call(elList.children).forEach(function (row) {
            if (!seen[row.dataset.key]) elList.removeChild(row);
        });
        if (window.I18n && I18n.applyStatic) I18n.applyStatic(elList);
        elTs.textContent = _t('更新 {time}', { time: fmtTime(new Date()) });
    }

    function refreshList(deep) {
        return api('/api/logs/services' + (deep ? '?deep=1' : '')).then(function (j) {
            renderList(j.items || []);
            var it = (j.items || []).filter(function (x) { return x.key === cur; })[0];
            renderQr(it);
        }).catch(function (e) {
            elStatErr.textContent = _t('服务列表读取失败: {msg}', { msg: e.message });
        });
    }

    // ---------------- 专用面板（CatPaws 控制台 / 手机摄像头） ----------------
    var PANEL_KEYS = { catpaw: 'CatPawsPanel', phone: 'CameraPanel' };
    var mountedPanel = '';

    function toggleLogUi(show) {
        if (elView) elView.style.display = show ? '' : 'none';
        if (elScenes) elScenes.style.display = show ? '' : 'none';
        if (elBudget) elBudget.style.display = show ? '' : 'none';
        if (elFilter) elFilter.style.display = show ? '' : 'none';
        var foot = document.querySelector('.lh-foot');
        if (foot) foot.style.display = show ? '' : 'none';
    }

    function unmountPanel() {
        ['CatPawsPanel', 'CameraPanel'].forEach(function (name) {
            var p = window[name];
            if (p && p.unmount) { try { p.unmount(); } catch (e) { /* ignore */ } }
        });
        mountedPanel = '';
        if (elPanel) { elPanel.innerHTML = ''; elPanel.hidden = true; }
    }

    function mountPanel(key) {
        var name = PANEL_KEYS[key];
        var panel = name ? window[name] : null;
        if (!panel || !elPanel) {
            unmountPanel();
            toggleLogUi(true);
            return;
        }
        if (mountedPanel === key) { toggleLogUi(false); return; }
        unmountPanel();
        mountedPanel = key;
        toggleLogUi(false);
        panel.mount(elPanel);
    }

    function select(key, force) {
        if (key === cur && !force) return;
        cur = key;
        mountPanel(key);
        var it = (lastList || []).filter(function (x) { return x.key === key; })[0];
        elCurName.textContent = it ? _t(it.name) : key;
        elCurFile.textContent = it ? it.log : '';
        elCurState.textContent = '—';
        elLines.innerHTML = '';
        elEmpty.style.display = '';
        elEmpty.textContent = _t('加载中…');
        offset = null;
        scene = '';
        onlyProblems = false;
        bgShown = false;
        closeDrawer();
        applyScenes();
        applyRawUi();
        resetCounts();
        elStatLines.textContent = _t('{n} 条事件', { n: 0 });
        elStatRate.textContent = '—';
        qrShown = '';
        renderQr(it);
        Array.prototype.forEach.call(elList.children, function (r) {
            r.classList.toggle('on', r.dataset.key === key);
        });
        loadOnce(true);
    }

    /** 只让"这一行"的按钮进入忙碌态，其它服务的按钮照常可点 */
    function setRowBusy(key, busy, what) {
        var row = elList.querySelector('.lh-item[data-key="' + key + '"]');
        if (!row) return;
        var s = row.querySelector('.lh-act.start');
        var t = row.querySelector('.lh-act.stop');
        if (busy) {
            if (s) { s.disabled = true; }
            if (t) { t.disabled = true; }
            var b = (what === 'start') ? s : t;
            if (b) b.innerHTML = '<i class="lh-spin"></i>';
        } else {
            if (s) { s.innerHTML = '▶'; s.disabled = row.dataset.running === '1'; }
            if (t) { t.innerHTML = '■'; t.disabled = false; }
        }
    }

    function busyBtn(btn, on) {
        if (!btn) return;
        if (!btn.dataset.label) btn.dataset.label = btn.innerHTML;
        if (on) { btn.disabled = true; btn.innerHTML = '<i class="lh-spin"></i>'; }
        else { btn.disabled = false; btn.innerHTML = btn.dataset.label; }
    }

    /** 停止后每 0.4 秒盯一次它的状态，真的没了就停转圈 */
    function waitGone(key, btn, nm, tries) {
        tries = tries || 0;
        api('/api/logs/tail?svc=' + encodeURIComponent(key) + '&limit=1').then(function (j) {
            if (!j.running) {
                busyBtn(btn, false);
                setRowBusy(key, false);
                toast(nm + '：' + _t('已停止'));
                return refreshList();
            }
            if (tries >= 30) {
                busyBtn(btn, false);
                setRowBusy(key, false);
                toast(nm + '：' + _t('已发出停止指令，进程还在释放资源'), false);
                return refreshList();
            }
            setTimeout(function () { waitGone(key, btn, nm, tries + 1); }, 400);
        }).catch(function () {
            busyBtn(btn, false);
            setRowBusy(key, false);
        });
    }

    /** 启动后盯端口：端口真的在监听才算就绪（SoVITS 冷启动约 50~60 秒） */
    function waitUp(key, btn, nm, tries) {
        tries = tries || 0;
        api('/api/logs/tail?svc=' + encodeURIComponent(key) + '&limit=1').then(function (j) {
            if (j.running) {
                busyBtn(btn, false);
                setRowBusy(key, false);
                toast(nm + '：' + _t('已就绪') +
                      (j.port ? ' · ' + _t('端口 {ports}', { ports: j.port }) : ''));
                return refreshList();
            }
            if (tries >= 120) {
                busyBtn(btn, false);
                setRowBusy(key, false);
                toast(nm + '：' + _t('还没就绪，请看日志（可能启动失败）'), true);
                return refreshList();
            }
            setTimeout(function () { waitUp(key, btn, nm, tries + 1); }, 1000);
        }).catch(function () {
            busyBtn(btn, false);
            setRowBusy(key, false);
        });
    }

    function act(what, key) {
        var it = (lastList || []).filter(function (x) { return x.key === key; })[0];
        var nm = it ? _t(it.name) : key;
        var tb = (key === cur) ? $(what === 'start' ? 'btnStart' : 'btnStop') : null;
        setRowBusy(key, true, what);
        busyBtn(tb, true);
        api('/api/logs/' + what + '?svc=' + encodeURIComponent(key), { method: 'POST' })
            .then(function (j) {
                var ok = !(j && j.status === 'error');
                toast(nm + '：' + ((j && j.message) || _t('完成')), !ok);
                if (!ok) { busyBtn(tb, false); setRowBusy(key, false); return refreshList(); }
                if (what === 'stop') waitGone(key, tb, nm, 0);
                else waitUp(key, tb, nm, 0);
            })
            .catch(function (e) {
                toast(nm + ' ' + _t(what === 'start' ? '启动' : '停止') + _t('失败: ') + e.message, true);
                busyBtn(tb, false);
                setRowBusy(key, false);
            });
    }

    // ---------------- 绑定 ----------------
    function buildScenes() {
        if (!elScenes) return;
        elScenes.innerHTML = '';
        SCENES.forEach(function (s) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'lh-scene' + (s[0] === '' ? ' on' : '');
            b.dataset.scene = s[0];
            b.innerHTML = '<i>' + s[2] + '</i><span>' + esc(_t(s[1])) + '</span>';
            b.addEventListener('click', function () {
                if (scene === s[0]) return;
                scene = s[0];
                applyScenes();
                refilter();
            });
            elScenes.appendChild(b);
        });
    }

    function bind() {
        elFilter.placeholder = _t('搜索：关键词，多个用 | 分隔');
        elEmpty.textContent = _t('选择左侧服务查看事件');
        buildScenes();
        applyScenes();
        applyRawUi();

        // 折叠预算按钮常驻重建会被每秒轮询替换，改用事件委托
        if (elBudget) {
            elBudget.addEventListener('click', function (e) {
                if (e.target && e.target.closest && e.target.closest('#btnBg')) toggleBg();
            });
        }

        if (elFilter) elFilter.setAttribute('autocomplete', 'off');
        elFilter.addEventListener('input', function () {
            clearTimeout(bind._t);
            bind._t = setTimeout(refilter, 400);
        });
        if (elOnlyProb) {
            elOnlyProb.addEventListener('click', function () {
                onlyProblems = !onlyProblems;
                applyScenes();
                refilter();
            });
        }
        if (elDrawer) {
            var close = $('drawerClose');
            if (close) close.addEventListener('click', closeDrawer);
            elDrawer.addEventListener('click', function (e) {
                if (e.target === elDrawer) closeDrawer();
            });
        }
        $('btnReload').addEventListener('click', function () {
            refreshList(true).then(function () { toast(_t('已刷新')); });
        });
        $('btnPause').addEventListener('click', function () {
            paused = !paused;
            this.textContent = _t(paused ? '继续' : '暂停');
            this.classList.toggle('lh-btn-primary', paused);
        });
        if ($('btnRaw')) $('btnRaw').addEventListener('click', toggleRaw);
        $('btnClear').addEventListener('click', function () {
            if (!confirm(_t('清空「{name}」的日志文件？', { name: elCurName.textContent }))) return;
            api('/api/logs/clear?svc=' + encodeURIComponent(cur), { method: 'POST' })
                .then(function (j) {
                    toast((j && j.message) || _t('已清空'));
                    offset = null; elLines.innerHTML = '';
                    loadOnce(true);
                })
                .catch(function (e) { toast(_t('清空失败: ') + e.message, true); });
        });
        $('btnStart').addEventListener('click', function () { act('start', cur); });
        $('btnStop').addEventListener('click', function () { act('stop', cur); });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeDrawer();
        });
        window.addEventListener('beforeunload', function () { alive = false; unmountPanel(); });
    }

    // ---------------- 启动 ----------------
    bind();
    window.Logs = { toast: toast, select: select, refreshList: refreshList };
    refreshList().then(function () {
        var wanted = '';
        try { wanted = new URLSearchParams(location.search).get('svc') || ''; } catch (e) { wanted = ''; }
        var known = (lastList || []).some(function (x) { return x.key === wanted; });
        select(known ? wanted : 'main', true);
        rateTick = Date.now();
        tick();
        setInterval(function () { if (!document.hidden) refreshList(); }, LIST_MS);
    });
})();
