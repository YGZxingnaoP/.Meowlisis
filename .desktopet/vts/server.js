// vts/server.js
// VTube Studio Public API 兼容 WebSocket 服务端（无认证）

const { WebSocketServer } = require('ws');
const { VtsModel, DEFAULT_TRACKING_PARAMETERS } = require('./model');

const API_NAME = 'VTubeStudioPublicAPI';
const API_VERSION = '1.0';

class VtsServer {
  /**
   * @param {VtsModel} model 模型状态
   * @param {Function} onCommand 指令回调 (type, payload)
   *   type: 'move'  payload {size, positionX, positionY, rotation}
   *         'param' payload {values: [{id, value, weight}]}
   *         'hotkey' payload {hotkey}
   */
  constructor(model, onCommand) {
    this.model = model;
    this.onCommand = onCommand || (() => {});
    this.wss = null;
    this.paramFix = {}; // 方向修正（控制面板设置）
  }

  start(host, port) {
    this.wss = new WebSocketServer({ host, port });
    this.wss.on('connection', (ws) => {
      ws.on('message', (raw) => {
        try {
          const msg = JSON.parse(raw.toString('utf-8'));
          this._handle(ws, msg);
        } catch (e) {
          this._sendError(ws, null, 2, 'JSONInvalid');
        }
      });
    });
    console.log(`[vts] VTS API server listening on ws://${host}:${port}`);
  }

  stop() {
    if (this.wss) {
      try { this.wss.close(); } catch (e) {}
      this.wss = null;
    }
  }

