// preload.js
// 通过 contextBridge 暴露受控 API 给渲染进程

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopet', {
  // 渲染进程上报模型原始尺寸（用于主进程计算窗口大小）
  modelReady: (size) => ipcRenderer.send('model-ready', size),
  // 渲染进程上报缩放（托盘/API 缩放后回传，保持一致性）
  setScale: (scale) => ipcRenderer.send('scale', scale),
  // 拖动模式下实时上报位置偏移
  dragMove: (offsetX, offsetY) => ipcRenderer.send('drag-move', { offsetX, offsetY }),
  // 主进程下发指令：scale / param / hotkey / loadModel / dragMode
  onCommand: (callback) => {
    ipcRenderer.on('command', (event, payload) => callback(payload));
  }
});
