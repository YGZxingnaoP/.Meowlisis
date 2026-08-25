// control/control.js
// 控制面板逻辑：实时调整缩放/位置/模型/方向修正

(async function () {
  const scaleSlider = document.getElementById('scaleSlider');
  const scaleInput = document.getElementById('scaleInput');
  const offsetX = document.getElementById('offsetX');
  const offsetY = document.getElementById('offsetY');
  const modelSelect = document.getElementById('modelSelect');
  const swapXY = document.getElementById('swapXY');
  const flipX = document.getElementById('flipX');
  const flipY = document.getElementById('flipY');
  const resetPos = document.getElementById('resetPos');
  const resetScale = document.getElementById('resetScale');
  const dragModeBtn = document.getElementById('dragModeBtn');

  let updating = false; // 防止初始化时触发事件

  // ---- 加载当前状态 ----
  try {
    const state = await window.control.getState();
    updating = true;
    if (typeof state.userScale === 'number') {
      scaleSlider.value = state.userScale;
      scaleInput.value = state.userScale.toFixed(2);
    }
    offsetX.value = state.offsetX || 0;
    offsetY.value = state.offsetY || 0;

    // 模型下拉
    if (Array.isArray(state.models)) {
      modelSelect.innerHTML = '';
      state.models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.dir;
        opt.textContent = m.name;
        if (m.dir === state.modelDir) opt.selected = true;
        modelSelect.appendChild(opt);
      });
    }

    // 方向修正
    const fix = state.paramFix || {};
    swapXY.checked = !!fix.swapAngleXY;
    flipX.checked = !!fix.flipAngleX;
    flipY.checked = !!fix.flipAngleY;
    updating = false;
  } catch (e) {
    console.error('加载状态失败:', e);
    updating = false;
  }

  // ---- 缩放 ----
  function applyScale(s) {
    s = Math.max(0.2, Math.min(3, Number(s) || 1));
    scaleSlider.value = s;
    scaleInput.value = s.toFixed(2);
    if (!updating) window.control.setScale(s);
  }
  scaleSlider.addEventListener('input', () => applyScale(scaleSlider.value));
  scaleInput.addEventListener('change', () => applyScale(scaleInput.value));

  // ---- 位置 ----
  function applyPosition() {
    if (updating) return;
    window.control.setPosition(Number(offsetX.value) || 0, Number(offsetY.value) || 0);
  }
  offsetX.addEventListener('change', applyPosition);
  offsetY.addEventListener('change', applyPosition);
  offsetX.addEventListener('input', applyPosition);
  offsetY.addEventListener('input', applyPosition);

  resetPos.addEventListener('click', () => {
    offsetX.value = 0;
    offsetY.value = 0;
    applyPosition();
  });
  resetScale.addEventListener('click', () => applyScale(1));

  // ---- 拖动模式开关 ----
  let dragModeOn = false;
  function updateDragBtn() {
    dragModeBtn.textContent = dragModeOn ? '🖱 退出拖动模式' : '🖱 拖动模式';
    dragModeBtn.style.background = dragModeOn ? '#ffb347' : '#ff66a5';
  }
  dragModeBtn.addEventListener('click', () => {
    dragModeOn = !dragModeOn;
    updateDragBtn();
    if (!updating) window.control.setDragMode(dragModeOn);
  });
  updateDragBtn();

  // ---- 模型切换 ----
  modelSelect.addEventListener('change', () => {
    if (!updating) window.control.loadModel(modelSelect.value);
  });

  // ---- 方向修正 ----
  function applyFix() {
    if (updating) return;
    window.control.setParamFix({
      swapAngleXY: swapXY.checked,
      flipAngleX: flipX.checked,
      flipAngleY: flipY.checked
    });
  }
  swapXY.addEventListener('change', applyFix);
  flipX.addEventListener('change', applyFix);
  flipY.addEventListener('change', applyFix);
})();
