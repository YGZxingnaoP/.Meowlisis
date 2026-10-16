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
            '<div class="char-card" style="margin-bottom:12px;">' +
            '<div class="form-group" style="margin-bottom:8px;">' +
            '<label>' + this.t('查询用户') + '</label>' +
            '<div style="display:flex;gap:8px;align-items:center;">' +
            '<input type="text" id="identityQuery" style="flex:1;min-width:0;" placeholder="' +
            this.t('编号 / 昵称 / QQ号 / B站uid') + '"' +
            ' onkeydown="if(event.key===\'Enter\'){IdentityUI.query();}">' +
            '<button class="btn btn-primary" style="white-space:nowrap;" onclick="IdentityUI.query()">' +
            this.t('查询') + '</button>' +
            '<button class="btn btn-secondary" style="white-space:nowrap;" onclick="IdentityUI.clear()">' +
            this.t('清空') + '</button>' +
            '</div>' +
            '<div class="help-text">' + this.t('四种写法都认：编号 000001、昵称、QQ 号、B 站 uid') + '</div>' +
            '</div>' +
            '<div id="identityMsg" class="help-text" style="min-height:16px;"></div>' +
            '</div>' +
            '<div id="identityDetail"></div>' +
            '<div class="form-section"><h4>' + this.t('绑定指令') + '</h4></div>' +
            '<div class="form-group"><label>' + this.t('绑定前缀词') + '</label>' +
            '<input type="text" data-path="identity.bind_prefix" value="' +
            this.esc(this.cfg('identity.bind_prefix', 'Meowlisis账号绑定')) +
            '" placeholder="Meowlisis账号绑定">' +
            '<div class="help-text">' + this.t('用户发「前缀词 + 帮助」看用法；前缀词 + qq QQ号 或 前缀词 + bili uid/昵称 即完成绑定') + '</div>' +
            '</div>' +
            '<div class="form-section"><h4>' + this.t('B站登录态（身份反查用）') + '</h4></div>' +
            '<div class="form-group"><label>SESSDATA</label>' +
            '<input type="text" data-path="identity.sessdata" value="' +
            this.esc(this.cfg('identity.sessdata', '')) + '">' +
            '<div class="help-text">' + this.t('只读这里：按 B站昵称反查 uid（用户ID 绑定、弹幕身份）都用这个登录态') + '</div>' +
            '</div>' +
            '<div class="form-group"><label>bili_jct</label>' +
            '<input type="text" data-path="identity.bili_jct" value="' +
            this.esc(this.cfg('identity.bili_jct', '')) + '">' +
            '<div style="margin-top:6px;">' +
            '<button class="btn btn-secondary" onclick="App.openBiliLogin(\'identity\')">' +
            this.t('B站扫码登录') + '</button></div>' +
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
        if (!key) { this.msg(this.t('先填编号 / 昵称 / QQ号 / B站uid'), true); return; }
        try {
            const res = await fetch('/api/identity/user?ref=' + encodeURIComponent(key));
            if (!res.ok) {
                this.msg(this.t('接口没响应') + '（' + res.status + '）：' + this.t('请重启配置管理器后再试'), true);
                return;
            }
            const data = await res.json();
            const detail = document.getElementById('identityDetail');
            if (!data || !data.meowid) {
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
        (d.channels || []).forEach(p => {
            const key = this.esc(p.key);
            const account = this.esc(p.ext_account);
            rows += '<div class="bind-row" style="display:flex;gap:8px;align-items:flex-end;margin-bottom:10px;">' +
                '<div style="flex:1;min-width:0;">' +
                '<label style="display:block;margin-bottom:4px;">' + this.esc(p.label) + '</label>' +
                '<input type="text" id="idacct_' + key + '" value="' + account + '" placeholder="' +
                this.t('填账号：QQ号 / B站uid / 声纹名') + '">' +
                '</div>' +
                '<button class="btn btn-primary" style="white-space:nowrap;" onclick="IdentityUI.bind(\'' + key + '\')">' +
                (p.ext_account ? this.t('更换') : this.t('绑定')) + '</button>' +
                '<button class="btn btn-secondary" style="white-space:nowrap;" onclick="IdentityUI.unbind(\'' + key + '\')">' +
                this.t('解绑') + '</button>' +
                '</div>';
        });
        box.innerHTML =
            '<div class="char-card">' +
            '<div style="margin-bottom:10px;">' +
            '<div style="font-size:18px;font-weight:600;line-height:1.3;">' +
            this.esc(d.nickname || this.t('未设昵称')) + '</div>' +
            '<div class="uid-sub">' + this.esc(d.meowid) + '</div>' +
            '</div>' +
            '<div class="help-text" style="margin-bottom:12px;">' +
            this.t('好感度') + ' ' + this.esc(d.affinity) + ' &nbsp;&middot;&nbsp; ' +
            this.t('生日') + ' ' + this.esc(d.birthday || this.t('未知')) +
            '</div>' +
            '<div class="form-group"><label>' + this.t('昵称') + '</label>' +
            '<div style="display:flex;gap:8px;align-items:center;">' +
            '<input type="text" id="identityNick" style="flex:1;min-width:0;" value="' +
            this.esc(d.nickname || '') + '" placeholder="' + this.t('所有平台统一用这个称呼') + '">' +
            '<button class="btn btn-secondary" style="white-space:nowrap;" onclick="IdentityUI.nickname()">' +
            this.t('改昵称') + '</button>' +
            '</div>' +
            '<div class="help-text">' + this.t('昵称可以重复，区分人只看编号（meowid）') + '</div>' +
            '</div>' +
            '<div class="form-section"><h4>' + this.t('通道绑定') + '</h4></div>' +
            rows +
            '</div>';
    },
    async nickname() {
        const nickname = this.val('identityNick');
        if (!nickname) { this.msg(this.t('先填新昵称'), true); return; }
        const data = await this.post('/api/identity/nickname', { meowid: this.detail.meowid, nickname: nickname });
        this.msg(data.message || (data.status === 'ok' ? this.t('昵称已更新') : this.t('改昵称失败')), data.status !== 'ok');
        this.query();
    },
    async bind(platform) {
        const account = this.val('idacct_' + platform);
        if (!account) { this.msg(this.t('先填要绑的账号'), true); return; }
        const data = await this.post('/api/identity/bind', { meowid: this.detail.meowid, channel: platform, ext_account: account });
        this.msg(data.message || (data.status === 'ok' ? this.t('绑定成功') : this.t('绑定失败')), data.status !== 'ok');
        this.query();
    },
    async unbind(platform) {
        const data = await this.post('/api/identity/unbind', { meowid: this.detail.meowid, channel: platform });
        this.msg(data.message || (data.status === 'ok' ? this.t('已解绑') : this.t('解绑失败')), data.status !== 'ok');
        this.query();
    }
};

Object.assign(Config, {
    identityUsers() {
        return IdentityUI.html();
    }
});
