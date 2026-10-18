/**
 * MeowLLM 配置页 —— 后端接口封装
 *
 * 只跟主项目的 config_gui 说两件事：
 *   1. /api/meowllm/config      读写 .vendor/.MeowLLM/config.yml
 *   2. /api/meowllm/control/<x> 代理到 MeowLLM 自己的 /meowllm/control/<x>
 *
 * 第 2 条必须经过主项目代理：配置页在 1801，MeowLLM 在 18100，
 * 浏览器直连是跨域，代理一下就没有 CORS 这回事，也不用在子服务上开 CORS。
 */

const MLApi = {
  async _json(res) {
    const text = await res.text();
    let body;
    try {
      body = text ? JSON.parse(text) : {};
    } catch (e) {
      throw new Error(`返回不是 JSON（HTTP ${res.status}）：${text.slice(0, 200)}`);
    }
    if (!res.ok) {
      // 子服务的错误体是 {"meowllm": {"error": {...}}}，配置接口是 {"error": "..."}
      const inner = body.meowllm && body.meowllm.error;
      const detail = body.error
        || (inner && (inner.message || inner.code || inner.detail))
        || body.message
        || `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return body;
  },

  /** 读整份 meowllm 配置：{ path, data } */
  async getConfig() {
    return this._json(await fetch('/api/meowllm/config', { headers: { Accept: 'application/json' } }));
  },

  /** 写整份 meowllm 配置：{ status, data } */
  async saveConfig(data) {
    return this._json(await fetch('/api/meowllm/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data }),
    }));
  },

  /** GET 控制面（health / stats / version / dmem/status） */
  async controlGet(path) {
    return this._json(await fetch(`/api/meowllm/control/${path}`, { headers: { Accept: 'application/json' } }));
  },

  /** POST 控制面（reload / dmem/write / dmem/forget / dmem/use） */
  async controlPost(path, body) {
    return this._json(await fetch(`/api/meowllm/control/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }));
  },
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { MLApi };
}
