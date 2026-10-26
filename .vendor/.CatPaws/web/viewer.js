const CWViewer = (() => {
  const canvas = document.getElementById('view');
  const idle = document.getElementById('idle');
  const metaEl = document.getElementById('meta');
  const ctx = canvas.getContext('2d');

  let ws = null;
  let decoder = null;
  let needKey = true;
  let codec = '';
  let size = null;
  let target = { host: location.hostname, port: 8081, token: '' };
  let closing = false;
  let retry = 0;
  let decoded = 0;
  let lastReport = performance.now();

  function setMeta(text) { metaEl.textContent = text; }
  function setIdle(show) { idle.classList.toggle('hidden', !show); }

  function fit(w, h) {
    const box = canvas.parentElement.getBoundingClientRect();
    const scale = Math.min((box.width - 24) / w, (box.height - 24) / h, 1);
    canvas.style.width = Math.max(80, Math.round(w * scale)) + 'px';
    canvas.style.height = Math.max(60, Math.round(h * scale)) + 'px';
  }

  function applySize(w, h) {
    if (!w || !h) return;
    if (size && size[0] === w && size[1] === h) return;
    size = [w, h];
    canvas.width = w;
    canvas.height = h;
    fit(w, h);
  }

  function closeDecoder() {
    if (!decoder) return;
    try { decoder.close(); } catch (e) {}
    decoder = null;
    needKey = true;
  }

  function requestKey() {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ t: 'reqkey' }));
  }

  async function configure(name) {
    closeDecoder();
    if (typeof VideoDecoder === 'undefined') {
      setMeta('浏览器不支持 WebCodecs');
      return;
    }
    codec = name;
    const candidates = [
      { codec: name, avc: { format: 'annexb' }, optimizeForLatency: true },
      { codec: name, optimizeForLatency: true },
      { codec: name }
    ];
    let chosen = null;
    for (const candidate of candidates) {
      try {
        const support = await VideoDecoder.isConfigSupported(candidate);
        if (support && support.supported) { chosen = candidate; break; }
      } catch (e) {}
    }
    if (!chosen) {
      setMeta('解码配置不受支持：' + name);
      return;
    }
    decoder = new VideoDecoder({
      output: onFrame,
      error: () => { needKey = true; requestKey(); }
    });
    decoder.configure(chosen);
    needKey = true;
    setMeta(name + ' · 等待关键帧…');
    requestKey();
  }

  function onFrame(frame) {
    try {
      const w = frame.displayWidth || frame.codedWidth;
      const h = frame.displayHeight || frame.codedHeight;
      applySize(w, h);
      ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
      setIdle(false);
      decoded += 1;
      const now = performance.now();
      if (now - lastReport > 1000) {
        setMeta(codec + ' · ' + w + 'x' + h + ' · ' + decoded + 'fps');
        decoded = 0;
        lastReport = now;
      }
    } finally {
      try { frame.close(); } catch (e) {}
    }
  }

  function onBinary(buffer) {
    if (!decoder || buffer.byteLength < 10) return;
    const data = new Uint8Array(buffer);
    const isKey = (data[0] & 0x01) === 1;
    if (!isKey && needKey) return;
    if (!isKey) {
      try { if ((decoder.decodeQueueSize || 0) > 6) return; } catch (e) {}
    }
    if (isKey) needKey = false;
    const view = new DataView(buffer);
    const ts = Number(view.getBigUint64(1, false));
    try {
      decoder.decode(new EncodedVideoChunk({
        type: isKey ? 'key' : 'delta',
        timestamp: ts,
        data: data.subarray(9)
      }));
    } catch (e) {
      needKey = true;
      requestKey();
    }
  }

  function schedule() {
    if (closing) return;
    retry = Math.min(retry + 1, 6);
    setTimeout(connect, 500 * retry);
  }

  function connect() {
    if (closing) return;
    const url = 'ws://' + target.host + ':' + target.port + '/ws?role=viewer&src=screen&token='
      + encodeURIComponent(target.token || '');
    let socket;
    try { socket = new WebSocket(url); } catch (e) { schedule(); return; }
    ws = socket;
    socket.binaryType = 'arraybuffer';
    socket.onopen = () => {
      retry = 0;
      socket.send(JSON.stringify({ t: 'hello', role: 'viewer', src: 'screen' }));
      setMeta('已连接中继，等待画面…');
    };
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        let msg = null;
        try { msg = JSON.parse(event.data); } catch (e) { return; }
        if (msg.t === 'vcfg' && msg.codec) configure(msg.codec);
        else if (msg.t === 'vstop') { closeDecoder(); setIdle(true); setMeta('手机已停止推流'); }
        else if (msg.t === 'hello') setMeta('已连接中继，等待画面…');
        return;
      }
      onBinary(event.data);
    };
    socket.onclose = () => { ws = null; schedule(); };
    socket.onerror = () => {};
  }

  function setTarget(next) {
    const changed = next.host !== target.host || next.port !== target.port
      || next.token !== target.token;
    target = Object.assign({}, target, next);
    if (changed) { close(); connect(); }
  }

  function close() {
    closing = true;
    closeDecoder();
    if (ws) { try { ws.close(); } catch (e) {} }
    ws = null;
    setTimeout(() => { closing = false; }, 50);
  }

  window.addEventListener('resize', () => { if (size) fit(size[0], size[1]); });
  setIdle(true);

  return { connect, close, setTarget, requestKey, setMeta };
})();
