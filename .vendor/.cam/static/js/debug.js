const modeEl = document.getElementById('mode');
const bufEl = document.getElementById('buf');
const updEl = document.getElementById('upd');
const metaEl = document.getElementById('meta');
const rowsEl = document.getElementById('rows');

function hhmmss(ts) {
  const d = new Date((ts || 0) * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
}

function render(d) {
  if (!d) return;
  modeEl.textContent = '模式 ' + (d.mode === 'call' ? '通话' : '聊天');
  modeEl.className = 'pill ' + (d.mode === 'call' ? 'on' : '');
  bufEl.textContent = '缓冲 ' + d.buffered_blocks + ' 块 / ' + d.buffered_bytes + ' 字节';
  updEl.textContent = '更新 ' + hhmmss(Date.now() / 1000);
  const meta = d.meta || {};
  metaEl.textContent = JSON.stringify(meta, null, 2) || '—';

  const log = d.log || [];
  const html = [];
  for (let i = log.length - 1; i >= 0; i--) {
    const r = log[i];
    html.push('<tr class="' + (r.kept ? 'yes' : 'no') + '">'
      + '<td>' + hhmmss(r.ts) + '</td>'
      + '<td>' + (r.mode === 'call' ? '通话' : '聊天') + '</td>'
      + '<td class="src">' + (r.source || '-') + '</td>'
      + '<td>' + (r.kept ? '是' : '否') + '</td>'
      + '<td>' + (r.bytes || 0) + '</td>'
      + '<td>' + (r.end ? '是' : '') + '</td>'
      + '<td class="txt">' + String(r.text || '').replace(/[<>&]/g, '') + '</td>'
      + '</tr>');
  }
  rowsEl.innerHTML = html.join('') || '<tr><td colspan="7">（暂无记录）</td></tr>';
}

function tick() {
  fetch('/api/tts/debug')
    .then((r) => r.json())
    .then(render)
    .catch(() => {
      updEl.textContent = '连接失败';
    });
}

tick();
setInterval(tick, 1000);
