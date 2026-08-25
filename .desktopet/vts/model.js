// vts/model.js
// 模型状态与参数映射：解析 vtube.json / cdi3.json，构建 VTS 输入参数 ↔ Live2D 参数映射

const fs = require('fs');
const path = require('path');

// VTS 标准追踪参数（defaultParameters 的默认值，与 VTube Studio 保持一致）
const DEFAULT_TRACKING_PARAMETERS = [
  { name: 'FaceAngleX', value: 0, min: -30, max: 30, defaultValue: 0 },
  { name: 'FaceAngleY', value: 0, min: -30, max: 30, defaultValue: 0 },
  { name: 'FaceAngleZ', value: 0, min: -30, max: 30, defaultValue: 0 },
  { name: 'MouthSmile', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'MouthOpen', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'EyeOpenLeft', value: 1, min: 0, max: 1, defaultValue: 1 },
  { name: 'EyeOpenRight', value: 1, min: 0, max: 1, defaultValue: 1 },
  { name: 'EyeLeftX', value: 0, min: -1, max: 1, defaultValue: 0 },
  { name: 'EyeLeftY', value: 0, min: -1, max: 1, defaultValue: 0 },
  { name: 'EyeRightX', value: 0, min: -1, max: 1, defaultValue: 0 },
  { name: 'EyeRightY', value: 0, min: -1, max: 1, defaultValue: 0 },
  { name: 'Brows', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'CheekPuff', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'TongueOut', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'MouthX', value: 0, min: -1, max: 1, defaultValue: 0 },
  { name: 'VoiceVolume', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'VoiceVolumePlusMouthOpen', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'VoiceFrequency', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'VoiceFrequencyPlusMouthSmile', value: 0, min: 0, max: 1, defaultValue: 0 },
  { name: 'BodyAngleX', value: 0, min: -30, max: 30, defaultValue: 0 },
  { name: 'BodyAngleY', value: 0, min: -30, max: 30, defaultValue: 0 },
  { name: 'BodyAngleZ', value: 0, min: -30, max: 30, defaultValue: 0 },
  { name: 'Breath', value: 0, min: 0, max: 1, defaultValue: 0 }
];

// 补充别名映射：客户端注入的 VTS 参数名 → Live2D 参数（当 vtube.json 无对应映射时使用）
const ALIAS_MAP = {
  'MouthOpen': { id: 'ParamMouthOpenY', inMin: 0, inMax: 1, outMin: 0, outMax: 1 },
  'MouthSmile': { id: 'ParamMouthForm', inMin: 0, inMax: 1, outMin: 0, outMax: 1 }
};

class VtsModel {
  constructor(cfg) {
    this.cfg = cfg;
    this.modelDir = path.resolve(cfg.model.dir);
    this.vtubePath = path.join(this.modelDir, cfg.model.vtube);
    this.cdi3Path = path.join(this.modelDir, cfg.model.cdi3);

    this.modelID = '6b4a955054cb4089a950f6a07b65c4f1';
    this.modelName = 'MiaoWu-l2d';
    this.modelLoaded = true;

    // VTS 输入参数 → Live2D 参数映射（一对多，含范围映射）
    this.paramMap = {};   // inputName -> [{id, inMin, inMax, outMin, outMax}]
    this.live2dParams = [];   // Live2D 参数列表（来自 cdi3.json）
    this.hotkeys = [];        // 表情热键 [{hotkeyID, name, file, action}]

    this.positionX = 0;
    this.positionY = 0;
    this.rotation = 0;
    this.size = 0;            // VTS size (-100 ~ +100)
    this.scale = 1.0;         // 实际渲染缩放

    this._load();
  }

  _load() {
    this._loadVtube();
    this._loadCdi3();
    this._buildAliasMap();
  }

