// renderer.js
// Live2D 渲染进程：加载模型、驱动参数、切换表情、缩放

(async function () {
  const params = new URLSearchParams(location.search);
  const modelUrl = params.get('model') || '../Live2d_resource/Meowlisis/MiaoWu-l2d.model3.json';

  // ---- 宿主环境与自适应模式 ----
  // 本渲染层同时服务两类宿主：
  //   1) 桌面 Electron（存在 window.desktopet API，由主进程下发 scale 指令，窗口尺寸=模型尺寸）
  //   2) 普通浏览器 iframe（如 .phone 手机页，无主进程）→ 开启"自适应"：按容器尺寸自动缩放
  const isElectronEnv = !!(window.desktopet && window.desktopet.onCommand);
  let autoFitMode = !isElectronEnv; // 非 Electron（手机 iframe）默认自适应
  let fitRatio = 0.92;              // 模型占容器比例（留物理摆动/呼吸等余量，防止被裁切）
  let manualFactor = 1.0;           // 用户手动微调倍率（手机页通过 postMessage 控制）
  let modelOrigW = 0, modelOrigH = 0; // 模型 scale=1 时的原始画布尺寸

  // URL 显式控制：?autofit=1/0、?fit=0.9
  const _af = params.get('autofit');
  if (_af === '1') autoFitMode = true;
  else if (_af === '0') autoFitMode = false;
  const _fit = parseFloat(params.get('fit'));
  if (_fit > 0.05 && _fit <= 3) fitRatio = _fit;

  if (!window.PIXI || !window.PIXI.live2d) {
    document.title = 'Live2D 库未加载';
    console.error('[renderer] Live2D 库未加载');
    return;
  }

  const app = new PIXI.Application({
    view: document.getElementById('canvas'),
    transparent: true,
    autoStart: true,
    resizeTo: window,
    backgroundAlpha: 0,
    // 高清渲染：按设备像素比渲染，防缩放后模糊/显示不完整
    resolution: window.devicePixelRatio || 1,
    autoDensity: true
  });

  // 打印 GPU 信息（验证是否用独显）
  try {
    const gl = app.renderer.gl;
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    const gpuName = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    console.log('[renderer] GPU:', gpuName);
  } catch (e) {}

  let model = null;
  let currentScale = 1.0;
  const activeExpressions = new Set();
  // 表情自动消失定时器：触发后 N 秒自动清空表情
  let expressionTimer = null;

  // ---- 模型位置 = 屏幕中心 + 用户拖拽偏移 ----
  // 手机 iframe（自适应模式）下用户可按住人物拖动；旋转/缩放/页面尺寸变化都保留该偏移。
  let dragOffsetX = 0;
  let dragOffsetY = 0;

  function clampDragOffset() {
    // 限制模型中心不越出画布（留 40px 余量），拖拽与尺寸变化时统一约束
    if (!app || !app.screen) return;
    const W = app.screen.width, H = app.screen.height;
    const mx = Math.max(W / 2 - 40, 0);
    const my = Math.max(H / 2 - 40, 0);
    dragOffsetX = Math.max(-mx, Math.min(mx, dragOffsetX));
    dragOffsetY = Math.max(-my, Math.min(my, dragOffsetY));
  }

  function setCenterPosition() {
    if (!model) return;
    clampDragOffset();
    model.position.set(
      app.screen.width / 2 + dragOffsetX,
      app.screen.height / 2 + dragOffsetY
    );
  }

  function recenter() {
    setCenterPosition(); // 保留用户拖拽偏移
  }

  function resetCenter() {
    dragOffsetX = 0;
    dragOffsetY = 0;
    setCenterPosition();
  }

  function applyScale(s) {
    currentScale = s;
    if (!model) return;
    model.scale.set(s);
    setCenterPosition();
  }

  // 自适应模式下计算"完整显示在容器内"的缩放：min(可用宽/模型宽, 可用高/模型高)
  function computeFitScale() {
    if (!(modelOrigW > 0) || !(modelOrigH > 0)) return null;
    const availW = app.screen.width * fitRatio;
    const availH = app.screen.height * fitRatio;
    if (availW <= 0 || availH <= 0) return null;
    return Math.min(availW / modelOrigW, availH / modelOrigH);
  }

  // 按当前模式应用缩放：
  //   自适应模式（手机 iframe）→ fitScale × 手动倍率
  //   桌面模式 → 沿用主进程下发的 currentScale
  function applyDesiredScale() {
    if (!model) return;
    if (autoFitMode) {
      const fs = computeFitScale();
      if (fs && fs > 0) applyScale(fs * manualFactor);
    } else {
      applyScale(currentScale);
    }
  }

  function applyParam(p) {
    if (!model) return;
    try {
      model.internalModel.coreModel.setParameterValueById(p.id, p.value);
    } catch (e) {
      console.warn('[renderer] 设置参数失败', p.id, e.message);
    }
  }

  function toggleExpression(file) {
    if (!model) return;
    if (!file) return;
    try {
      // 清空旧表情，只显示当前表情（实现表情"更新"，不再叠加/停留在旧表情）
      activeExpressions.clear();
      activeExpressions.add(file);
      model.expression(file);
      console.log('[renderer] 触发表情', file);

      // 触发后 10 秒自动消失
      if (expressionTimer) clearTimeout(expressionTimer);
      expressionTimer = setTimeout(() => {
        activeExpressions.clear();
        model.expression();
        console.log('[renderer] 表情自动消失');
      }, 10000);
    } catch (e) {
      console.error('[renderer] 表情切换失败', file, e.message);
    }
  }

  async function loadModel(url) {
    // 移除旧模型
    if (model) {
      app.stage.removeChild(model);
      try { model.destroy(); } catch (e) {}
      model = null;
    }
    activeExpressions.clear();
    model = await PIXI.live2d.Live2DModel.from(url);
    model.anchor.set(0.5, 0.5);
    // 禁用 pixi 自带的鼠标跟随（focus：头/眼会跟随鼠标，且方向与 VTS 不一致，导致左右变俯仰）。
    // 头部/眼睛方向完全由 VTS 注入参数（FaceAngleX/Y）驱动，方向通过控制面板 paramFix 修正。
    model.autoInteract = false;
    app.stage.addChild(model);

    // 记录 scale=1 时的原始尺寸（必须在 applyScale 前读取，供自适应计算）
    modelOrigW = model.width;
    modelOrigH = model.height;
    applyDesiredScale();

    // 上报模型原始尺寸（用于主进程计算窗口大小）
    if (window.desktopet && window.desktopet.modelReady) {
      window.desktopet.modelReady({ width: model.width, height: model.height });
    }
    console.log('[renderer] 模型加载完成', model.width, model.height);
  }

  try {
    await loadModel(modelUrl);
  } catch (e) {
    console.error('[renderer] 模型加载失败:', e);
    document.title = '模型加载失败';
    return;
  }

  // ---- 视口变化：居中 + 自适应模式下重算缩放（旋转/窗口变化）----
  function onViewportResize() {
    recenter();
    if (autoFitMode) {
      const fs = computeFitScale();
      if (fs && fs > 0) applyScale(fs * manualFactor);
    }
  }
  window.addEventListener('resize', onViewportResize);
  window.addEventListener('orientationchange', onViewportResize);

  // ---- 手机 iframe（自适应模式）：按住人物拖拽移动，双击回中 ----
  if (autoFitMode) {
    const dragCanvas = document.getElementById('canvas');
    let afDragging = false;
    let afLast = null;
    dragCanvas.style.touchAction = 'none'; // 防 iframe 内触摸滚动/缩放
    dragCanvas.style.cursor = 'grab';

    dragCanvas.addEventListener('pointerdown', (e) => {
      afDragging = true;
      afLast = { x: e.clientX, y: e.clientY };
      dragCanvas.style.cursor = 'grabbing';
      try { dragCanvas.setPointerCapture(e.pointerId); } catch (err) {}
    });
    dragCanvas.addEventListener('pointermove', (e) => {
      if (!afDragging || !afLast) return;
      dragOffsetX += e.clientX - afLast.x;
      dragOffsetY += e.clientY - afLast.y;
      afLast = { x: e.clientX, y: e.clientY };
      setCenterPosition();
    });
    function endAfDrag() {
      afDragging = false;
      afLast = null;
      dragCanvas.style.cursor = 'grab';
    }
    dragCanvas.addEventListener('pointerup', endAfDrag);
    dragCanvas.addEventListener('pointercancel', endAfDrag);
    // 双击人物回中（浏览器仅在两次点击无明显位移时触发）
    dragCanvas.addEventListener('dblclick', (e) => {
      e.preventDefault();
      resetCenter();
    });
  }

  // ---- 拖动模式：鼠标实时拖动人物 ----
  let dragMode = false;
  let dragging = false;
  let dragStart = null;
  let curOffsetX = 0;
  let curOffsetY = 0;
  const canvas = document.getElementById('canvas');

  canvas.addEventListener('mousedown', (e) => {
    if (!dragMode) return;
    dragging = true;
    dragStart = { screenX: e.screenX, screenY: e.screenY, offsetX: curOffsetX, offsetY: curOffsetY };
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging || !dragStart) return;
    const dx = e.screenX - dragStart.screenX;
    const dy = e.screenY - dragStart.screenY;
    curOffsetX = dragStart.offsetX + dx;
    curOffsetY = dragStart.offsetY + dy;
    if (window.desktopet && window.desktopet.dragMove) {
      window.desktopet.dragMove(curOffsetX, curOffsetY);
    }
  });
  window.addEventListener('mouseup', () => { dragging = false; dragStart = null; });

  // ---- 鼠标跟随（正确方向）----
  // 主进程用 getCursorScreenPoint 轮询鼠标位置（仅读取，不拦截事件，穿透照常），
  // 这里手动驱动头部/眼睛跟随，方向用标准 Live2D 映射（修正 pixi 自带 focus 的 X/Y 反向问题）。
  let followActive = false;
  const followFix = { swapAngleXY: false, flipAngleX: false, flipAngleY: false };
  const followTarget = { angleX: 0, angleY: 0, eyeX: 0, eyeY: 0 };
  const followCurrent = { angleX: 0, angleY: 0, eyeX: 0, eyeY: 0 };

  app.ticker.add(() => {
    if (!model) return;
    const t = 0.18; // 平滑系数
    followCurrent.angleX += (followTarget.angleX - followCurrent.angleX) * t;
    followCurrent.angleY += (followTarget.angleY - followCurrent.angleY) * t;
    followCurrent.eyeX += (followTarget.eyeX - followCurrent.eyeX) * t;
    followCurrent.eyeY += (followTarget.eyeY - followCurrent.eyeY) * t;
    // 鼠标在窗口范围内时才跟随，否则交给 VTS 注入参数（Meowlisis 嘴部/摆动）驱动，避免冲突
    if (followActive) {
      applyParam({ id: 'ParamAngleX', value: followCurrent.angleX });
      applyParam({ id: 'ParamAngleY', value: followCurrent.angleY });
      applyParam({ id: 'ParamEyeBallX', value: followCurrent.eyeX });
      applyParam({ id: 'ParamEyeBallY', value: followCurrent.eyeY });
    }
  });

  // 接收主进程指令
  if (window.desktopet && window.desktopet.onCommand) {
    window.desktopet.onCommand((payload) => {
      if (!payload) return;
      switch (payload.type) {
        case 'scale':
          applyScale(payload.scale);
          break;
        case 'param':
          if (payload.values) payload.values.forEach(applyParam);
          break;
        case 'hotkey':
          if (payload.hotkey && payload.hotkey.file) {
            toggleExpression(payload.hotkey.file);
          }
          break;
        case 'loadModel':
          if (payload.url) {
            loadModel(payload.url).catch(e => console.error('[renderer] 切换模型失败:', e));
          }
          break;
        case 'dragMode':
          dragMode = !!payload.enabled;
          if (typeof payload.offsetX === 'number') curOffsetX = payload.offsetX;
          if (typeof payload.offsetY === 'number') curOffsetY = payload.offsetY;
          break;
        case 'follow':
          followActive = !!payload.active;
          if (followActive) {
            const clamp = (v) => Math.max(-1, Math.min(1, Number(v) || 0));
            let nx = clamp(payload.nx), ny = clamp(payload.ny);
            if (followFix.swapAngleXY) { const tt = nx; nx = ny; ny = tt; }
            if (followFix.flipAngleX) nx = -nx;
            if (followFix.flipAngleY) ny = -ny;
            // 标准映射：鼠标 X→左右转头(ParamAngleX)，鼠标 Y→上下俯仰(ParamAngleY)
            // 屏幕 Y 向下、Live2D ParamAngleY 正值向上，故 Y 取反
            followTarget.angleX = nx * 15;
            followTarget.angleY = -ny * 15;
            followTarget.eyeX = nx * 0.8;
            followTarget.eyeY = -ny * 0.8;
          }
          break;
        case 'followFix':
          if (payload) {
            followFix.swapAngleXY = !!payload.swapAngleXY;
            followFix.flipAngleX = !!payload.flipAngleX;
            followFix.flipAngleY = !!payload.flipAngleY;
          }
          break;
      }
    });
  }

  // 手机页（父窗口 iframe）缩放控制：postMessage
  // { source:'meow-phone', type:'pet-zoom', dir:'in'|'out' } / { type:'pet-reset' }
  window.addEventListener('message', (e) => {
    const d = e.data;
    if (!d || d.source !== 'meow-phone') return;
    if (d.type === 'pet-zoom') {
      const step = (d.dir === 'in' ? 1.15 : 1 / 1.15);
      manualFactor = Math.max(0.35, Math.min(2.5, manualFactor * step));
      if (autoFitMode) {
        const fs = computeFitScale();
        if (fs && fs > 0) applyScale(fs * manualFactor);
      }
    } else if (d.type === 'pet-reset') {
      manualFactor = 1.0;
      resetCenter(); // 重置大小 + 位置回中
      if (autoFitMode) {
        const fs = computeFitScale();
        if (fs && fs > 0) applyScale(fs * manualFactor);
      }
    }
  });
})();
