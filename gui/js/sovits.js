/**
 * SoVITS specific logic
 */
const Sovits = {
    renderPanel() {
        const cfg = window._config || {};
        const tts = cfg.tts || {};
        const api = tts.api || {};
        const model = tts.model || {};

        return `
            <div class="form-group">
                <label>推理设备</label>
                <select data-path="tts.api.device">
                    <option value="cuda" ${api.device === 'cuda' ? 'selected' : ''}>CUDA (GPU)</option>
                    <option value="cpu" ${api.device === 'cpu' ? 'selected' : ''}>CPU</option>
                </select>
            </div>
            <div class="form-group">
                <label>半精度推理</label>
                <div class="checkbox-group">
                    <input type="checkbox" data-path="tts.api.is_half" ${api.is_half ? 'checked' : ''}>
                    <label>启用半精度 (is_half)</label>
                </div>
            </div>
            <div class="form-group">
                <label>GPT 模型路径</label>
                <input type="text" data-path="tts.model.gpt_path" value="${model.gpt_path || ''}" placeholder=".ckpt 文件路径">
            </div>
            <div class="form-group">
                <label>SoVITS 模型路径</label>
                <input type="text" data-path="tts.model.sovits_path" value="${model.sovits_path || ''}" placeholder=".pth 文件路径">
            </div>
            <div class="form-group">
                <label>API Host</label>
                <input type="text" data-path="tts.api.host" value="${api.host || '127.0.0.1'}">
            </div>
            <div class="form-group">
                <label>API Port</label>
                <input type="number" data-path="tts.api.port" value="${api.port || 9880}">
            </div>
            <div class="form-group">
                <button class="btn btn-primary" id="sovitsStartBtn">启动 SoVITS</button>
            </div>
        `;
    },

    bindEvents() {
        const btn = document.getElementById('sovitsStartBtn');
        if (btn) {
            btn.addEventListener('click', async () => {
                try {
                    await API.startSovits();
                    App.showToast('SoVITS 已启动');
                } catch (e) {
                    App.showToast('SoVITS 启动失败: ' + e.message, true);
                }
            });
        }
    }
};
