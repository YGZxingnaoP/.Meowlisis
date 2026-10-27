/**
 * CatPaws（手机操作）配置面板
 *
 * 配置真值：.vendor/.CatPaws/config.yml
 * 读写：/api/catpaws/config（gui/tools/catpaws_hub.py）
 * 表单字段用 data-cwp="a.b.c" + data-kind 描述，收集后按嵌套字典提交。
 */
(function () {
    'use strict';

    var CW = {
        data: {}
    };

    CW.set = function (data) {
        this.data = data || {};
    };

    CW._v = function (path, def) {
        var parts = String(path || '').split('.');
        var node = this.data;
        for (var i = 0; i < parts.length; i++) {
            if (node == null || typeof node !== 'object') return def;
            node = node[parts[i]];
        }
        return (node === undefined || node === null) ? def : node;
    };

    CW._t = function (s) {
        try {
            if (typeof I18n !== 'undefined' && I18n && I18n.text) return I18n.text(s);
        } catch (e) { /* ignore */ }
        return s;
    };

    CW._esc = function (s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    };

    CW._text = function (label, path, help) {
        var v = this._v(path, '');
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<input type="text" data-cwp="' + path + '" data-kind="text" value="' + this._esc(v) + '">' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._password = function (label, path, help) {
        var v = this._v(path, '');
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<input type="password" data-cwp="' + path + '" data-kind="text" value="' + this._esc(v) + '">' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._num = function (label, path, help, step) {
        var v = this._v(path, 0);
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<input type="number" data-cwp="' + path + '" data-kind="num" step="' + (step || 1) + '" value="' + this._esc(v) + '">' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._check = function (label, path, help) {
        var v = this._v(path, false);
        return '<div class="form-group"><div class="checkbox-group">' +
            '<input type="checkbox" data-cwp="' + path + '" data-kind="bool" ' + (v ? 'checked' : '') + '>' +
            '<label>' + this._t(label) + '</label></div>' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._select = function (label, path, options, help) {
        var v = String(this._v(path, ''));
        var opts = options.map(function (o) {
            return '<option value="' + o.value + '"' + (String(o.value) === v ? ' selected' : '') + '>' +
                CW._t(o.label) + '</option>';
        }).join('');
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<select data-cwp="' + path + '" data-kind="text">' + opts + '</select>' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._list = function (label, path, help) {
        var v = this._v(path, []);
        if (Array.isArray(v)) v = v.join(', ');
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<input type="text" data-cwp="' + path + '" data-kind="list" value="' + this._esc(v) + '">' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._area = function (label, path, help) {
        var v = this._v(path, '');
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<textarea rows="4" data-cwp="' + path + '" data-kind="text">' + this._esc(v) + '</textarea>' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._kv = function (label, path, help) {
        var obj = this._v(path, {}) || {};
        var lines = Object.keys(obj).map(function (k) { return k + '=' + obj[k]; }).join('\n');
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<textarea rows="4" data-cwp="' + path + '" data-kind="kv">' + this._esc(lines) + '</textarea>' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._tags = function (label, path, help, placeholder) {
        var value = this._v(path, []);
        if (typeof value === 'string') value = value.split(/[,\uFF0C;\uFF1B]/);
        var list = (value || []).map(function (v) { return String(v).trim(); })
            .filter(function (v) { return v.length; });
        var chips = list.map(function (word) {
            return '<span class="split-tag" data-cwp-tag-word="' + this._esc(word) + '">' +
                this._esc(word) +
                '<button type="button" class="split-tag-remove" data-cwp-tag-remove="' + path + '">&times;</button>' +
                '</span>';
        }, this).join('');
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<div class="split-flag-editor cwp-tags" data-cwp-tag-editor="' + path + '">' +
            '<div class="split-tags" data-cwp-tag-list="' + path + '">' +
            (chips || '<span class="help-text">' + this._t('还没有条目，回车添加') + '</span>') +
            '</div>' +
            '<div class="split-add-row cwp-tag-add-row">' +
            '<input type="text" class="split-add-input" data-cwp-tag-input="' + path + '" placeholder="' +
            this._esc(this._t(placeholder || '输入后回车添加')) + '">' +
            '<button type="button" class="cw-tag-add" data-cwp-tag-add="' + path + '">＋</button>' +
            '</div>' +
            '<input type="hidden" data-cwp="' + path + '" data-kind="list" value="' +
            this._esc(list.join(', ')) + '">' +
            '</div>' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._numbers = function (label, path, help, placeholder) {
        var value = this._v(path, []);
        var text = Array.isArray(value) ? value.join(', ') : String(value || '');
        return '<div class="form-group"><label>' + this._t(label) + '</label>' +
            '<input type="text" data-cwp="' + path + '" data-kind="nums" value="' + this._esc(text) +
            '" placeholder="' + this._esc(this._t(placeholder || '留空') ) + '">' +
            (help ? '<div class="help-text">' + this._t(help) + '</div>' : '') + '</div>';
    };

    CW._provider = function (name, title) {
        var base = 'port.' + name + '.';
        var active = String(this._v('port.type', 'deepseek') || 'deepseek');
        var hidden = (name === active) ? '' : ' style="display:none"';
        return '<div class="cwp-provider"' + hidden + ' data-cwp-provider="' + name + '">' +
            '<div class="help-text">' + this._t(title) + '</div>' +
            this._text('接口地址', base + 'base_url') +
            this._password('API Key', base + 'api_key') +
            this._text('模型', base + 'model') +
            this._num('温度', base + 'temperature', '', 0.1) +
            this._num('最大 token', base + 'max_tokens') +
            '</div>';
    };

    CW._render = function () {
        var S = (typeof Config !== 'undefined' && Config._section)
            ? function (t) { return Config._section(t); }
            : function (t) { return '<h4>' + CW._t(t) + '</h4>'; };
        return '' +
            S('触发与停止') +
            this._check('启用手机操作', 'trigger.enabled', '关掉后只有 GUI 手动启动能接管；聊天里的触发词不再生效') +
            this._select('触发模式', 'trigger.trigger_mode', [
                { value: 'both', label: '触发词 + 意图分析' },
                { value: 'prefix', label: '只认触发词' },
                { value: 'intent', label: '只认意图分析词' }
            ], '对应点歌的 prefix / intent：触发词命中直接进链路，意图词命中先让模型判断') +
            this._tags('触发词', 'trigger.prefix', '命中这些词直接开始操作手机（默认「喵呜我要点外卖」）') +
            this._tags('意图分析词', 'trigger.intent', '消息里出现这些词才交给模型判断要不要操作手机') +
            this._area('意图分析提示词', 'trigger.prompt', '留空用内置提示词') +
            this._tags('停止词', 'stop.keywords', '说这些词立刻停手、停链路、停语音（默认「别再操控手机了」「手机还我」）') +

            S('服务与设备') +
            this._text('监听地址（客户端用它连）', 'server.host') +
            this._text('实际绑定地址', 'server.bind_host', '手机要连就用 0.0.0.0，只本机用就 127.0.0.1') +
            this._num('服务端口', 'server.port') +
            this._text('中继地址', 'server.relay_host') +
            this._num('中继端口', 'server.relay_port') +
            this._text('访问令牌', 'server.token', '留空不校验') +
            this._text('设备地址', 'device.ip') +
            this._num('设备端口', 'device.port', '要跟 catpaws-launcher 的 wda_port 一致') +
            this._num('设备超时（秒）', 'device.timeout', '', 0.5) +
            this._check('mock 设备', 'device.mock') +
            this._check('允许操作 mock 设备', 'device.allow_mock', '只在桥接回归测试时打开；真机使用请关掉') +
            this._text('Runner bundle id', 'device.runner_bundle_id') +
            this._text('CatCam bundle id', 'device.catcam_bundle_id') +

            S('模型端口') +
            this._select('端口类型', 'port.type', [
                { value: 'deepseek', label: 'DeepSeek' },
                { value: 'aliyun', label: '通义千问' },
                { value: 'gemini', label: 'Gemini' },
                { value: 'meowllm', label: 'MeowLLM（本地）' }
            ], '手机操作链路的模型完全独立于主项目；func/catpaws 只用它做意图判断') +
            this._provider('deepseek', 'DeepSeek') +
            this._provider('aliyun', '通义千问') +
            this._provider('gemini', 'Gemini') +
            this._provider('meowllm', 'MeowLLM') +
            S('看图') +
            this._text('接口地址', 'vision.base_url') +
            this._password('API Key', 'vision.api_key') +
            this._text('模型', 'vision.model') +
            this._num('截图长边', 'vision.max_edge') +

            S('操作链路') +
            this._check('开始前回桌面', 'agent.start_home') +
            this._check('结束后回桌面', 'agent.exit_to_home', '默认关：任务结束留在当前界面') +
            this._num('单轮最大步数', 'agent.max_rounds', '0 = 不限制', 1) +
            this._num('单链路最大步数', 'agent.max_steps_per_session', '0 = 不限制', 10) +
            this._num('链路超时（秒）', 'agent.session_timeout_sec', '0 = 不掐断', 60) +
            this._num('连续操作步数', 'agent.sequence_steps') +
            this._num('每秒最多操作', 'agent.max_actions_per_second', '', 1) +
            this._num('最小步间隔（毫秒）', 'agent.min_delay_ms', '', 10) +
            this._num('问用户等待（秒）', 'agent.ask_timeout_sec', '0 = 一直等', 10) +
            this._check('允许 OCR 观察', 'agent.allow_ocr') +
            this._num('截图长边', 'agent.screenshot_max_edge', '', 10) +
            this._check('反思阶段', 'agent.reflect_enabled', '任务完成后自动复盘，值得沉淀的流程先问过你才写脚本') +
            this._num('反思轮数上限', 'agent.reflect_max_rounds', '0 = 不限制', 1) +
            this._num('脚本最多文件数', 'agent.action_max_files') +
            this._num('脚本最大字节', 'agent.action_max_bytes', '', 1000) +
            this._num('脚本改动行数上限', 'agent.action_max_change_lines') +
            this._num('滑动最小像素', 'agent.swipe_min_px') +
            this._num('滑动安全边距', 'agent.swipe_margin_px') +
            this._num('滑动速度（px/ms）', 'agent.swipe_speed_px_ms', '', 0.1) +
            this._num('点按边距', 'agent.tap_margin_px') +
            this._check('保存操作缩略图', 'agent.thumb_enabled') +
            this._num('缩略图长边', 'agent.thumb_long_edge') +
            this._num('缩略图质量', 'agent.thumb_quality') +
            this._num('空闲自动点击（秒）', 'agent.keep_awake_sec',
                '防息屏：链路进行中空闲超过这么秒就轻点一下状态栏；0 = 关闭（建议先用系统「自动锁定=永不」）', 5) +
            this._numbers('自动点击坐标（x,y）', 'agent.keep_awake_point',
                '留空 = 状态栏正中；不要填屏幕底部（输入法弹出时那里是空格/发送键）', '留空') +

            S('视频中继') +
            this._num('帧率', 'stream.fps') +
            this._num('长边', 'stream.max_edge') +
            this._num('码率', 'stream.bitrate', '', 100000) +

            S('安全') +
            this._tags('应用白名单', 'guard.app_allowlist', '留空 = 不限制（黑名单仍然生效）', '输入 bundle_id 后回车') +
            this._tags('应用黑名单', 'guard.app_denylist', '', '输入 bundle_id 后回车') +
            this._kv('应用别名（名称=bundle_id）', 'guard.apps') +
            this._tags('敏感词', 'guard.sensitive_words', '界面出现这些词时按敏感操作处理') +
            this._check('敏感操作要确认', 'guard.sensitive_confirm') +
            this._tags('反思阶段禁用词', 'guard.reflect_block_words', '反思时碰到这些词的操作一律拦住（付款、隐私类）') +

            S('与主项目的桥接') +
            this._num('轮询间隔（秒）', 'sync.poll_sec', '', 0.1) +
            this._num('单次链路上限（秒）', 'sync.max_run_sec', '0 = 不限制', 60) +
            this._num('等主人回答（秒）', 'sync.answer_timeout', '', 10) +
            this._check('回传记忆与播报', 'sync.notify', '角色说的每句话写进长期记忆/摘要/短期记忆并走 TTS') +
            this._num('短期记忆轮数', 'sync.short_rounds', '启动时带给手机链路的对话轮数');
    };

    CW.collect = function () {
        var root = document.getElementById('modalBody');
        if (!root) return null;
        var out = {};
        var nodes = root.querySelectorAll('[data-cwp]');
        Array.prototype.forEach.call(nodes, function (node) {
            var path = node.getAttribute('data-cwp');
            var kind = node.getAttribute('data-kind') || 'text';
            var value;
            if (kind === 'bool') value = !!node.checked;
            else if (kind === 'num') {
                var raw = String(node.value || '').trim();
                if (raw === '') return;
                var num = Number(raw);
                value = (Math.abs(num - Math.round(num)) < 1e-9) ? parseInt(raw, 10) : num;
            } else if (kind === 'list') {
                value = String(node.value || '').split(/[,\uFF0C;\uFF1B\n]/)
                    .map(function (s) { return s.trim(); })
                    .filter(function (s) { return s.length; });
            } else if (kind === 'nums') {
                value = String(node.value || '').split(/[,\uFF0C;\uFF1B\s]+/)
                    .map(function (s) { return Number(s); })
                    .filter(function (n) { return !isNaN(n) && n >= 0; });
            } else if (kind === 'kv') {
                value = {};
                String(node.value || '').split(/\n/).forEach(function (line) {
                    var idx = line.indexOf('=');
                    if (idx <= 0) return;
                    var k = line.slice(0, idx).trim();
                    var v = line.slice(idx + 1).trim();
                    if (k) value[k] = v;
                });
            } else {
                value = String(node.value == null ? '' : node.value);
            }
            CW._assign(out, path, value);
        });
        return out;
    };

    CW._assign = function (root, path, value) {
        var parts = String(path).split('.');
        var node = root;
        for (var i = 0; i < parts.length - 1; i++) {
            if (typeof node[parts[i]] !== 'object' || node[parts[i]] === null) node[parts[i]] = {};
            node = node[parts[i]];
        }
        node[parts[parts.length - 1]] = value;
    };

    // ---- 标签编辑器 / 端口类型切换：文档级事件委托，面板重绘不用重绑 ----
    CW._syncTags = function (path) {
        var root = document.getElementById('modalBody');
        if (!root) return;
        var editor = root.querySelector('[data-cwp-tag-editor="' + path + '"]');
        if (!editor) return;
        var words = [];
        Array.prototype.forEach.call(editor.querySelectorAll('[data-cwp-tag-word]'), function (chip) {
            var word = chip.getAttribute('data-cwp-tag-word');
            if (word) words.push(word);
        });
        var hidden = editor.querySelector('[data-cwp="' + path + '"]');
        if (hidden) hidden.value = words.join(', ');
        var list = editor.querySelector('[data-cwp-tag-list="' + path + '"]');
        if (list && !words.length) {
            list.innerHTML = '<span class="help-text">' + CW._t('还没有条目，回车添加') + '</span>';
        }
    };

    CW._renderTags = function (path) {
        var root = document.getElementById('modalBody');
        if (!root) return;
        var list = root.querySelector('[data-cwp-tag-list="' + path + '"]');
        if (!list) return;
        var words = [];
        Array.prototype.forEach.call(list.querySelectorAll('[data-cwp-tag-word]'), function (chip) {
            var word = chip.getAttribute('data-cwp-tag-word');
            if (word) words.push(word);
        });
        if (!words.length) {
            list.innerHTML = '<span class="help-text">' + CW._t('还没有条目，回车添加') + '</span>';
        } else {
            list.innerHTML = words.map(function (word) {
                return '<span class="split-tag" data-cwp-tag-word="' + CW._esc(word) + '">' + CW._esc(word) +
                    '<button type="button" class="split-tag-remove" data-cwp-tag-remove="' + path + '">&times;</button>' +
                    '</span>';
            }).join('');
        }
        var hidden = root.querySelector('[data-cwp="' + path + '"]');
        if (hidden) hidden.value = words.join(', ');
    };

    CW._addTag = function (path, word) {
        var body = String(word || '').replace(/[,\uFF0C;\uFF1B]/g, ' ').trim();
        if (!body) return;
        var root = document.getElementById('modalBody');
        var list = root && root.querySelector('[data-cwp-tag-list="' + path + '"]');
        if (!list) return;
        var exists = Array.prototype.some.call(list.querySelectorAll('[data-cwp-tag-word]'), function (chip) {
            return chip.getAttribute('data-cwp-tag-word') === body;
        });
        if (exists) return;
        var holder = document.createElement('span');
        holder.className = 'split-tag';
        holder.setAttribute('data-cwp-tag-word', body);
        holder.innerHTML = CW._esc(body) +
            '<button type="button" class="split-tag-remove" data-cwp-tag-remove="' + path + '">&times;</button>';
        if (list.querySelector('.help-text')) list.innerHTML = '';
        list.appendChild(holder);
        CW._syncTags(path);
    };

    CW._toggleProvider = function (value) {
        var root = document.getElementById('modalBody');
        if (!root) return;
        Array.prototype.forEach.call(root.querySelectorAll('[data-cwp-provider]'), function (block) {
            block.style.display = (block.getAttribute('data-cwp-provider') === value) ? '' : 'none';
        });
    };

    if (typeof Config !== 'undefined') {
        Config.cwp = CW;
        Config.catpaws = function () { return CW._render(); };
        Config.collectCatpaws = function () { return CW.collect(); };
        Config.setCatpawsConfig = function (cfg) { CW.set(cfg); };
    }

    if (typeof document !== 'undefined' && !window.__cwpBound) {
        window.__cwpBound = true;
        document.addEventListener('click', function (ev) {
            var remove = ev.target.closest ? ev.target.closest('[data-cwp-tag-remove]') : null;
            if (remove) {
                var path = remove.getAttribute('data-cwp-tag-remove');
                var chip = remove.closest('[data-cwp-tag-word]');
                if (chip && chip.parentNode) chip.parentNode.removeChild(chip);
                CW._renderTags(path);
                return;
            }
            var add = ev.target.closest ? ev.target.closest('[data-cwp-tag-add]') : null;
            if (add) {
                var box = add.closest('[data-cwp-tag-editor]');
                var input = box && box.querySelector('[data-cwp-tag-input]');
                if (input) {
                    CW._addTag(box.getAttribute('data-cwp-tag-editor'), input.value);
                    input.value = '';
                }
            }
        });
        document.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Enter') return;
            var input = ev.target.closest ? ev.target.closest('[data-cwp-tag-input]') : null;
            if (!input) return;
            ev.preventDefault();
            var box = input.closest('[data-cwp-tag-editor]');
            if (!box) return;
            CW._addTag(box.getAttribute('data-cwp-tag-editor'), input.value);
            input.value = '';
        });
        document.addEventListener('change', function (ev) {
            var node = ev.target;
            if (node && node.getAttribute && node.getAttribute('data-cwp') === 'port.type') {
                CW._toggleProvider(node.value);
            }
        });
    }
})();
