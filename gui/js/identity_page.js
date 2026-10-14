const IdentityUI = {
    detail: null,
    t(s) {
        return (window.Config && Config._t) ? Config._t(s) : s;
    },
    esc(s) {
        return String(s === undefined || s === null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },
    cfg(path, def) {
        return (window.Config && Config._val) ? Config._val(path, def) : def;
    },
    html() {
        return '<div class="form-section"><h4>' + this.t('用户 ID') + '</h4></div>' +
            '<div class="help-text">' + this.t('输入编号（或昵称）查这个人，逐个平台看绑定情况') + '</div>' +
            '<div class="form-group"><label>' + this.t('编号或昵称') + '</label>' +
            '<input type="text" id="identityQuery" placeholder="000001"' +
            ' onkeydown="if(event.key===\'Enter\'){IdentityUI.query();}"></div>' +
            '<div class="speaker-actions">' +
            '<button class="btn btn-primary" onclick="IdentityUI.query()">' + this.t('查询') + '</button>' +
            '<button class="btn btn-secondary" onclick="IdentityUI.clear()">' + this.t('清空') + '</button>' +
            '</div>' +
            '<div id="identityMsg" class="help-text"></div>' +
            '<div id="identityDetail"></div>' +
            '<div class="form-section"><h4>' + this.t('绑定指令') + '</h4></div>' +
            '<div class="form-group"><label>' + this.t('绑定前缀词') + '</label>' +
            '<input type="text" data-path="identity.bind_prefix" value="' +
            this.esc(this.cfg('identity.bind_prefix', 'Meowlisis账号绑定')) +
            '" placeholder="Meowlisis账号绑定">' +
            '<div class="help-text">' + this.t('用户发「前缀词 + 帮助」看用法；前缀词 + qq QQ号 或 前缀词 + bili uid/昵称 即完成绑定') + '</div>' +
            '</div>';
    },
    msg(text, bad) {
        const el = document.getElementById('identityMsg');
        if (!el) return;
        el.textContent = text || '';
        el.style.color = bad ? '#e66' : '';
    },
    val(id) {
        const el = document.getElementById(id);
        return el ? el.value.trim() : '';
    },
    clear() {
        const box = document.getElementById('identityQuery');
        if (box) box.value = '';
        const detail = document.getElementById('identityDetail');
        if (detail) detail.innerHTML = '';
        this.detail = null;
        this.msg('');
    },
    async post(url, payload) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await res.json();
    },
    async query() {
        const key = this.val('identityQuery');
        if (!key) { this.msg(this.t('先填编号或昵称'), true); return; }
        try {
            const res = await fetch('/api/identity/user?id=' + encodeURIComponent(key));
            if (!res.ok) {
                this.msg(this.t('接口没响应') + '（' + res.status + '）：' + this.t('请重启配置管理器后再试'), true);
                return;
            }
            const data = await res.json();
            const detail = document.getElementById('identityDetail');
            if (!data || !data.id) {
                if (detail) detail.innerHTML = '';
                this.detail = null;
                this.msg(this.t('没找到') + '：' + key, true);
                return;
            }
            this.detail = data;
            this.msg('');
            this.renderDetail();
        } catch (e) {
            this.msg(this.t('读取失败') + ': ' + e, true);
        }
    },
    renderDetail() {
        const d = this.detail || {};
        const box = document.getElementById('identityDetail');
        if (!box) return;
        let rows = '';
        (d.platforms || []).forEach(p => {
            const key = this.esc(p.key);
            const account = this.esc(p.account);
            rows += '<div class="form-group"><label>' + this.esc(p.label) + '</label>' +
                '<input type="text" id="idacct_' + key + '" value="' + account + '" placeholder="' +
                this.t('填账号：QQ号 / B站uid / 声纹名') + '">' +
                '<div class="speaker-actions">' +
                '<button class="btn btn-primary" onclick="IdentityUI.bind(\'' + key + '\')">' +
                (p.account ? this.t('更换') : this.t('绑定')) + '</button>' +
                '<button class="btn btn-secondary" onclick="IdentityUI.unbind(\'' + key + '\')">' +
                this.t('解绑') + '</button>' +
                '</div></div>';
        });
        box.innerHTML = '<div class="char-card">' +
            '<div class="char-card-title">' + this.t('用户档案') + '</div>' +
            '<div class="help-text">' + this.t('好感度') + ' ' + this.esc(d.affinity) + ' · ' +
            this.t('生日') + ' ' + this.esc(d.birthday || this.t('未知')) + '</div>' +
            '<div class="form-group"><label>' + this.t('编号') + '</label>' +
            '<input type="text" id="identityId" value="' + this.esc(d.id) + '" disabled>' +
            '</div>' +
            '<div class="form-group"><label>' + this.t('昵称') + '</label>' +
            '<input type="text" id="identityNick" value="' + this.esc(d.nickname || '') + '" placeholder="' +
            this.t('所有平台统一用这个称呼') + '">' +
            '<div class="speaker-actions">' +
            '<button class="btn btn-secondary" onclick="IdentityUI.nickname()">' + this.t('改昵称') + '</button>' +
            '</div></div>' +
            '<div class="form-section"><h4>' + this.t('平台绑定') + '</h4></div>' +
            rows +
            '</div>';
    },
    async nickname() {
        const nickname = this.val('identityNick');
        if (!nickname) { this.msg(this.t('先填新昵称'), true); return; }
        const data = await this.post('/api/identity/nickname', { id: this.detail.id, nickname: nickname });
        this.msg(data.message || (data.status === 'ok' ? this.t('昵称已更新') : this.t('改昵称失败')), data.status !== 'ok');
        this.query();
    },
    async bind(platform) {
        const account = this.val('idacct_' + platform);
        if (!account) { this.msg(this.t('先填要绑的账号'), true); return; }
        const data = await this.post('/api/identity/bind', { id: this.detail.id, platform: platform, account: account });
        this.msg(data.message || (data.status === 'ok' ? this.t('绑定成功') : this.t('绑定失败')), data.status !== 'ok');
        this.query();
    },
    async unbind(platform) {
        const data = await this.post('/api/identity/unbind', { id: this.detail.id, platform: platform });
        this.msg(data.message || (data.status === 'ok' ? this.t('已解绑') : this.t('解绑失败')), data.status !== 'ok');
        this.query();
    }
};

Object.assign(Config, {
    identityUsers() {
        return IdentityUI.html();
    }
});
