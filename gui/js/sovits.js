/**
 * SoVITS specific logic
 */
const Sovits = {
    renderPanel() {
        const cfg = window._config || {};
        const tts = cfg.tts || {};
        const api = tts.api || {};

        return `
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
