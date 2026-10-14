/**
 * 画图 / 语音 进度卡片（日志中心内，数据全部来自真实日志）
 *
 * 数据源：GET /api/logs/progress
 *   绘画 → logs/comfy_engine.log 的 tqdm 行（百分比/步进/已用/预计）
 *          + 当日主日志的 [flux_painter] 阶段行（档位/提示词/已提交/异常）
 *   语音 → 当日主日志的「播放片段 N」/ 字幕 JSON（chatStatus + text）/ 打断行
 * 不连接原项目的任何 WebSocket，不修改原项目任何文件。
 */
(function () {
    'use strict';

    var elPaint = document.getElementById('progPaint');
    var elTts = document.getElementById('progTts');
    if (!elPaint || !elTts) return;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function fmtAge(sec) {
        if (sec == null) return '—';
        if (sec < 2) return '刚刚';
        if (sec < 60) return sec + ' 秒前';
        if (sec < 3600) return Math.round(sec / 60) + ' 分钟前';
        return Math.round(sec / 3600) + ' 小时前';
    }

    function fmtDur(sec) {
        if (sec == null || sec < 0) return '—';
        var m = Math.floor(sec / 60), s = Math.round(sec % 60);
        return m + ':' + (s < 10 ? '0' : '') + s;
    }

    function barHtml(pct, cls) {
        var w = Math.max(0, Math.min(100, pct || 0));
        return '<div class="pg-bar ' + (cls || '') + '"><i style="width:' + w + '%"></i>' +
               '<span>' + (pct == null ? '—' : pct + '%') + '</span></div>';
    }

    function row(k, v) {
        return '<div class="pg-row"><span class="pg-k">' + esc(k) + '</span><span class="pg-v">' + v + '</span></div>';
    }

    var PAINT_STATE = { idle: '空闲', running: '绘制中', done: '已完成', error: '出错' };
    var TTS_STATE = { idle: '空闲', synth: '合成中', playing: '播放中', interrupted: '被打断' };

    function renderPaint(d) {
        d = d || { state: 'idle' };
        var st = PAINT_STATE[d.state] || d.state;
        var h = '<div class="pg-head"><b>🎨 画图</b>' +
                '<span class="pg-state s-' + esc(d.state) + '">' + esc(st) + '</span>' +
                '<span class="pg-age">' + esc(fmtAge(d.age)) + '</span></div>';
        if (d.state === 'running' || d.state === 'done') {
            h += barHtml(d.percent, d.state === 'done' ? 'ok' : '');
            h += row('阶段', esc(d.stage || '—') + (d.detail ? ' · ' + esc(d.detail) : ''));
            h += row('步进', esc(d.step || '—') + (d.rate ? ' · ' + esc(d.rate) : ''));
            h += row('已用 / 预计', esc(fmtDur(d.elapsed)) + ' / ' + esc(fmtDur(d.eta)));
        } else if (d.state === 'error') {
            h += row('原因', esc(d.stage || d.detail || '绘制失败'));
        } else {
            h += '<div class="pg-empty">当前没有绘图任务</div>';
        }
        elPaint.innerHTML = h;
    }

    function renderTts(d) {
        d = d || { state: 'idle' };
        var st = TTS_STATE[d.state] || d.state;
        var seg = d.seg ? ('片段 ' + d.seg + (d.total ? ' / ' + d.total : '')) : '—';
        var h = '<div class="pg-head"><b>🔊 语音</b>' +
                '<span class="pg-state s-' + esc(d.state) + '">' + esc(st) + '</span>' +
                '<span class="pg-age">' + esc(fmtAge(d.age)) + '</span></div>';
        if (d.state === 'playing' || d.state === 'synth') {
            h += barHtml(d.total ? Math.round((d.seg || 0) * 100 / d.total) : null, 'soft');
            h += row('进度', esc(seg));
            h += row('正在念', d.text ? '「' + esc(d.text) + '」' : '—');
        } else if (d.state === 'interrupted') {
            h += row('状态', '主人说话了，已停下');
        } else {
            h += '<div class="pg-empty">当前没有语音在播</div>';
        }
        elTts.innerHTML = h;
    }

    var failN = 0;

    function tick() {
        var wait = 1000;
        fetch('/api/logs/progress', { cache: 'no-store' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (j) {
                failN = 0;
                renderPaint(j.paint);
                renderTts(j.tts);
            })
            .catch(function (e) {
                failN++;
                wait = failN > 3 ? 30000 : (failN > 1 ? 5000 : 1000);
                if (failN === 1) {
                    var m = '<div class="pg-empty">进度接口取不到（' + esc(e.message) +
                            '）：后端进程还没重启，重启 config_gui 后自动恢复</div>';
                    elPaint.innerHTML = m;
                    elTts.innerHTML = m;
                }
            })
            .then(function () { setTimeout(tick, wait); });
    }

    tick();
})();
