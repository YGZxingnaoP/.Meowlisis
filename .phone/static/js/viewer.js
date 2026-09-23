import { Bus } from './ws.js';
import { MonitorAudio } from './monaudio.js';

const canvas = document.getElementById('view');
const frameEl = document.getElementById('frame');
const ctx2d = canvas.getContext('2d');
const metaEl = document.getElementById('meta');
const idleEl = document.getElementById('idle');
const sndBtn = document.getElementById('sndBtn');

const mon = new MonitorAudio();

const bus = new Bus('viewer');
let decoder = null;
let codecName = '';
let needKey = true;
let size = null;

let decoded = 0;
let fpsTs = performance.now();

function setMeta(text) {
  metaEl.textContent = text;
}

function setIdle(show) {
  idleEl.classList.toggle('hidden', !show);
}

function fitFrame(w, h) {
  const pad = 28;
  const availW = Math.max(160, window.innerWidth - pad);
  const availH = Math.max(120, window.innerHeight - pad);
  const scale = Math.min(availW / w, availH / h, 1);
  frameEl.style.width = Math.max(120, Math.round(w * scale)) + 'px';
  frameEl.style.height = Math.max(90, Math.round(h * scale)) + 'px';
}

function applySize(w, h) {
  if (!(w > 0) || !(h > 0)) return;
  if (size && size[0] === w && size[1] === h) return;
  size = [w, h];
  canvas.width = w;
  canvas.height = h;
  fitFrame(w, h);
}

function candidatesFor(name) {
  const base = { codec: name };
  return [
    Object.assign({}, base, { hardwareAcceleration: 'prefer-hardware', optimizeForLatency: true }),
    Object.assign({}, base, { optimizeForLatency: true }),
    base
  ];
}

async function configure(name) {
  closeDecoder();
  needKey = true;
  if (typeof VideoDecoder === 'undefined') {
    setIdle(true);
    setMeta('浏览器不支持 WebCodecs');
    return;
  }
  let chosen = null;
  for (const cand of candidatesFor(name)) {
    try {
      const res = await VideoDecoder.isConfigSupported(cand);
      if (res && res.supported) {
        chosen = cand;
        break;
      }
    } catch (e) {
      chosen = cand;
      break;
    }
  }
  if (!chosen) {
    setIdle(true);
    setMeta('解码配置不受支持：' + name);
    return;
  }
  decoder = new VideoDecoder({
    output: (frame) => onFrame(frame),
    error: () => {
      needKey = true;
      requestKey();
    }
  });
  decoder.configure(chosen);
  codecName = name;
  setIdle(true);
  setMeta(name + ' · 等待画面…');
  requestKey();
}

function closeDecoder() {
  if (!decoder) return;
  try {
    decoder.close();
  } catch (e) {}
  decoder = null;
}

function requestKey() {
  bus.send({ t: 'reqkey' });
}

function onFrame(frame) {
  try {
    const w = frame.displayWidth || frame.codedWidth;
    const h = frame.displayHeight || frame.codedHeight;
    applySize(w, h);
    ctx2d.drawImage(frame, 0, 0, canvas.width, canvas.height);
    setIdle(false);
  } catch (e) {
  } finally {
    try {
      frame.close();
    } catch (e) {}
  }
  decoded += 1;
  const now = performance.now();
  if (now - fpsTs >= 1000) {
    const fps = Math.round((decoded * 1000) / (now - fpsTs));
    decoded = 0;
    fpsTs = now;
    if (size) setMeta(codecName + ' · ' + size[0] + 'x' + size[1] + ' · ' + fps + 'fps');
  }
}

function onBinary(buf) {
  const data = new Uint8Array(buf);
  if (data[0] === 0x03) {
    mon.feed(buf);
    return;
  }
  if (!decoder || buf.byteLength < 10) return;
  const flags = data[0];
  const dv = new DataView(buf);
  const ts = Number(dv.getBigUint64(1, false));
  const isKey = (flags & 0x01) === 1;
  if (!isKey && needKey) return;
  if (isKey) needKey = false;
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

bus.onText((msg) => {
  if (!msg) return;
  if (msg.t === 'vcfg') {
    configure(msg.codec);
  } else if (msg.t === 'vstop') {
    closeDecoder();
    size = null;
    ctx2d.clearRect(0, 0, canvas.width, canvas.height);
    setIdle(true);
    setMeta('手机摄像头已关闭');
  } else if (msg.t === 'hello') {
    setMeta('已连接，等待画面…');
  }
});

bus.onBin((buf) => onBinary(buf));

bus.onStatus((ok) => {
  if (!ok) {
    closeDecoder();
    setIdle(true);
    setMeta('连接断开，重连中…');
  }
});

function syncSnd() {
  if (!sndBtn) return;
  sndBtn.textContent = mon.on ? '🔊' : '🔇';
  sndBtn.classList.toggle('on', mon.on);
  sndBtn.title = mon.on
    ? '手机声音已开（点击关闭）'
    : (mon.ctx && mon.ctx.state === 'suspended'
      ? '点击画面或此按钮开启手机声音' : '手机声音已关（点击开启）');
}

function setMonitor(on) {
  if (on) mon.unlock();
  else mon.mute();
  syncSnd();
  bus.send({ t: 'audio', on: on ? 1 : 0 });
}

if (sndBtn) {
  sndBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    setMonitor(!mon.on);
  });
}

// 自动解锁只做一次，且点"声音按钮"时跳过（否则会与按钮的开关互相打架）
let autoUnlocked = false;
document.addEventListener('pointerdown', (e) => {
  if (autoUnlocked) return;
  autoUnlocked = true;
  if (sndBtn && (e.target === sndBtn || sndBtn.contains(e.target))) return;
  if (!mon.on) setMonitor(true);
});

window.addEventListener('resize', () => {
  if (size) fitFrame(size[0], size[1]);
});

bus.connect();
setIdle(true);
setMeta('连接中…');
setMonitor(true);
