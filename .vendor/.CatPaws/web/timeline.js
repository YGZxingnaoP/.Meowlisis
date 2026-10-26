const CWTimeline = (() => {
  const list = document.getElementById('log');
  let lastSeq = 0;
  let session = '';
  let timer = null;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function head(item) {
    const row = el('div', 'head');
    row.appendChild(el('span', '', (item.ts || '').slice(11, 19)));
    row.appendChild(el('span', '', item.kind || ''));
    return row;
  }

  function describeEntry(item) {
    const kind = item.kind || '';
    if (kind === 'tool_call') return item.tool + ' ' + JSON.stringify(item.args || {});
    if (kind === 'phase') return '阶段 → ' + item.phase + (item.reason ? '（' + item.reason + '）' : '')
      + (item.goal ? ' 目标：' + item.goal : '');
    if (kind === 'single' || kind === 'sequence') {
      const body = item.action || (item.steps || []).join(' → ');
      return body + (item.ok ? '  ✅ ' + (item.elapsed_ms || 0) + 'ms'
        : '  ❌ ' + (item.code || '') + ' ' + (item.message || ''));
    }
    if (kind === 'action_start') return '执行 action：' + (item.action_id || '') + ' ' + (item.title || '');
    if (kind === 'action_finish') return 'action ' + (item.action_id || '') + (item.ok ? ' 成功' : ' 失败')
      + (item.message ? '：' + item.message : '');
    if (kind === 'action_created') return '新建 action：' + (item.action_id || '');
    if (kind === 'action_updated') return '更新 action：' + (item.action_id || '') + ' v' + (item.version || '');
    if (kind === 'observe') {
      if (item.mode === 'image') return '截图观察 ' + ((item.screen || {}).pixel || []).join('x');
      return 'OCR观察 ' + ((item.texts || []).slice(0, 8).join(' / ')) + (item.sensitive ? '  ⚠ ' + item.sensitive : '');
    }
    if (kind === 'assistant') return item.text || '';
    if (kind === 'ask') return '❓ ' + (item.question || '');
    if (kind === 'answer') return '💬 ' + (item.answer ? item.answer : '（无回答）');
    if (kind === 'script_log' || kind === 'script_output') return '[脚本] ' + (item.text || '');
    if (kind === 'script_stderr') return '[脚本错误] ' + (item.text || '');
    if (kind === 'stop' || kind === 'stop_request') return '🛑 停止（' + (item.reason || '') + '）';
    if (kind === 'error') return '⚠ ' + (item.code || '') + ' ' + (item.message || '');
    if (kind === 'thumb') return '';
    if (kind === 'relay') return '中继 ' + (item.action || '');
    return JSON.stringify(item).slice(0, 300);
  }

  function cls(item) {
    const kind = item.kind || '';
    if (kind === 'single' || kind === 'sequence' || kind === 'action_finish') return item.ok ? 'item ok' : 'item bad';
    if (kind === 'phase') return 'item phase';
    if (kind === 'ask' || kind === 'answer') return 'item ask';
    if (kind === 'assistant') return 'item say';
    if (kind === 'error' || kind === 'stop') return 'item bad';
    return 'item';
  }

  function append(item) {
    if (item.kind === 'thumb') {
      const img = document.createElement('img');
      img.src = '/' + (item.path || '');
      list.appendChild(img);
      return;
    }
    const text = describeEntry(item);
    if (!text) return;
    const node = el('div', cls(item));
    node.appendChild(head(item));
    node.appendChild(el('div', 'body', text));
    list.appendChild(node);
    if (item.kind === 'phase' && item.phase === 'running') list.textContent = '';
  }

  async function poll() {
    try {
      const response = await fetch('/cw/ops?limit=300');
      const data = await response.json();
      const items = data.items || [];
      if (items.length && items[0].session && items[0].session !== session) {
        session = items[0].session;
        lastSeq = 0;
        list.textContent = '';
      }
      for (const item of items) {
        if (item.kind === 'thumb') continue;
        if ((item.seq || 0) <= lastSeq) continue;
        lastSeq = item.seq || lastSeq;
        append(item);
      }
      list.scrollTop = list.scrollHeight;
    } catch (e) {}
  }

  function start(interval) {
    if (timer) clearInterval(timer);
    timer = setInterval(poll, interval || 900);
    poll();
  }

  function clear() {
    list.textContent = '';
    lastSeq = 0;
  }

  return { start, clear, poll };
})();
