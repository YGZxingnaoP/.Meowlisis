/**
 * API communication module
 */
const API = {
    baseUrl: '',

    async getConfig() {
        const res = await fetch('/api/config');
        if (!res.ok) throw new Error('Failed to load config');
        return res.json();
    },

    async saveConfig(config) {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        if (!res.ok) throw new Error('Failed to save config');
        return res.json();
    },

    async getTtsConfig() {
        const res = await fetch('/api/tts_config');
        if (!res.ok) return {};
        return res.json();
    },

    async saveTtsConfig(cfg) {
        const res = await fetch('/api/tts_config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg)
        });
        if (!res.ok) throw new Error('Failed to save TTS config');
        return res.json();
    },

    async startMain() {
        const res = await fetch('/api/start_main', { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start main');
        return res.json();
    },

    async startSovits() {
        const res = await fetch('/api/start_sovits', { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start SoVITS');
        return res.json();
    },

    async getPrompt() {
        try {
            const res = await fetch('/api/prompt');
            if (!res.ok) return '';
            return res.text();
        } catch {
            return '';
        }
    },

    async savePrompt(text) {
        await fetch('/api/prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
    }
};
