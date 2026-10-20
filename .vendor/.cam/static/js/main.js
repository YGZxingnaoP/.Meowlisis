import { Bus } from './ws.js';
import { Player } from './player.js';
import { Camera } from './camera.js';
import { Mic } from './audio.js';
import { Chat } from './chat.js';
import { Bubble } from './bubble.js';
import { Say } from './say.js';
import { Mode } from './mode.js';

const NAME_KEY = 'phone_username';
// 手机端身份 = 用户编号（000001 / temp-000001），昵称由主项目解析后回填显示
const PHONE_UID_RE = /^(\d{6}|temp-\d{6})$/;
const PHONE_DEFAULT_NAME = '手机用户';
let username = (() => {
  try {
    const saved = String(localStorage.getItem(NAME_KEY) || '').trim();
    if (PHONE_UID_RE.test(saved)) return saved;
  } catch (e) {}
  return PHONE_DEFAULT_NAME;
})();

const el = (id) => document.getElementById(id);
const camVideo = el('cam');
const camView = el('camView');
const bubbleEl = el('bubble');
const sayEl = el('sayLine');
const camBtn = el('camBtn');
const micBtn = el('micBtn');
const msgBtn = el('msgBtn');
const flipBtn = el('flipBtn');
const modePill = el('modePill');
const modeToast = el('modeToast');
const inputBar = el('inputBar');
const textInput = el('textInput');
const sendBtn = el('sendBtn');
const nameTag = el('nameTag');
const nameValue = el('nameValue');
const nameInput = el('nameInput');
const petFrame = el('petFrame');

const bus = new Bus('phone');
// 麦克风走独立 WS：视频大帧永远不会把音频堵在后面（原来音视频同一条连接 = 语音忽大忽小/丢句）
const audioBus = new Bus('phone', { queueBin: false });
const player = new Player();
const camera = new Camera(bus, camVideo, camView);
const mic = new Mic(audioBus, () => player.isPlaying(), { gateOn: true });
const chat = new Chat(username);
const bubble = new Bubble(bubbleEl);
const say = new Say(sayEl, 6000);

// ---- 语音音量（手机端播放 AI 语音）：静音 + 0~100 音量，记忆到 localStorage ----
// iOS 注意：拖动 input[type=range] 时如果回写 .value，系统会把手势当成页面滚动而取消拖动（表现为"滑到底弹回来"），
// 所以拖动过程中只读不写，松手(change)才回写。
const VOL_KEY = 'meow.phone.vol';
const MUTE_KEY = 'meow.phone.mute';
const volBtn = el('volBtn');
const volRange = el('volRange');
let volLevel = 1;
let volMuted = false;
let volDrag = false;
try {
  const v = parseFloat(localStorage.getItem(VOL_KEY));
  if (!isNaN(v) && v >= 0 && v <= 1) volLevel = v;
  volMuted = localStorage.getItem(MUTE_KEY) === '1';
} catch (e) {}

function saveVol() {
  try {
    localStorage.setItem(VOL_KEY, String(volLevel));
    localStorage.setItem(MUTE_KEY, volMuted ? '1' : '0');
  } catch (e) {}
}

function paintVol(force) {
  if (volRange && (force || !volDrag)) volRange.value = String(Math.round(volLevel * 100));
  if (volBtn) {
    const silent = volMuted || volLevel <= 0.001;
    volBtn.title = silent ? '语音已静音（点击恢复）' : '点击静音';
    volBtn.classList.toggle('off', silent);
  }
}

/** 只把音量落到播放器 + 存盘，不动滑条 DOM（拖动中不干扰手势） */
function pushVol() {
  player.setVolume(volMuted ? 0 : volLevel);
  saveVol();
}

function applyVol() {
  pushVol();
  paintVol(true);
}

if (volBtn) {
  volBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    volMuted = !(volMuted || volLevel <= 0.001);
    if (!volMuted && volLevel <= 0.001) volLevel = 0.6;
    try {
      player.unlock();
    } catch (err) {}
    applyVol();
    say.show(volMuted ? '语音已静音' : '语音音量 ' + Math.round(volLevel * 100) + '%');
  });
}

if (volRange) {
  const readSlider = () => {
    volLevel = Math.max(0, Math.min(1, Number(volRange.value) / 100));
    volMuted = volLevel <= 0.001;
    player.setVolume(volMuted ? 0 : volLevel);   // 立刻生效
    paintVol(false);                             // 只改图标，不回写滑条
    saveVol();
  };
  const endDrag = () => {
    volDrag = false;
    paintVol(true);
  };
  volRange.addEventListener('input', readSlider);
  volRange.addEventListener('change', () => {
    readSlider();
    endDrag();
    try {
      player.unlock();
    } catch (err) {}
  });
  volRange.addEventListener('pointerdown', (e) => {
    volDrag = true;
    e.stopPropagation();
  });
  volRange.addEventListener('touchstart', () => {
    volDrag = true;
  }, { passive: true });
  volRange.addEventListener('click', (e) => e.stopPropagation());
  window.addEventListener('pointerup', endDrag);
  window.addEventListener('touchend', endDrag);
  window.addEventListener('touchcancel', endDrag);
}

