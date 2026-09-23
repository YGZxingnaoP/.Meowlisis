import { Bus } from './ws.js';
import { Player } from './player.js';
import { Camera } from './camera.js';
import { Mic } from './audio.js';
import { Chat } from './chat.js';
import { Bubble } from './bubble.js';
import { Say } from './say.js';
import { Mode } from './mode.js';

const NAME_KEY = 'phone_username';
let username = localStorage.getItem(NAME_KEY) || '手机用户';

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

const bus = new Bus('phone');
const player = new Player();
const camera = new Camera(bus, camVideo, camView);
const mic = new Mic(bus, () => player.isPlaying());
const chat = new Chat(username);
const bubble = new Bubble(bubbleEl);
const say = new Say(sayEl, 6000);
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
  if (!inputBar.classList.contains('hidden')) textInput.focus();
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
  const clean = String(name || '').trim().replace(/\s+/g, ' ').slice(0, 20);
  if (!clean) return false;
  username = clean;
  try {
    localStorage.setItem(NAME_KEY, username);
  } catch (e) {}
  renderName();
  syncUser();
  return true;
}

let lastExitTs = 0;

function enterEdit() {
  nameTag.classList.add('editing');
  nameInput.value = '';
  nameInput.placeholder = '输入昵称（当前：' + username + '）';
  nameInput.focus();
}

function exitEdit(save) {
  if (!nameTag.classList.contains('editing')) return;
  nameTag.classList.remove('editing');
  lastExitTs = Date.now();
  if (save) setUsername(nameInput.value);
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
}

function initPlayer() {
  let unlocked = false;
  const unlock = () => {
    if (unlocked) return;
    unlocked = player.unlock();
    if (unlocked) document.removeEventListener('pointerdown', unlock);
  };
  document.addEventListener('pointerdown', unlock);
  player.onMeta = (meta) => {
    if (meta && meta.text) bubble.show(String(meta.text), 'ai');
  };
  player.onFiltered = (n) => mode.hintFiltered(n);
  player.start();
}

function initBus() {
  bus.onText((msg) => {
    if (msg && msg.t === 'reqkey') camera.requestKeyframe();
  });
  bus.connect();
}

window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d || d.source !== 'meow-desktopet' || d.type !== 'pet-rect') return;
  bubble.setPetRect({ x: d.x, y: d.y, w: d.w, h: d.h });
});

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

chat.onUser = (text) => say.show(text);
chat.onError = (msg) => notify('发送失败：' + msg);

initNameUi();
initBus();
initPlayer();
syncUser();
chat.start();
mode.load();
