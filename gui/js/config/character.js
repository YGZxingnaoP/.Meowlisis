/**
 * 配置面板生成器 - character 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
    characterCardConfig(files) {
        let h = this._section('角色卡选择');
        const cur = this._val('character_card.card_file', 'prompt');
        const opts = (files || []).map(f => {
            const v = f.replace(/\.json$/, '');
            return `<option value="${v}" ${v === cur ? 'selected' : ''}>${v}</option>`;
        }).join('');
        h += `<div class="form-group"><label>角色卡文件</label>
            <select data-path="character_card.card_file" id="cardFileSelect">${opts || '<option value="prompt">prompt</option>'}</select></div>`;
        h += this._text('当前选中角色名', 'character_card.select', '');
        h += `<div class="speaker-actions">
            <button class="btn btn-secondary" id="newCardBtn">新建角色卡</button>
        </div>`;
        return h;
    },
    characterCardData(data) {
        const chars = (data && data.characters) || [];
        let h = this._section('角色卡内容');
        if (!chars.length) {
            h += `<div class="help-text">暂无角色数据，请点击下方新建</div>`;
            return h;
        }
        const c = chars[0];

        // 共用字段
        h += this._charText('角色名称', 'name', c.name) +
            this._charText('昵称', 'nickname', c.nickname) +
            this._charText('外貌', 'appearance', c.appearance) +
            this._charText('生日', 'birthday', c.birthday) +
            this._charText('身份证号', 'id_card', c.id_card) +
            this._charText('QQ号', 'qq', c.qq) +
            this._charText('手机号', 'phone', c.phone) +
            this._charText('MBTI', 'mbti', c.mbti) +
            this._charText('最喜欢的东西', 'favorite', c.favorite) +
            this._charText('爱好', 'hobbies', c.hobbies) +
            this._charText('讨厌的东西', 'dislikes', c.dislikes) +
            this._charText('人际关系', 'relationships', c.relationships);

        // 设定（字典，多条）
        h += this._section('角色设定（多条）');
        h += `<div id="settingList">`;
        const setting = c.setting || {};
        if (setting && typeof setting === 'object') {
            Object.keys(setting).forEach((k, i) => {
                h += this._settingRow(i, k, setting[k]);
            });
        }
        h += `</div>`;
        h += `<button class="btn btn-secondary" id="addSettingBtn">添加设定</button>`;

        // 性格（字典，多条）
        h += this._section('角色性格（多条，每条含提示词）');
        h += `<div id="personalityList">`;
        const personality = c.personality || {};
        if (personality && typeof personality === 'object') {
            Object.keys(personality).forEach((k, i) => {
                h += this._personalityRow(i, k, personality[k]);
            });
        }
        h += `</div>`;
        h += `<button class="btn btn-secondary" id="addPersonalityBtn">新建性格</button>`;
        return h;
    },
    _charText(label, field, value) {
        return `<div class="form-group"><label>${label}</label>
            <textarea class="auto-grow" rows="2" data-char-field="${field}">${this._esc(value)}</textarea>
        </div>`;
    },
    _settingRow(index, key, value) {
        return `<div class="dict-row" data-dict-index="${index}">
            <div class="form-group"><label>设定名</label>
                <input type="text" data-setting-key value="${key == null ? '' : key}"></div>
            <div class="form-group"><label>设定内容</label>
                <textarea class="auto-grow" rows="2" data-setting-value>${this._esc(value)}</textarea></div>
        </div>`;
    },
    _personalityRow(index, key, value) {
        return `<div class="dict-row" data-dict-index="${index}">
            <div class="form-group"><label>性格名</label>
                <input type="text" data-personality-key value="${key == null ? '' : key}"></div>
            <div class="form-group"><label>性格提示词</label>
                <textarea class="auto-grow" rows="2" data-personality-value>${this._esc(value)}</textarea></div>
        </div>`;
    },
});
