// main.js
// Electron 主进程：透明穿透窗口 + 系统托盘 + VTS API 服务端 + IPC 桥

const { app, BrowserWindow, Tray, Menu, ipcMain, screen, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');

// 强制使用独立显卡渲染（核显太卡）。双显卡笔记本上 Chromium 默认可能用核显。
app.commandLine.appendSwitch('force_high_performance_gpu');
// 允许 GPU 加速的 2D 画布 / WebGL
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('ignore-gpu-blocklist');

const { VtsModel } = require('./vts/model');
const { VtsServer } = require('./vts/server');

const configPath = path.join(__dirname, 'config.json');
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf-8'));

let win = null;
let tray = null;
let model = null;
let server = null;

// baseScale：基准缩放（让大画布模型适配屏幕，model-ready 时按屏幕计算）
// userScale：用户缩放倍数（托盘/API 控制）
let baseScale = 0.1;
let userScale = 1.0;
let offsetX = 0;
let offsetY = 0; // 用户位置偏移（控制面板调整）
let dragMode = false; // 拖动模式（取消穿透，可实时拖动人物）
let modelSize = { width: 400, height: 800 }; // 渲染进程上报后更新
let anchor = null; // 窗口底部中心锚点
let controlWin = null; // 控制面板窗口

function getAnchor() {
  const wa = screen.getPrimaryDisplay().workArea;
  return {
    x: Math.round(wa.x + wa.width * 0.62),
    y: Math.round(wa.y + wa.height)
  };
}

// 扫描 Live2d_resource 下含 .model3.json 的模型目录
function listModels() {
  const root = path.resolve(__dirname, 'Live2d_resource');
  const out = [];
  try {
    if (!fs.existsSync(root)) return out;
    for (const e of fs.readdirSync(root, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      const dir = path.join(root, e.name);
      try {
        const model3 = fs.readdirSync(dir).find(f => f.endsWith('.model3.json'));
        if (model3) {
          out.push({ name: e.name, dir: path.relative(__dirname, dir).replace(/\\/g, '/'), model3 });
        }
      } catch (err) {}
    }
  } catch (e) {}
  return out;
}

// 打开控制面板窗口
function openControlPanel() {
  if (controlWin) {
    controlWin.focus();
    return;
  }
  controlWin = new BrowserWindow({
    width: 380,
    height: 560,
    transparent: false,
    frame: true,
    resizable: false,
    alwaysOnTop: true,
    webPreferences: {
      preload: path.join(__dirname, 'control', 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  controlWin.loadFile(path.join(__dirname, 'control', 'control.html'));
  controlWin.on('closed', () => { controlWin = null; });
}

function applyWindowSize() {
  if (!win) return;
  const s = baseScale * userScale;
  const padding = cfg.window.padding || 1.15; // 留边距，防物理摆动内容超出被裁剪
  const w = Math.max(50, Math.round(modelSize.width * s * padding));
  const h = Math.max(50, Math.round(modelSize.height * s * padding));
  const a = anchor || getAnchor();
  const x = a.x - Math.round(w / 2) + offsetX;
  const y = a.y - h + offsetY;
  win.setBounds({ x, y, width: w, height: h }, false);
}

function setUserScale(newUserScale) {
  userScale = Math.max(0.1, Math.min(5.0, newUserScale));
  applyWindowSize();
  const s = baseScale * userScale;
  console.log(`[main] setUserScale=${userScale.toFixed(3)}, window=${Math.round(modelSize.width * s)}x${Math.round(modelSize.height * s)}`);
  if (win && win.webContents) {
    win.webContents.send('command', { type: 'scale', scale: baseScale * userScale });
  }
}

// 鼠标跟随：用 getCursorScreenPoint 轮询鼠标位置（仅读取坐标，不拦截任何鼠标事件，
// 穿透照常，游戏/正常操作完全不受影响），把位置发给渲染进程驱动人物跟随。
let followTimer = null;

function startMouseFollow() {
  if (followTimer) return;
  followTimer = setInterval(() => {
    if (!win || !win.webContents) return;
    try {
      const point = screen.getCursorScreenPoint();
      const b = win.getBounds();
      const margin = 120; // 窗口外跟随边距
      const inRange = point.x >= b.x - margin && point.x <= b.x + b.width + margin &&
                      point.y >= b.y - margin && point.y <= b.y + b.height + margin;
      if (!inRange) {
        win.webContents.send('command', { type: 'follow', active: false });
        return;
      }
      const cx = b.x + b.width / 2;
      const cy = b.y + b.height / 2;
      const nx = (point.x - cx) / (b.width / 2);
      const ny = (point.y - cy) / (b.height / 2);
      win.webContents.send('command', { type: 'follow', active: true, nx, ny });
    } catch (e) {}
  }, 33);
}

function createWindow() {
  anchor = getAnchor();

  win = new BrowserWindow({
    width: 400,
    height: 800,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    hasShadow: false,
    resizable: false,
    skipTaskbar: true,
    fullscreenable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: false
    }
  });

  win.setAlwaysOnTop(true, 'screen-saver');
  // 鼠标穿透：不拦截任何鼠标事件，全部透传给下层窗口（游戏）
  win.setIgnoreMouseEvents(true, { forward: true });

  const modelAbs = path.resolve(__dirname, cfg.model.dir, cfg.model.model3);
  const modelUrl = 'file:///' + modelAbs.replace(/\\/g, '/');
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'), {
    query: { model: modelUrl }
  });

  // 渲染进程日志转发到主进程 stdout（便于调试）
  win.webContents.on('console-message', (event, level, message) => {
    console.log('[renderer]', message);
  });

  win.on('closed', () => { win = null; });
}

function buildModelSubmenu() {
  const models = listModels();
  if (!models.length) return [{ label: '(无模型)', enabled: false }];
  return models.map(m => ({
    label: m.name,
    type: 'radio',
    checked: m.dir === cfg.model.dir,
    click: () => loadModel(m.dir)
  }));
}

function buildTrayMenu() {
  return Menu.buildFromTemplate([
    { label: '控制面板', click: openControlPanel },
    { type: 'separator' },
    { label: '放大', click: () => setUserScale(userScale * 1.1) },
    { label: '缩小', click: () => setUserScale(userScale / 1.1) },
    { label: '重置大小', click: () => setUserScale(1.0) },
    { type: 'separator' },
    { label: '加载模型', submenu: buildModelSubmenu() },
    { type: 'separator' },
    { label: '退出桌宠', click: () => app.quit() }
  ]);
}

function createTray() {
  // 优先使用根目录 icon.ico，找不到再回退 icon.png
  let icon = nativeImage.createFromPath(path.join(__dirname, 'icon.ico'));
  if (icon.isEmpty()) icon = nativeImage.createFromPath(path.join(__dirname, 'icon.png'));
  if (icon.isEmpty()) icon = nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip('喵呜桌宠');
  tray.setContextMenu(buildTrayMenu());
  tray.on('double-click', openControlPanel);
}

// 切换加载的 Live2D 模型（托盘子菜单 / 控制面板共用）
function loadModel(modelDir) {
  cfg.model.dir = modelDir;
  const models = listModels();
  const m = models.find(x => x.dir === modelDir);
  const model3 = m ? m.model3 : cfg.model.model3;
  const modelAbs = path.resolve(__dirname, modelDir, model3);
  if (win && win.webContents) {
    win.webContents.send('command', { type: 'loadModel', url: 'file:///' + modelAbs.replace(/\\/g, '/') });
  }
  if (tray) tray.setContextMenu(buildTrayMenu());
}

function startVtsServer() {
  model = new VtsModel(cfg);
  server = new VtsServer(model, (type, payload) => {
    // 缩放指令由主进程统一处理（调整窗口 + 通知渲染）
    if (type === 'move' && typeof payload.userScale === 'number') {
      setUserScale(payload.userScale);
      return;
    }
    if (!win || !win.webContents) return;
    win.webContents.send('command', Object.assign({ type }, payload));
  });
  server.paramFix = cfg.paramFix || {};
  server.start(cfg.api.host, cfg.api.port);
}

// ---- IPC ----
ipcMain.on('model-ready', (e, size) => {
  if (size && size.width > 0 && size.height > 0) {
    modelSize = { width: size.width, height: size.height };
    // 按屏幕计算基准缩放：模型高度适配屏幕，且不超过屏幕宽度
    const wa = screen.getPrimaryDisplay().workArea;
    baseScale = Math.min((wa.height * 0.72) / modelSize.height, (wa.width * 0.45) / modelSize.width);
    if (!(baseScale > 0)) baseScale = 0.1;
    applyWindowSize();
    const s = baseScale * userScale;
    console.log(`[main] model-ready: model=${modelSize.width}x${modelSize.height}, baseScale=${baseScale.toFixed(4)}, window=${Math.round(modelSize.width * s)}x${Math.round(modelSize.height * s)}, screen=${wa.width}x${wa.height}`);
    // 模型就绪后同步一次缩放给渲染进程
    if (win && win.webContents) {
      win.webContents.send('command', { type: 'scale', scale: baseScale * userScale });
      win.webContents.send('command', { type: 'followFix', ...(cfg.paramFix || {}) });
    }
  }
});

ipcMain.on('scale', (e, s) => {
  if (typeof s === 'number') setUserScale(s);
});

// ---- 控制面板 IPC ----
ipcMain.handle('control:getState', () => ({
  userScale,
  offsetX,
  offsetY,
  modelDir: cfg.model.dir,
  models: listModels(),
  paramFix: cfg.paramFix || {}
}));

ipcMain.handle('control:setScale', (e, s) => {
  setUserScale(Number(s));
});

ipcMain.handle('control:setPosition', (e, x, y) => {
  offsetX = Number(x) || 0;
  offsetY = Number(y) || 0;
  applyWindowSize();
});

ipcMain.handle('control:loadModel', (e, modelDir) => {
  loadModel(modelDir);
});

ipcMain.handle('control:setParamFix', (e, fix) => {
  cfg.paramFix = fix || {};
  if (server) server.paramFix = cfg.paramFix;
  // 同步方向修正给渲染进程（鼠标跟随也用同一套修正）
  if (win && win.webContents) {
    win.webContents.send('command', { type: 'followFix', ...fix });
  }
});

// 拖动模式：开启后取消穿透，桌宠可被鼠标实时拖动
ipcMain.handle('control:setDragMode', (e, enabled) => {
  dragMode = !!enabled;
  if (win) {
    win.setIgnoreMouseEvents(!dragMode, { forward: true });
    if (win.webContents) {
      win.webContents.send('command', { type: 'dragMode', enabled: dragMode, offsetX, offsetY });
    }
  }
});

// 拖动过程中渲染进程实时上报位置偏移
ipcMain.on('drag-move', (e, pos) => {
  if (pos && typeof pos.offsetX === 'number') {
    offsetX = pos.offsetX;
    offsetY = pos.offsetY || 0;
    applyWindowSize();
  }
});

app.whenReady().then(() => {
  createWindow();
  createTray();
  startVtsServer();
  startMouseFollow();
});

app.on('window-all-closed', () => {
  // 桌宠常驻，不自动退出；托盘可退出
});

app.on('before-quit', () => {
  if (server) server.stop();
});
