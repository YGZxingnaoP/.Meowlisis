/**
 * MeowLLM 配置页 —— 字段渲染与取值
 *
 * 设计要点：
 *   * 点号路径的读写都在这里，path 只写一次（schema.js 里）
 *   * 每个字段除了输入框，还会渲染一行 help 说明（需求：每个参数有简单说明）
 *   * 「空输入」不等于「清空」：数字框留空 = 不改，避免一次误删把默认值抹掉
 */

const MLFields = {
  /* ---------------------------------------------------------- 点号路径 */
  read(obj, path) {
    return String(path).split('.').reduce(
      (node, key) => (node && typeof node === 'object' ? node[key] : undefined), obj);
  },

  write(obj, path, value) {
    const keys = String(path).split('.');
    let node = obj;
    for (let i = 0; i < keys.length - 1; i += 1) {
      const key = keys[i];
      if (!node[key] || typeof node[key] !== 'object') node[key] = {};
      node = node[key];
    }
    node[keys[keys.length - 1]] = value;
    return obj;
  },

  /* ---------------------------------------------------------- 渲染 */
  /**
   * 渲染一个字段。
   * @param {object} field schema 里的字段定义
   * @param {*} value 当前配置里的值（可能 undefined）
   */
  render(field, value) {
    const id = `f_${field.path.replace(/\./g, '__')}`;
    const has = value !== undefined && value !== null;
    const raw = has ? value : field.def;
    let control;

    if (field.type === 'checkbox') {
      control = `<label class="mll-switch">
          <input type="checkbox" id="${id}" data-path="${field.path}" ${raw === true ? 'checked' : ''}>
          <span class="mll-switch-track"><span class="mll-switch-dot"></span></span>
          <span class="mll-switch-text">${raw === true ? '开启' : '关闭'}</span>
        </label>`;
    } else if (field.type === 'select') {
      const options = (field.options || []).map((opt) => {
        const item = typeof opt === 'string' ? { value: opt, label: opt } : opt;
        const selected = String(item.value) === String(raw === undefined ? '' : raw) ? 'selected' : '';
        return `<option value="${MLFields.esc(item.value)}" ${selected}>${MLFields.esc(item.label)}</option>`;
      }).join('');
      control = `<select id="${id}" data-path="${field.path}">${options}</select>`;
    } else if (field.type === 'list') {
      const text = Array.isArray(raw) ? raw.join(', ') : (has ? String(raw) : '');
      control = `<input type="text" id="${id}" data-path="${field.path}"
          value="${MLFields.esc(text)}" placeholder="${MLFields.esc(field.placeholder || '逗号分隔，留空 = 空列表')}">`;
    } else if (field.type === 'number') {
      const step = field.step === undefined ? 'any' : field.step;
      const min = field.min === undefined ? '' : ` min="${field.min}"`;
      const max = field.max === undefined ? '' : ` max="${field.max}"`;
      control = `<input type="number" id="${id}" data-path="${field.path}" step="${step}"${min}${max}
          value="${raw === null || raw === undefined ? '' : MLFields.esc(raw)}">`;
    } else {
      // text / path
      control = `<input type="text" id="${id}" data-path="${field.path}"
          value="${raw === null || raw === undefined ? '' : MLFields.esc(raw)}"
          placeholder="${MLFields.esc(field.placeholder || '')}" spellcheck="false"
          ${field.type === 'path' ? 'class="mll-path-input"' : ''}>`;
    }

    const restart = field.restart ? '<span class="mll-tag mll-tag-restart">需重启</span>' : '';
    return `<div class="mll-field" data-field="${field.path}">
        <div class="mll-field-head">
          <label for="${id}">${MLFields.esc(field.label)}${restart}</label>
          <code class="mll-key">${MLFields.esc(field.path)}</code>
        </div>
        ${control}
        ${field.help ? `<div class="mll-help">${MLFields.esc(field.help)}</div>` : ''}
      </div>`;
  },

  /* ---------------------------------------------------------- 取值 */
  /**
   * 从一个输入元素读出「应该写回配置的值」。
   * 返回 undefined 表示「这次不改」（例如数字框被清空）。
   */
  valueOf(el, field) {
    if (field.type === 'checkbox') return el.checked;
    if (field.type === 'list') {
      return String(el.value || '')
        .split(/[,，]/)
        .map((item) => item.trim())
        .filter(Boolean);
    }
    const text = String(el.value == null ? '' : el.value).trim();
    if (field.type === 'number') {
      if (text === '') return undefined;
      const num = Number(text);
      return Number.isNaN(num) ? undefined : num;
    }
    if (field.path === 'gen.seed') {
      // seed 留空要写回 null（而不是 ""），否则采样会拿到一个非数字
      if (text === '') return null;
      const num = Number(text);
      return Number.isNaN(num) ? text : num;
    }
    return text;
  },

  esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { MLFields };
}