applyVol();
const mode = new Mode(modePill, modeToast);

function notify(text) {
  bubble.show(text, 'ai');
}

function setBall(btn, on) {
  btn.classList.toggle('on', !!on);
}

function syncUser() {
  chat.setUsername(username);
  bus.send({ t: 'user', name: username });
  // 麦克风走独立 WS：身份必须单独带上，否则上行音频没有编号，
  // 主项目会按默认的「手机用户」另建一个临时身份（语音记忆就记到别人身上了）
  audioBus.send({ t: 'user', name: username });
}

async function toggleCam() {
  if (camera.on) {
    await camera.stop();
    setBall(camBtn, false);
    return;
  }
  try {
    await camera.start();
    setBall(camBtn, true);
  } catch (e) {
    notify('摄像头不可用：' + (e && e.message ? e.message : e));
    setBall(camBtn, false);
  }
}

async function toggleMic() {
  if (mic.on) {
    await mic.stop();
    setBall(micBtn, false);
    return;
  }
  try {
    syncUser();
    await mic.start();
    setBall(micBtn, true);
  } catch (e) {
    notify('麦克风不可用：' + (e && e.message ? e.message : e));
    setBall(micBtn, false);
  }
}

function toggleInput() {
  inputBar.classList.toggle('hidden');
  const typing = !inputBar.classList.contains('hidden');
  document.body.classList.toggle('typing', typing);
  if (typing) textInput.focus();
}

function sendText() {
  const v = textInput.value;
  textInput.value = '';
  if (chat.send(v)) inputBar.classList.add('hidden');
}

function renderName() {
  if (nameValue) nameValue.textContent = username;
}

function setUsername(name) {
  const clean = String(name || '').trim();
  if (!PHONE_UID_RE.test(clean)) return false;
  username = clean;
  try {
    localStorage.setItem(NAME_KEY, username);
  } catch (e) {}
  renderName();
  syncUser();
  refreshNick();
  return true;
}

let lastExitTs = 0;

function enterEdit() {
  nameTag.classList.add('editing');
  nameTag.classList.remove('err');
  nameInput.value = '';
  nameInput.placeholder = '输入编号，如 000001';
  nameInput.focus();
}

function exitEdit(save) {
  if (!nameTag.classList.contains('editing')) return;
  nameTag.classList.remove('editing');
  lastExitTs = Date.now();
  if (save && !setUsername(nameInput.value)) flashNameError();
}

function flashNameError() {
  nameTag.classList.add('err');
  setTimeout(() => nameTag.classList.remove('err'), 1200);
}

async function refreshNick() {
  const nickEl = el('nickValue');
  if (!nickEl) return;
  const unset = !username || username === PHONE_DEFAULT_NAME;
  if (unset) {
    nameValue.textContent = '未设置';
    nickEl.textContent = '';
    return;
  }
  nameValue.textContent = username;
  nickEl.textContent = '';
  try {
    const r = await fetch('/api/who?uid=' + encodeURIComponent(username), { cache: 'no-store' });
    const d = await r.json();
    const nick = String((d && d.nickname) || '').trim();
    if (nick) {
      nameValue.textContent = nick;              // 第一行：昵称
      nickEl.textContent = '编号 ' + username;    // 第二行：编号
    }
  } catch (e) {}
}

function initNameUi() {
  document.addEventListener('pointerdown', (e) => {
    if (nameTag.classList.contains('editing') && !nameTag.contains(e.target)) exitEdit(true);
  });
  nameTag.addEventListener('click', () => {
    if (nameTag.classList.contains('editing')) return;
    if (Date.now() - lastExitTs < 350) return;
    enterEdit();
  });
  nameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') exitEdit(true);
    else if (e.key === 'Escape') exitEdit(false);
  });
  nameInput.addEventListener('blur', () => exitEdit(true));
  nameInput.addEventListener('click', (e) => e.stopPropagation());
  renderName();
  refreshNick();
}

