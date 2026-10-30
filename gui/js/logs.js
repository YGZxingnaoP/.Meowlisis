/**
 * 日志中心前端（/logs）
 *
 * 拉取：1s 轮询 /api/logs/tail?svc=&since=<字节偏移>，只取新增内容。
 * 展示：后端已把每行解析成 {lv, ts, src, msg, txt, more, t}
 *   - t    转译后的人话（匹配不到规则则为空）
 *   - msg  去掉时间/来源/级别后的正文
 *   - txt  完整原始行（折叠在"原文"里，诊断用）
 *   - more 归并进来的续行数（异常堆栈）
 * 级别分成「日志 / 警告 / 错误」三个页签（另有"全部"），每个页签带计数。
 */
(function () {
    'use strict';

    var MAX_LINES = 4000;          // 页面最多保留多少行，防内存膨胀
    var TAIL_MS = 1000;            // 日志轮询间隔
    var LIST_MS = 3000;            // 服务状态轮询间隔

    var $ = function (id) { return document.getElementById(id); };

    function _t(s, vars) {
        try { if (window.I18n && I18n.text) return I18n.text(s, vars); } catch (e) { /* ignore */ }
        return s;
    }

    var elList = $('svcList'), elLines = $('lines'), elView = $('view');
    var elCurName = $('curName'), elCurState = $('curState'), elCurFile = $('curFile');
    var elFilter = $('filter'), elEmpty = $('empty'), elTabs = $('levelTabs');
    var elPanel = $('svcPanel');
    var elQrBox = $('qrBox'), elQrImg = $('qrImg'), elQrHint = $('qrHint');
    var elQrWebui = $('qrWebui'), elQrToken = $('qrToken');
    var elStatLines = $('statLines'), elStatSize = $('statSize'), elStatRate = $('statRate');
    var elStatErr = $('statErr'), elTs = $('tsInfo'), elAuto = $('autoScroll');

    var cur = 'main';              // 当前服务
    var offset = null;             // 已读到的字节偏移
    var paused = false;            // 暂停拉取
    var rate = 0, rateTick = 0, rateN = 0;
    var alive = true;
    var level = '';                // 当前级别页签：'' | 'INFO' | 'WARN' | 'ERROR'
    // 没有级别的行（第三方服务日志居多）归入「日志」一类
    var counts = { 'INFO': 0, 'WARN': 0, 'ERROR': 0 };

    function bucketOf(lv) {
        return (lv === 'WARN' || lv === 'ERROR') ? lv : 'INFO';
    }

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

    // ---------------- 过滤 ----------------
    // 过滤正则按"关键词"缓存：refilter 时会逐条问一遍，原来每问一条就 new 一次 RegExp
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
        if (level && bucketOf(rec.lv || '') !== level) return false;
        var re = filterRe();
        if (!re) return true;
        return re.test(rec.txt || rec.msg || '');
    }

    // ---------------- 计数（页签角标） ----------------
    function setBadge(id, n) {
        var el = $(id);
        if (el) el.textContent = n > 999 ? '999+' : String(n);
    }

    function updateCounts() {
        setBadge('cntAll', counts.INFO + counts.WARN + counts.ERROR);
        setBadge('cntINFO', counts.INFO);
        setBadge('cntWARN', counts.WARN);
        setBadge('cntERROR', counts.ERROR);
    }

    function resetCounts() {
        counts = { 'INFO': 0, 'WARN': 0, 'ERROR': 0 };
        updateCounts();
    }

    function applyTabs() {
        if (!elTabs) return;
        Array.prototype.forEach.call(elTabs.querySelectorAll('.lh-tab'), function (t) {
            t.classList.toggle('on', (t.dataset.lv || '') === level);
        });
    }

    // ---------------- 渲染 ----------------
    function atBottom() {
        return elView.scrollTop + elView.clientHeight >= elView.scrollHeight - 24;
    }

    function stick(wasBottom) {
        if (elAuto.checked && wasBottom) elView.scrollTop = elView.scrollHeight;
    }

    /** 一条日志 = 级别 + 摘要（转译后的人话，没有就用正文）+ 时间/来源 + 可折叠原文 */
    function lineNode(rec) {
        var lv = rec.lv || '';
        var d = document.createElement('div');
        d.className = 'lh-line' + (lv ? ' line-' + lv : '');

        // 转译命中 → 显示人话（有 key 值就拼成「短句：值」）；否则回退原始正文
        var seen = rec.t ? _t(rec.t) : '';
        if (seen && rec.d) seen += '：' + rec.d;
        var title = seen || rec.msg || rec.txt || '';
        var html = '<span class="lv">' + esc(lv) + '</span><div class="body">';
        html += '<div class="sum">' + esc(title);
        if (rec.n > 1) html += '<i class="more" title="' + esc(_t('相同内容合并了多少行')) + '">×' + rec.n + '</i>';
        if (rec.more) html += '<i class="more" title="' + esc(_t('展开原文可看到其余堆栈行')) + '">+' + rec.more + '</i>';
        html += '</div>';

        var meta = [];
        if (rec.ts) meta.push('<span class="ts">' + esc(rec.ts) + '</span>');
        if (rec.src) meta.push('<span class="src" title="' + esc(rec.src) + '">' + esc(shortSrc(rec.src)) + '</span>');
        if (meta.length) html += '<div class="meta">' + meta.join(' · ') + '</div>';

        if (rec.t) {
            html += '<details class="raw"><summary>' + esc(_t('原文')) + '</summary><pre>' + esc(rec.txt || '') + '</pre></details>';
        }
        html += '</div>';
        d.innerHTML = html;
        return d;
    }

    function append(records) {
        var keep = elAuto.checked ? atBottom() : false;
        var frag = document.createDocumentFragment(), added = 0;
        records.forEach(function (rec) {
            if (!lineOk(rec)) return;
            counts[bucketOf(rec.lv || '')]++;
            frag.appendChild(lineNode(rec));
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
        elStatLines.textContent = _t('{n} 行', { n: elLines.childElementCount });
    }

    function renderAll(records) {
        elLines.innerHTML = '';
        resetCounts();
        elEmpty.style.display = 'none';
        append(records);
        elView.scrollTop = elView.scrollHeight;      // 首次直接到底
    }

    function refilter() {
        // 过滤/页签变了就从头重新拉一次（简单可靠，日志量可控）
        offset = null;
        loadOnce(true);
    }

    // ---------------- 拉日志 ----------------
    function loadOnce(reset) {
        var q = '/api/logs/tail?svc=' + encodeURIComponent(cur) + '&limit=1500';
        if (offset !== null && !reset) q += '&since=' + offset;
        return api(q).then(function (j) {
            offset = j.offset;
            elStatSize.textContent = _t('文件 {size}', { size: fmtSize(j.size) });
            if (j.running) {
                var extra = (j.pid ? ' pid ' + j.pid : '') +
                            (j.ports && j.ports.length ? ' · ' + _t('端口 {ports}', { ports: j.ports.join(',') }) : '');
                elCurState.textContent = _t('● 运行中') + extra;
            } else {
                elCurState.textContent = _t('○ 未运行');
            }
            elCurState.className = 'lh-state' + (j.running ? ' run' : '');
            if (reset) renderAll(j.lines);
            else if (j.lines.length) append(j.lines);
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
            elStatRate.textContent = rate ? _t('{n} 行/秒', { n: rate }) : '—';
        }
        setTimeout(tick, TAIL_MS);
    }

    // 暂停/只读状态栏：只刷运行状态，不动日志内容
    function refreshState() {
        api('/api/logs/tail?svc=' + encodeURIComponent(cur) + '&limit=50').then(function (j) {
            if (j.running) {
                var extra = (j.pid ? ' pid ' + j.pid : '') +
                            (j.ports && j.ports.length ? ' · ' + _t('端口 {ports}', { ports: j.ports.join(',') }) : '');
                elCurState.textContent = _t('● 运行中') + extra;
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

    function renderList(items) {
        lastList = items;
        elList.innerHTML = '';
        items.forEach(function (it) {
            var row = document.createElement('div');
            row.className = 'lh-item' + (it.key === cur ? ' on' : '');
            row.dataset.key = it.key;
            row.dataset.running = it.running ? '1' : '0';
            var sub;
            if (it.running) {
                sub = (it.ports && it.ports.length)
                    ? _t('运行中 · {ports}', { ports: it.ports.join(',') })
                    : _t('运行中');
            } else {
                sub = it.log_exists ? fmtSize(it.size) : _t('未运行');
            }
            row.innerHTML =
                '<span class="lh-dot' + (it.running ? ' run' : '') + '"></span>' +
                '<span class="lh-meta">' +
                    '<span class="lh-name">' + esc(_t(it.name)) + '</span>' +
                    '<span class="lh-sub">' + esc(sub) + '</span>' +
                '</span>' +
                '<span class="lh-acts">' +
                    '<button class="lh-act start" data-i18n-title="启动">▶</button>' +
                    '<button class="lh-act stop" data-i18n-title="停止">■</button>' +
                '</span>';
            row.querySelector('.lh-act.start').disabled = it.running;
            // ■ 停止永不置灰：状态可能因"服务是手动启动的"而显示未运行，
            // 但后端会用命令行反查真的去找进程，所以必须让它点得动
            row.querySelector('.lh-act.stop').disabled = false;
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
            elList.appendChild(row);
        });
        if (window.I18n && I18n.applyStatic) I18n.applyStatic(elList);
        elTs.textContent = _t('更新 {time}', { time: fmtTime(new Date()) });
    }

    function refreshList(deep) {
        // deep=1：点 ⟳ 时让后端在后台重扫一遍命令行（认出手动启动的服务）
        return api('/api/logs/services' + (deep ? '?deep=1' : '')).then(function (j) {
            renderList(j.items || []);
            var it = (j.items || []).filter(function (x) { return x.key === cur; })[0];
            renderQr(it);              // 选中的是 NapCat 时同步二维码
        }).catch(function (e) {
            elStatErr.textContent = _t('服务列表读取失败: {msg}', { msg: e.message });
        });
    }

    // ---------------- 专用面板（CatPaws 控制台 / 手机摄像头） ----------------
    var PANEL_KEYS = { catpaw: 'CatPawsPanel', phone: 'CameraPanel' };
    var mountedPanel = '';

    function toggleLogUi(show) {
        if (elView) elView.style.display = show ? '' : 'none';
        if (elTabs) elTabs.style.display = show ? '' : 'none';
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
        resetCounts();
        elStatLines.textContent = _t('{n} 行', { n: 0 });
        elStatRate.textContent = '—';
        qrShown = '';                  // 强制重画二维码区
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
            if (tries >= 30) {                 // 最多盯 12 秒
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
                else { busyBtn(tb, false); setRowBusy(key, false); return refreshList(); }
            })
            .catch(function (e) {
                toast(nm + ' ' + _t(what === 'start' ? '启动' : '停止') + _t('失败: ') + e.message, true);
                busyBtn(tb, false);
                setRowBusy(key, false);
            });
    }

    // ---------------- 绑定 ----------------
    function bind() {
        elFilter.placeholder = _t('过滤关键字（支持 | 或）');
        elEmpty.textContent = _t('选择左侧服务查看日志');
        applyTabs();

        if (elFilter) elFilter.setAttribute('autocomplete', 'off');
        elFilter.addEventListener('input', function () {
            clearTimeout(bind._t);
            bind._t = setTimeout(refilter, 400);
        });
        if (elTabs) {
            elTabs.addEventListener('click', function (e) {
                var b = e.target.closest ? e.target.closest('.lh-tab') : null;
                if (!b) return;
                var lv = b.dataset.lv || '';
                if (lv === level) return;
                level = lv;
                applyTabs();
                refilter();
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
