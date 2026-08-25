// renderer.js
// Live2D 渲染进程：加载模型、驱动参数、切换表情、缩放

(async function () {
  const params = new URLSearchParams(location.search);
  const modelUrl = params.get('model') || '../Live2d_resource/Meowlisis/MiaoWu-l2d.model3.json';

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

  function recenter() {
    if (!model) return;
    model.position.set(app.screen.width / 2, app.screen.height / 2);
  }

  function applyScale(s) {
    currentScale = s;
    if (!model) return;
    model.scale.set(s);
    recenter();
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
    applyScale(currentScale);

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

  window.addEventListener('resize', recenter);

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
})();
