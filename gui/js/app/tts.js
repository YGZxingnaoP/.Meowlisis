/**
 * 应用控制器 - tts 模块
 * 由 app.js 拆分而来，统一挂载到全局 App 对象
 */

Object.assign(App, {
    async openTtsPanel() {
        try {
            const html = Config.tts();
            Modal.show('TTS 设置', html, async () => {
                try {
                    // 1. config.yml 的 tts 节点
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);

                    // 2. 参考音频
                    const refAudio = Config.collectRefAudio();
                    await API.saveRefAudio(refAudio);

                    // 3. tts_infer.yaml 模型配置
                    const ttsModel = Config.collectTtsModel();
                    await API.saveTtsConfig(ttsModel);

                    this.showToast('TTS 配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });

            // 异步填充参考音频与模型配置
            const refAudio = await API.getRefAudio();
            const refPanel = document.getElementById('refAudioPanel');
            if (refPanel) {
                refPanel.innerHTML = Config.refAudioPanel(refAudio);
                Modal.initAutoGrow(refPanel);
            }

            const ttsModel = await API.getTtsConfig();
            const sovitsModels = await API.getSovitsModels();
            const modelPanel = document.getElementById('ttsModelPanel');
            if (modelPanel) modelPanel.innerHTML = Config.ttsModelPanel(ttsModel, sovitsModels);
        } catch (e) {
            console.error('Error rendering tts panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ TTS 子球：模型配置 ============,
    async openTtsModelPanel() {
        try {
            const [ttsModel, sovitsModels, refAudio] = await Promise.all([
                API.getTtsConfig(),
                API.getSovitsModels(),
                API.getRefAudio()
            ]);
            const html = Config.tts_model_panel(ttsModel, sovitsModels);
            Modal.show('TTS 模型配置', html, async () => {
                try {
                    // 1. config.yml 情绪采样参数
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);
                    // 2. 参考音频（ref_audio/config.json）
                    const refAudioData = Config.collectRefAudio();
                    await API.saveRefAudio(refAudioData);
                    // 3. 模型权重（tts_infer.yaml）
                    const ttsModelData = Config.collectTtsModel();
                    await API.saveTtsConfig(ttsModelData);
                    this.showToast('模型配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });

            // 异步填充参考音频
            const refPanel = document.getElementById('refAudioPanel');
            if (refPanel) {
                refPanel.innerHTML = Config.refAudioPanel(refAudio);
                Modal.initAutoGrow(refPanel);
            }
        } catch (e) {
            console.error('Error rendering tts model panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ TTS 子球：参数配置 ============,
    async openTtsParamsPanel() {
        try {
            const ttsModel = await API.getTtsConfig();
            const html = Config.tts_params_panel(ttsModel);
            Modal.show('TTS 参数配置', html, async () => {
                try {
                    // 1. config.yml 的 tts 节点（流式参数 + 音量 + 线程数）
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);
                    // 2. tts_infer.yaml 合成参数（语速/温度/top_k/top_p/切分）
                    const ttsModelData = Config.collectTtsModel();
                    await API.saveTtsConfig(ttsModelData);
                    this.showToast('参数配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering tts params panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },

    // ============ TTS 子球：打断与流式开关 ============,
    async openTtsConfigPanel() {
        try {
            const html = Config.tts_config_panel();
            Modal.show('TTS 打断与流式开关', html, async () => {
                try {
                    const updates = Config.collectValues();
                    Config.applyUpdates(updates, this.config);
                    await API.saveConfig(this.config);
                    this.showToast('配置已保存');
                } catch (e) {
                    this.showToast('保存失败: ' + e.message, true);
                }
            });
        } catch (e) {
            console.error('Error rendering tts config panel:', e);
            this.showToast('面板渲染失败: ' + e.message, true);
        }
    },
});
