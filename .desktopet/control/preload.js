// control/preload.js
// 控制面板的 IPC 桥（独立于桌宠渲染进程）

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('control', {
  getState: () => ipcRenderer.invoke('control:getState'),
  setScale: (s) => ipcRenderer.invoke('control:setScale', s),
  setPosition: (x, y) => ipcRenderer.invoke('control:setPosition', x, y),
  loadModel: (dir) => ipcRenderer.invoke('control:loadModel', dir),
  setParamFix: (fix) => ipcRenderer.invoke('control:setParamFix', fix),
  setDragMode: (enabled) => ipcRenderer.invoke('control:setDragMode', enabled)
});