function initPlayer() {
  const unlock = () => {
    if (player.on) {
      document.removeEventListener('pointerdown', unlock);
      return;
    }
    if (!player.unlock()) return;
    document.removeEventListener('pointerdown', unlock);
    say.show('声音已开启');
  };
  document.addEventListener('pointerdown', unlock);
  player.onStatus = (ok) => {
    if (ok) say.show('声音已开启');
  };
  player.onMeta = (meta) => {
    if (meta && meta.text) bubble.show(String(meta.text), 'ai');
  };
  player.onFiltered = (n) => mode.hintFiltered(n);
  player.start();
  // 刷新页面后 AudioContext 会被浏览器锁住，不点屏幕就没声音——主动提示
  setTimeout(() => {
    if (!player.on) say.show('点一下屏幕开启声音');
  }, 1500);
  setTimeout(() => {
    if (!player.on) say.show('还没有声音：点一下屏幕任意位置');
  }, 7000);
}

function initBus() {
  bus.onText((msg) => {
    if (msg && msg.t === 'reqkey') camera.requestKeyframe();
  });
  // 断线重连后补发身份：发送队列只负责断线期间的文本，重连成功时不会自动重放
  bus.onOpen(() => {
    bus.send({ t: 'user', name: username });
    // 重连等同一次"重新开始"：新的服务端连接上旧的 seq/时间线没有意义
    try { player.resync('ws'); } catch (e) {}
    try { chat.resync(); } catch (e) {}
  });
  audioBus.onOpen(() => {
    audioBus.send({ t: 'user', name: username });
    try { player.resync('ws-audio'); } catch (e) {}
  });
  bus.connect();
  audioBus.connect();
}

window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d || d.source !== 'meow-desktopet' || d.type !== 'pet-rect') return;
  bubble.setPetRect({ x: d.x, y: d.y, w: d.w, h: d.h });
});

// ---- 旋转 / 视口变化：通知桌宠 iframe 重新贴合 ----
// iframe 自己的 resize 在部分手机上会晚于布局甚至不触发，横屏后桌宠会留在竖屏坐标上（跑到屏幕外）
function refitPet() {
  try {
    if (petFrame && petFrame.contentWindow) {
      petFrame.contentWindow.postMessage({ source: 'meow-phone', type: 'pet-refit' }, '*');
    }
  } catch (e) {}
}

function initViewport() {
  window.addEventListener('resize', refitPet);
  window.addEventListener('orientationchange', () => {
    refitPet();
    setTimeout(refitPet, 320);   // iOS 旋转时布局滞后，稍后再补一次
  });
  if (window.visualViewport) {
    try {
      window.visualViewport.addEventListener('resize', refitPet);
    } catch (e) {}
  }
}

// ---- 息屏 / 切后台 / 回前台：音频链路必须重新对齐 ----
// 后台会冻结定时器，回来时旧的 seq 与时间线会把积压的语音一次性补播，
// 麦克风还会被闸门一直掐住（表现就是"电脑彻底听不到你说话，只能重启"）。
// 这里统一：隐藏时停轮询（省电、不攒错位状态），回到前台重新对齐后再拉。
function initVisibility() {
  const onHide = () => {
    try { player.stop(); } catch (e) {}
    try { chat.stop(); } catch (e) {}
  };
  const onShow = (reason) => {
    try { player.resync(reason); } catch (e) {}
    try { chat.resync(); } catch (e) {}
    try { player.start(); } catch (e) {}
    try { chat.start(); } catch (e) {}
  };
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) onHide();
    else onShow('visible');
  });
  window.addEventListener('pageshow', () => onShow('pageshow'));
}

camBtn.addEventListener('click', toggleCam);
micBtn.addEventListener('click', toggleMic);
msgBtn.addEventListener('click', toggleInput);
flipBtn.addEventListener('click', async () => {
  try {
    await camera.flip();
  } catch (e) {
    notify('切换摄像头失败：' + (e && e.message ? e.message : e));
  }
});
sendBtn.addEventListener('click', sendText);
textInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendText();
});
modePill.addEventListener('click', () => mode.toggle());

camera.onError = (e) => notify('摄像头编码异常：' + (e && e.message ? e.message : e));
mic.onError = (e) => notify('麦克风异常：' + (e && e.message ? e.message : e));

// 真实帧率/丢帧提示（节流：5 秒最多一次，只有掉到 26fps 以下或出现丢帧才提示）
let lastStatAt = 0;
camera.onStats = (s) => {
  const now = Date.now();
  if (now - lastStatAt < 5000) return;
  if (s.fps >= 26 && s.dropEnc === 0 && s.dropWs === 0) return;
  lastStatAt = now;
  say.show('画面 ' + s.fps + 'fps · 丢帧 编' + s.dropEnc + '/网' + s.dropWs + ' · 缓存 ' + s.q);
};

chat.onUser = (text) => say.show(text);
chat.onError = (msg) => notify('发送失败：' + msg);

initNameUi();
initBus();
initPlayer();
initViewport();
initVisibility();
syncUser();
chat.start();
mode.load();