  _loadVtube() {
    try {
      const raw = fs.readFileSync(this.vtubePath, 'utf-8');
      const vtube = JSON.parse(raw);
      this.modelID = vtube.ModelID || this.modelID;
      this.modelName = vtube.Name || this.modelName;

      // 参数映射
      const settings = vtube.ParameterSettings || [];
      for (const s of settings) {
        const input = s.Input;
        const out = s.OutputLive2D;
        if (!input || !out) continue;
        if (!this.paramMap[input]) this.paramMap[input] = [];
        this.paramMap[input].push({
          id: out,
          inMin: s.InputRangeLower || 0,
          inMax: s.InputRangeUpper || 1,
          outMin: s.OutputRangeLower || 0,
          outMax: s.OutputRangeUpper || 1
        });
      }

      // 热键
      const hotkeys = vtube.Hotkeys || [];
      for (const h of hotkeys) {
        this.hotkeys.push({
          hotkeyID: h.HotkeyID || '',
          name: h.Name || '',
          action: h.Action || '',
          file: h.File || ''
        });
      }
    } catch (e) {
      console.error('[model] 解析 vtube.json 失败:', e.message);
    }
  }

  _loadCdi3() {
    try {
      const raw = fs.readFileSync(this.cdi3Path, 'utf-8');
      const cdi3 = JSON.parse(raw);
      const params = cdi3.Parameters || [];
      const seen = new Set();
      for (const p of params) {
        if (!p.Id || seen.has(p.Id)) continue;
        seen.add(p.Id);
        this.live2dParams.push({
          name: p.Id,
          value: 0,
          min: -30,
          max: 30,
          defaultValue: 0
        });
      }
    } catch (e) {
      console.error('[model] 解析 cdi3.json 失败:', e.message);
    }
  }

  _buildAliasMap() {
    // 补充 vtube.json 未覆盖的常见别名（如 Meowlisis 默认注入的 MouthOpen）
    for (const input of Object.keys(ALIAS_MAP)) {
      if (!this.paramMap[input]) {
        this.paramMap[input] = [ALIAS_MAP[input]];
      }
    }
  }

  // 把 VTS 输入参数值映射为 Live2D 参数值列表
  mapInputToLive2D(inputName, value) {
    const mappings = this.paramMap[inputName];
    if (!mappings || mappings.length === 0) return [];
    const out = [];
    for (const m of mappings) {
      // 线性映射：inRange -> outRange
      let v = value;
      const inSpan = m.inMax - m.inMin;
      const outSpan = m.outMax - m.outMin;
      if (inSpan !== 0) {
        const t = (value - m.inMin) / inSpan;
        v = m.outMin + t * outSpan;
      }
      out.push({ id: m.id, value: v });
    }
    return out;
  }

  // 获取当前模型信息（CurrentModelResponse 的 data 部分）
  getCurrentModelData() {
    return {
      modelLoaded: this.modelLoaded,
      modelName: this.modelName,
      modelID: this.modelID,
      vtsModelName: this.cfg.model.vtube,
      vtsModelIconName: '',
      live2DModelName: this.cfg.model.model3,
      modelLoadTime: 0,
      timeSinceModelLoaded: 0,
      numberOfLive2DParameters: this.live2dParams.length,
      numberOfLive2DArtmeshes: 0,
      hasPhysicsFile: true,
      numberOfTextures: 1,
      textureResolution: 8192,
      modelPosition: {
        positionX: this.positionX,
        positionY: this.positionY,
        rotation: this.rotation,
        size: this.size
      }
    };
  }

  // 触发热键：按 hotkeyID 或 name 匹配表情
  findHotkey(hotkeyID) {
    if (!hotkeyID) return null;
    let h = this.hotkeys.find(x => x.hotkeyID === hotkeyID);
    if (!h) h = this.hotkeys.find(x => x.name === hotkeyID);
    return h || null;
  }

  // VTS size(-100~+100) -> 渲染 scale，采用指数映射 size=0 => 1x
  static sizeToScale(size) {
    return Math.pow(2, size / 100);
  }
}

module.exports = { VtsModel, DEFAULT_TRACKING_PARAMETERS };