  _send(ws, msg) {
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify(msg));
    }
  }

  _base(msg) {
    return {
      apiName: API_NAME,
      apiVersion: API_VERSION,
      timestamp: Date.now(),
      requestID: msg && msg.requestID ? msg.requestID : ''
    };
  }

  _sendError(ws, msg, errorID, message) {
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'APIError',
      data: { errorID, message }
    }));
  }

  _handle(ws, msg) {
    if (!msg || typeof msg !== 'object') {
      this._sendError(ws, msg, 2, 'JSONInvalid');
      return;
    }
    const type = msg.messageType;
    if (!type) {
      this._sendError(ws, msg, 6, 'RequestTypeMissingOrEmpty');
      return;
    }

    switch (type) {
      case 'APIStateRequest':
        return this._handleApiState(ws, msg);
      case 'AuthenticationRequest':
        return this._handleAuth(ws, msg);
      case 'StatisticsRequest':
        return this._handleStatistics(ws, msg);
      case 'CurrentModelRequest':
        return this._handleCurrentModel(ws, msg);
      case 'AvailableModelsRequest':
        return this._handleAvailableModels(ws, msg);
      case 'ModelLoadRequest':
        return this._handleModelLoad(ws, msg);
      case 'MoveModelRequest':
        return this._handleMoveModel(ws, msg);
      case 'HotkeyTriggerRequest':
        return this._handleHotkeyTrigger(ws, msg);
      case 'HotkeysInCurrentModelRequest':
        return this._handleHotkeysInCurrentModel(ws, msg);
      case 'InjectParameterDataRequest':
        return this._handleInjectParameter(ws, msg);
      case 'Live2DParameterListRequest':
        return this._handleLive2DParameterList(ws, msg);
      case 'InputParameterListRequest':
        return this._handleInputParameterList(ws, msg);
      case 'ExpressionStateRequest':
        return this._handleExpressionState(ws, msg);
      case 'ExpressionActivationRequest':
        return this._handleExpressionActivation(ws, msg);
      case 'EventSubscriptionRequest':
        return this._handleEventSubscription(ws, msg);
      case 'ParameterCreationRequest':
      case 'ParameterDeletionRequest':
        return this._send(ws, Object.assign(this._base(msg), {
          messageType: 'APIError',
          data: { errorID: 7, message: 'Request not supported by desktop pet' }
        }));
      default:
        this._sendError(ws, msg, 7, `RequestTypeUnknown: ${type}`);
    }
  }

  _handleApiState(ws, msg) {
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'APIStateResponse',
      data: {
        active: true,
        vTubeStudioVersion: '1.35.10',
        currentSessionAuthenticated: true
      }
    }));
  }

  _handleAuth(ws, msg) {
    // 无认证：任何 token 都直接通过
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'AuthenticationResponse',
      data: {
        authenticated: true,
        reason: 'Desktop pet: authentication disabled'
      }
    }));
  }

  _handleStatistics(ws, msg) {
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'StatisticsResponse',
      data: {
        uptime: Math.round(process.uptime() * 1000),
        framerate: 60,
        vTubeStudioVersion: '1.35.10',
        allowedPlugins: 1,
        connectedPlugins: 1,
        startedWithSteam: false,
        windowWidth: 1920,
        windowHeight: 1080,
        windowIsFullscreen: false
      }
    }));
  }

  _handleCurrentModel(ws, msg) {
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'CurrentModelResponse',
      data: this.model.getCurrentModelData()
    }));
  }

  _handleAvailableModels(ws, msg) {
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'AvailableModelsResponse',
      data: {
        numberOfModels: 1,
        availableModels: [{
          modelLoaded: true,
          modelName: this.model.modelName,
          modelID: this.model.modelID,
          vtsModelName: this.model.cfg.model.vtube,
          vtsModelIconName: ''
        }]
      }
    }));
  }

  _handleModelLoad(ws, msg) {
    // 桌宠固定单模型，忽略加载请求但返回成功
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'ModelLoadResponse',
      data: { modelID: this.model.modelID }
    }));
  }

  _handleMoveModel(ws, msg) {
    const d = msg.data || {};
    const size = this._num(d.size, 0);
    const positionX = this._num(d.positionX, this.model.positionX);
    const positionY = this._num(d.positionY, this.model.positionY);
    const rotation = this._num(d.rotation, this.model.rotation);

    this.model.size = Math.max(-100, Math.min(100, size));
    this.model.positionX = positionX;
    this.model.positionY = positionY;
    this.model.rotation = rotation;
    this.model.scale = VtsModel.sizeToScale(this.model.size);

    this.onCommand('move', {
      size: this.model.size,
      userScale: VtsModel.sizeToScale(this.model.size),
      positionX,
      positionY,
      rotation
    });

    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'MoveModelResponse',
      data: {}
    }));
  }

  _handleHotkeyTrigger(ws, msg) {
    const d = msg.data || {};
    const hotkeyID = d.hotkeyID || '';
    const hotkey = this.model.findHotkey(hotkeyID);
    if (!hotkey) {
      this._sendError(ws, msg, 202, 'HotkeyIDNotFoundInModel');
      return;
    }
    this.onCommand('hotkey', { hotkey });
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'HotkeyTriggerResponse',
      data: {}
    }));
  }

  _handleHotkeysInCurrentModel(ws, msg) {
    const availableHotkeys = this.model.hotkeys.map(h => ({
      name: h.name,
      type: h.action,
      file: h.file,
      hotkeyID: h.hotkeyID
    }));
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'HotkeysInCurrentModelResponse',
      data: {
        modelLoaded: true,
        modelName: this.model.modelName,
        modelID: this.model.modelID,
        availableHotkeys
      }
    }));
  }

  _handleInjectParameter(ws, msg) {
    const d = msg.data || {};
    const values = d.parameterValues || [];
    if (!values.length) {
      this._sendError(ws, msg, 450, 'InjectDataNoDataProvided');
      return;
    }

    // 方向修正：先对 VTS 输入参数做交换/翻转，再映射到 Live2D 参数
    const processed = values.map(p => ({ id: p.id, value: this._num(p.value, 0), weight: this._num(p.weight, 1) }));
    const fix = this.paramFix || {};
    if (fix.swapAngleXY) {
      // 在映射层交换参数 id：FaceAngleX 的值改用 FaceAngleY 的映射（→ParamAngleY），反之亦然。
      // 注意必须在「交换 id」而非「交换值」层面做，因为客户端常单参数注入（如只发 FaceAngleX）。
      for (const p of processed) {
        if (p.id === 'FaceAngleX') p.id = 'FaceAngleY';
        else if (p.id === 'FaceAngleY') p.id = 'FaceAngleX';
      }
    }
    if (fix.flipAngleX) {
      for (const p of processed) if (p.id === 'FaceAngleX') p.value = -p.value;
    }
    if (fix.flipAngleY) {
      for (const p of processed) if (p.id === 'FaceAngleY') p.value = -p.value;
    }

    const mapped = [];
    for (const p of processed) {
      const live2d = this.model.mapInputToLive2D(p.id, p.value);
      for (const l of live2d) {
        mapped.push({ id: l.id, value: l.value, weight: p.weight });
      }
    }
    if (mapped.length) {
      console.log('[vts] 注入参数 ->', JSON.stringify(mapped), 'paramFix:', JSON.stringify(this.paramFix));
      this.onCommand('param', { values: mapped });
    }
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'InjectParameterDataResponse',
      data: {}
    }));
  }

  _handleLive2DParameterList(ws, msg) {
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'Live2DParameterListResponse',
      data: {
        modelID: this.model.modelID,
        modelName: this.model.modelName,
        parameters: this.model.live2dParams
      }
    }));
  }

  _handleInputParameterList(ws, msg) {
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'InputParameterListResponse',
      data: {
        modelID: this.model.modelID,
        modelName: this.model.modelName,
        defaultParameters: DEFAULT_TRACKING_PARAMETERS,
        customParameters: []
      }
    }));
  }

  _handleExpressionState(ws, msg) {
    const d = msg.data || {};
    const file = d.expressionFile || d.file || '';
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'ExpressionStateResponse',
      data: {
        modelLoaded: true,
        modelName: this.model.modelName,
        modelID: this.model.modelID,
        expressions: this.model.hotkeys
          .filter(h => h.action === 'ToggleExpression')
          .map(h => ({ name: h.name, file: h.file, active: false }))
      }
    }));
  }

  _handleExpressionActivation(ws, msg) {
    const d = msg.data || {};
    const file = d.expressionFile || '';
    const active = !!d.active;
    const hotkey = this.model.hotkeys.find(h => h.file === file);
    if (!hotkey) {
      this._sendError(ws, msg, 651, 'ExpressionActivationRequestFileNotFound');
      return;
    }
    this.onCommand('hotkey', { hotkey, active });
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'ExpressionActivationResponse',
      data: {}
    }));
  }

  _handleEventSubscription(ws, msg) {
    const d = msg.data || {};
    // 桌宠简化：接受订阅请求，但不实际推送事件流
    this._send(ws, Object.assign(this._base(msg), {
      messageType: 'EventSubscriptionResponse',
      data: {
        subscribedEventCount: 0,
        subscribedEvents: []
      }
    }));
  }

  _num(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }
}

module.exports = { VtsServer };
