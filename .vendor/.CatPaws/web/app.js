(() => {
  const pillDevice = document.getElementById('pill-device');
  const pillSession = document.getElementById('pill-session');
  const pillStream = document.getElementById('pill-stream');
  const goalInput = document.getElementById('goal');
  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnStream = document.getElementById('btn-stream');
  const btnShot = document.getElementById('btn-shot');
  const askBox = document.getElementById('ask');
  const askQ = document.getElementById('askQ');
  const askInput = document.getElementById('askInput');
  const askSend = document.getElementById('askSend');

  let viewerReady = false;
  let streamOn = false;
  let busy = false;

  function pill(node, text, state) {
    node.textContent = text;
    node.className = 'pill ' + (state || '');
  }

  async function post(path, body) {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    try { return await response.json(); } catch (e) { return {}; }
  }

  function updateViewer(config, relay) {
    if (viewerReady) return;
    if (!config || !relay) return;
    viewerReady = true;
    CWViewer.setTarget({ host: location.hostname, port: relay.port || config.relay_port,
      token: relay.token || '' });
    CWViewer.connect();
  }

  function renderStatus(status) {
    const device = (status.device || {}).info || {};
    const screen = device.screen || {};
    const mockText = (status.config || {}).device && status.config.device.mock ? ' · mock' : '';
    if (status.device && status.device.error) {
      pill(pillDevice, '设备离线', 'off');
    } else {
      const pixel = (screen.pixel || []).join('x');
      pill(pillDevice, '设备 ' + (pixel || '就绪') + mockText, 'on');
    }
    const session = status.session || {};
    if (session.phase === 'running') pill(pillSession, '链路运行中 ' + (session.elapsed_sec || 0) + 's', 'busy');
    else if (session.phase === 'reflecting') pill(pillSession, '复盘中…', 'busy');
    else pill(pillSession, '链路空闲', '');
    const relay = status.relay || {};
    pill(pillStream, '视频 ' + (relay.device_online ? '已连' : '未连') + ' · ' +
      (relay.streaming ? relay.fps + 'fps' : '关'), relay.streaming ? 'on' : '');
    streamOn = !!relay.streaming;
    btnStream.textContent = streamOn ? '视频关' : '视频开';
    busy = !!status.agent_busy;
    btnStart.disabled = busy;
    const question = status.pending_question;
    if (question && question.question) {
      askBox.classList.remove('hidden');
      askQ.textContent = '❓ ' + question.question;
      if (document.activeElement !== askInput) askInput.focus();
    } else {
      askBox.classList.add('hidden');
    }
    updateViewer(status.config, relay);
  }

  async function refresh() {
    try {
      const response = await fetch('/cw/status');
      renderStatus(await response.json());
    } catch (e) {}
  }

  btnStart.addEventListener('click', async () => {
    const goal = goalInput.value.trim();
    if (!goal) { goalInput.focus(); return; }
    const result = await post('/cw/start', { goal });
    if (!result.ok) alert(result.message || '启动失败');
    refresh();
  });

  btnStop.addEventListener('click', async () => {
    await post('/cw/stop', { reason: 'web' });
    refresh();
  });

  btnStream.addEventListener('click', async () => {
    await post('/cw/stream', { on: !streamOn });
    refresh();
  });

  btnShot.addEventListener('click', () => {
    window.open('/cw/screenshot?t=' + Date.now(), '_blank');
  });

  askSend.addEventListener('click', async () => {
    const text = askInput.value.trim();
    askInput.value = '';
    await post('/cw/answer', { text });
    refresh();
  });

  askInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') askSend.click();
  });

  goalInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !busy) btnStart.click();
  });

  setInterval(refresh, 1500);
  refresh();
  CWTimeline.start(900);
})();
