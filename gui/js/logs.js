/**
 * 日志中心前端（/logs）
 *
 * 拉取策略：1s 轮询 /api/logs/tail?svc=&since=<字节偏移>，只取新增内容。
 * 比 SSE/WebSocket 简单，且不需要后端长连接（Flask 单线程下更稳）。
 * 首次不带 since，后端只回文件尾部（默认 192KB），避免几十 MB 老日志卡死页面。
 */
(function () {
    'use strict';

    var MAX_LINES = 4000;          // 页面最多保留多少行，防内存膨胀
    var TAIL_MS = 1000;            // 日志轮询间隔
    var LIST_MS = 3000;            // 服务状态轮询间隔

    var $ = function (id) { return document.getElementById(id); };
    var elList = $('svcList'), elLines = $('lines'), elView = $('view');
    var elCurName = $('curName'), elCurState = $('curState'), elCurFile = $('curFile');
    var elFilter = $('filter'), elLevel = $('level'), elEmpty = $('empty');
    var elQrBox = $('qrBox'), elQrImg = $('qrImg'), elQrHint = $('qrHint');
    var elQrWebui = $('qrWebui'), elQrToken = $('qrToken');
    var elStatLines = $('statLines'), elStatSize = $('statSize'), elStatRate = $('statRate');
    var elStatErr = $('statErr'), elTs = $('tsInfo'), elAuto = $('autoScroll');

    var cur = 'main';              // 当前服务
    var offset = null;             // 已读到的字节偏移
    var paused = false;            // 暂停拉取
    var rate = 0, rateTick = 0, rateN = 0;
    var alive = true;

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
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ---------------- 过滤 ----------------
    function filterRe() {
        var kw = (elFilter.value || '').trim();
        if (!kw) return null;
        var parts = kw.split('|').map(function (s) { return s.trim(); }).filter(Boolean);
        if (!parts.length) return null;
        try {
            return new RegExp(parts.map(function (p) {
                return p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            }).join('|'), 'i');
        } catch (e) { return null; }
    }

    function levelPass(lv) {
        var want = elLevel.value;
        if (!want) return true;
        var rank = { DEBUG: 1, INFO: 2, WARNING: 3, WARN: 3, ERROR: 4, CRITICAL: 5 };
        var need = want === 'WARNING' ? 3 : (want === 'INFO' ? 2 : 4);
        return (rank[lv] || 0) >= need;
    }

    function lineOk(rec) {
        if (!levelPass(rec.lv)) return false;
        var re = filterRe();
        return !re || re.test(rec.txt);
    }

    // ---------------- 渲染 ----------------
    function atBottom() {
        return elView.scrollTop + elView.clientHeight >= elView.scrollHeight - 24;
    }

    function stick(wasBottom) {
        if (elAuto.checked && wasBottom) elView.scrollTop = elView.scrollHeight;
    }

    function append(records) {
        var keep = elAuto.checked ? atBottom() : false;
        var frag = document.createDocumentFragment(), added = 0;
        records.forEach(function (rec) {
            if (!lineOk(rec)) return;
            var d = document.createElement('div');
            d.className = 'lh-line' + (rec.lv ? ' ' + rec.lv : '') +
                          (rec.lv === 'ERROR' || rec.lv === 'CRITICAL' ? ' line-ERROR' :
                           (rec.lv === 'WARNING' || rec.lv === 'WARN' ? ' line-WARNING' : ''));
            d.innerHTML = '<span class="lv">' + esc(rec.lv || '') + '</span>' +
                          '<span class="txt">' + esc(rec.txt) + '</span>';
            frag.appendChild(d);
            added++;
        });
        if (added) {
            elEmpty.style.display = 'none';
            elLines.appendChild(frag);
            var over = elLines.childElementCount - MAX_LINES;
            while (over-- > 0 && elLines.firstChild) elLines.removeChild(elLines.firstChild);
            rateN += added;
            stick(keep);
        }
        elStatLines.textContent = elLines.childElementCount + ' 行';
    }

    function renderAll(records) {
        elLines.innerHTML = '';
        elEmpty.style.display = 'none';
        append(records);
        elView.scrollTop = elView.scrollHeight;      // 首次直接到底
    }

    function refilter() {
        // 过滤条件变了就从头重新拉一次（简单可靠，日志量可控）
        offset = null;
        loadOnce(true);
    }

    // ---------------- 拉日志 ----------------
    function loadOnce(reset) {
        var q = '/api/logs/tail?svc=' + encodeURIComponent(cur) + '&limit=1500';
        if (offset !== null && !reset) q += '&since=' + offset;
        return api(q).then(function (j) {
            offset = j.offset;
            elStatSize.textContent = '文件 ' + fmtSize(j.size);
            elCurState.textContent = j.running
                ? ('● 运行中' + (j.pid ? ' pid ' + j.pid : '') +
                   (j.ports && j.ports.length ? ' · 端口 ' + j.ports.join(',') : ''))
                : '○ 未运行';
            elCurState.className = 'lh-state' + (j.running ? ' run' : '');
            if (reset) renderAll(j.lines);
            else if (j.lines.length) append(j.lines);
            elStatErr.textContent = '';
            return j;
        }).catch(function (e) {
            elStatErr.textContent = '读取失败: ' + e.message;
        });
    }

    function tick() {
        if (!alive) return;
        if (!paused && !document.hidden) loadOnce(false);
        var now = Date.now();
        if (now - rateTick >= 2000) {
            rate = Math.round(rateN / ((now - rateTick) / 1000));
            rateN = 0; rateTick = now;
            elStatRate.textContent = rate ? rate + ' 行/秒' : '—';
        }
        setTimeout(tick, TAIL_MS);
    }

    // ---------------- NapCat 二维码 ----------------
    /**
     * 只有选中的服务带 qr 信息（目前是 NapCat）才显示。
     * 图片地址用 mtime 当缓存串：NapCat 换了二维码 mtime 就变，
     * 刷新服务列表时自然会拉到新图，不需要轮询图片本身。
     */
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
                elQrHint.textContent = '用手机 QQ 扫码登录（' +
                    new Date(it.qr.mtime * 1000).toLocaleTimeString('zh-CN', { hour12: false }) + ' 生成）';
            } else {
                elQrImg.removeAttribute('src');
                elQrImg.style.display = 'none';
                elQrHint.textContent = '还没有二维码：点左侧 ▶ 启动 NapCat，' +
                    '若无需登录（已登录过）则不出现';
            }
        }
        if (it.webui) {
            elQrWebui.href = it.webui.url;
            elQrToken.textContent = it.webui.token ? ('WebUI 令牌：' + it.webui.token) : '';
        }
    }

    // ---------------- 服务列表 ----------------
    var lastList = null;

    function renderList(items, patched) {
        lastList = items;
        elList.innerHTML = '';
        items.forEach(function (it) {
            var row = document.createElement('div');
            row.className = 'lh-item' + (it.key === cur ? ' on' : '');
            row.dataset.key = it.key;
            row.innerHTML =
                '<span class="lh-dot' + (it.running ? ' run' : '') + '"></span>' +
                '<span class="lh-meta">' +
                    '<span class="lh-name">' + esc(it.name) + '</span>' +
                    '<span class="lh-sub">' + (it.running
                        ? (it.ports && it.ports.length ? '运行中 · ' + it.ports.join(',') : '运行中')
                        : (it.log_exists ? fmtSize(it.size) : '未运行')) + '</span>' +
                '</span>' +
                '<span class="lh-acts">' +
                    '<button class="lh-act start" title="启动">▶</button>' +
                    '<button class="lh-act stop" title="停止">■</button>' +
                '</span>';
            row.querySelector('.lh-act.start').disabled = it.running;
            // ■ 停止永不置灰：状态可能因为服务是"手动启动的"而显示未运行，
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
        elTs.textContent = '更新 ' + new Date().toLocaleTimeString('zh-CN', { hour12: false });
        if (patched && patched.length === 0) {
            elStatErr.textContent = '提示：启动端点尚未被 loghub 接管（config_gui.py 未打补丁）';
        }
    }

    function refreshList() {
        return api('/api/logs/services').then(function (j) {
            renderList(j.items, j.patched);
            var it = (j.items || []).filter(function (x) { return x.key === cur; })[0];
            renderQr(it);              // 选中的是 NapCat 时同步二维码
        }).catch(function (e) {
            elStatErr.textContent = '服务列表读取失败: ' + e.message;
        });
    }

    function select(key) {
        if (key === cur) return;
        cur = key;
        var it = (lastList || []).filter(function (x) { return x.key === key; })[0];
        elCurName.textContent = it ? it.name : key;
        elCurFile.textContent = it ? it.log : '';
        elCurState.textContent = '—';
        elLines.innerHTML = '';
        elEmpty.style.display = '';
        elEmpty.textContent = '加载中…';
        offset = null;
        elStatLines.textContent = '0 行';
        elStatRate.textContent = '—';
        qrShown = '';                  // 强制重画二维码区
        renderQr(it);
        Array.prototype.forEach.call(elList.children, function (r) {
            r.classList.toggle('on', r.dataset.key === key);
        });
        loadOnce(true);
    }

    function act(what, key) {
        var it = (lastList || []).filter(function (x) { return x.key === key; })[0];
        var nm = it ? it.name : key;
        var btns = elList.querySelectorAll('.lh-act');
        Array.prototype.forEach.call(btns, function (b) { b.disabled = true; });
        api('/api/logs/' + what + '?svc=' + encodeURIComponent(key), { method: 'POST' })
            .then(function (j) {
                toast(nm + '：' + (j.message || (what === 'start' ? '已启动' : '已停止')));
                setTimeout(refreshList, 600);
            })
            .catch(function (e) {
                toast(nm + ' ' + (what === 'start' ? '启动' : '停止') + '失败: ' + e.message, true);
                refreshList();
            });
    }

    // ---------------- 绑定 ----------------
    function bind() {
        elFilter.addEventListener('input', function () {
            clearTimeout(bind._t);
            bind._t = setTimeout(refilter, 400);
        });
        elLevel.addEventListener('change', refilter);
        $('btnReload').addEventListener('click', function () {
            refreshList().then(function () { toast('已刷新'); });
        });
        $('btnPause').addEventListener('click', function () {
            paused = !paused;
            this.textContent = paused ? '继续' : '暂停';
            this.classList.toggle('lh-btn-primary', paused);
        });
        $('btnClear').addEventListener('click', function () {
            if (!confirm('清空「' + elCurName.textContent + '」的日志文件？')) return;
            api('/api/logs/clear?svc=' + encodeURIComponent(cur), { method: 'POST' })
                .then(function (j) {
                    toast(j.message || '已清空');
                    offset = null; elLines.innerHTML = '';
                    loadOnce(true);
                })
                .catch(function (e) { toast('清空失败: ' + e.message, true); });
        });
        $('btnStart').addEventListener('click', function () { act('start', cur); });
        $('btnStop').addEventListener('click', function () { act('stop', cur); });
        window.addEventListener('beforeunload', function () { alive = false; });
    }

    // ---------------- 启动 ----------------
    bind();
    refreshList().then(function () {
        select(cur = 'main');
        rateTick = Date.now();
        tick();
        setInterval(function () { if (!document.hidden) refreshList(); }, LIST_MS);
    });
})();
