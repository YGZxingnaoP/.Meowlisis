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

    async startSensevoice() {
        const res = await fetch('/api/start_sensevoice', { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start SenseVoice');
        return res.json();
    },

    async startNapcat() {
        const res = await fetch('/api/start_napcat', { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start NapCat');
        return res.json();
    },

    async getCharacterCard(file) {
        const res = await fetch('/api/character_card?file=' + encodeURIComponent(file || 'prompt'));
        if (!res.ok) throw new Error('Failed to load character card');
        return res.json();
    },

    async getCharacterCards() {
        const res = await fetch('/api/character_cards');
        if (!res.ok) return [];
        return res.json();
    },

    async saveCharacterCard(file, data) {
        const res = await fetch('/api/character_card', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file, data })
        });
        if (!res.ok) throw new Error('Failed to save character card');
        return res.json();
    },

    async getRefAudio() {
        const res = await fetch('/api/ref_audio');
        if (!res.ok) return {};
        return res.json();
    },

    async saveRefAudio(data) {
        const res = await fetch('/api/ref_audio', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error('Failed to save ref audio');
        return res.json();
    },

    async getSovitsModels() {
        const res = await fetch('/api/sovits_models');
        if (!res.ok) return { ckpt: [], pth: [] };
        return res.json();
    },

    async getFrontPrompt() {
        const res = await fetch('/api/front_prompt');
        if (!res.ok) return {};
        return res.json();
    },

    async saveFrontPrompt(data) {
        const res = await fetch('/api/front_prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error('Failed to save front prompt');
        return res.json();
    },

    async getSpeakers() {
        const res = await fetch('/api/speakers');
        if (!res.ok) return [];
        return res.json();
    },

    async toggleSpeaker(name, enabled) {
        const res = await fetch('/api/speakers/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, enabled })
        });
        if (!res.ok) throw new Error('Failed to toggle speaker');
        return res.json();
    },

    async buildAllSpeakers() {
        const res = await fetch('/api/speakers/build_all', { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start build');
        return res.json();
    },

    async getBuildStatus() {
        const res = await fetch('/api/speakers/build_status');
        if (!res.ok) return { running: false, progress: '' };
        return res.json();
    },

    async createSpeaker(name, wavFile) {
        const formData = new FormData();
        formData.append('name', name);
        formData.append('wav', wavFile);
        const res = await fetch('/api/speakers/create', {
            method: 'POST',
            body: formData
        });
        if (!res.ok) throw new Error('Failed to create speaker');
        return res.json();
    },

    async verifySite(site, query) {
        const res = await fetch('/api/verify_site', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ site, query: query || '测试' })
        });
        if (!res.ok) throw new Error('Failed to verify site');
        return res.json();
    },

    async verifySessdata(sessdata) {
        const res = await fetch('/api/verify_sessdata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sessdata })
        });
        if (!res.ok) throw new Error('Failed to verify SESSDATA');
        return res.json();
    },

    async startBiliLogin() {
        const res = await fetch('/api/bili_login/start', { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start B站扫码登录');
        return res.json();
    },

    async checkBiliLogin(qrcodeKey) {
        const res = await fetch('/api/bili_login/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ qrcode_key: qrcodeKey || '' })
        });
        if (!res.ok) throw new Error('Failed to check B站扫码登录');
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
