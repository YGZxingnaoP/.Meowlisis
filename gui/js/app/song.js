/**
 * 应用控制器 - song 模块
 * 由 app.js 拆分而来，统一挂载到全局 App 对象
 */

Object.assign(App, {
    async openMeowsingerCoverPanel() {
        let models = [], indices = [];
        try {
            const r = await API.getRvcModels();
            models = r.models || [];
            indices = r.indices || [];
        } catch (e) {
            console.warn('加载 RVC 模型列表失败:', e);
        }
        this._openConfigPanel('翻唱设置', () => Config.meowsingerCover(models, indices));
    },

    // ============ LLM 面板（含前置词/后置词） ============,
});
