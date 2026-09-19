/**
 * Orbit 系统（卡片版）
 *
 * - 中心启动球 / 工具箱父级模型球：保留球形态
 * - 外层配置卡 13 / 启动卡 9 / 工具箱卡 10：卡面 = resource/cat_photos/{id}.png
 * - 有子卡的卡：点击 → 该卡放大到中央 + 子卡扇形摊开
 * - 无子卡的卡：点击 → 直接开配置面板（Modal 从该卡位置放大）
 * - 已摊开的父卡（self=true 的）：再点 → 打开父卡自身的配置面板；否则收起
 * - 点击空白 / 点中心球：整个收起
 *
 * 数据表里的 id 与 App.onPlanetClick / onLaunchClick / onToolboxPlanetClick 完全一致，
 * card = 卡面文件名（cards.json 的 id）。
 */
const Orbit = {
    // ==================== 可调参数 ====================
    CFG: {
        // 卡尺寸写在 css/cards.css（122×168）
        // 半径/景深全部按原版恢复：扁平比 2:1，近大远小 0.65~1.2
        RX: 600, RY: 300,          // 外层轨道（横向 / 纵向），init 时按视口高度做安全修正
        LRX: 400, LRY: 200,        // 启动卡自己的内侧椭圆轨道
        TRX: 430, TRY: 215,        // 工具箱椭圆半径
        LAUNCH_STAGGER: 45,        // 展开时每张启动卡的错峰延迟（ms）→ 一张张弹出去
        FLIP_DELAY: 160,           // 翻牌到打开面板的间隔（ms）
        SCALE_MIN: 0.65,           // 轨道最远处缩放（原版）
        SCALE_SPAN: 0.55,          // 最近处比最远处大多少（原版 0.65~1.2）
        FOCUS_SCALE: 1.62,         // 父卡摊开子卡时放大到的倍数
        PARENT_DY: -52,            // 摊开时父卡上移多少（子卡 270 高，父卡不下移就顶不出空间）
        KID_SPACING: 224,          // 子卡横向间距（子卡 198 宽、倾斜 7° 后包围盒 230）
        KID_DY0: 232,              // 子卡基准下移距离（父卡底边在 -52+136=84，倾斜后子卡上沿 86）
        KID_DY_SPAN: 18,           // 每远一档再多下移（小窗口也不至于切到最外面那张）
        KID_ROT: 7,                // 子卡倾斜角（度）
        KID_HALF: 155,             // 子卡 198×270 倾斜后包围盒半高（扇形自适应要用，见 _fanSpan）

        // 工具箱面板是固定 1180×800 且 overflow:hidden，可用纵向空间比浏览器视口小得多，
        // 所以子卡要小一号、扇形要更靠上，否则最外侧那几张会被面板切掉。
        TOOL: {
            FOCUS_SCALE: 1.45,
            PARENT_DY: -60,
            KID_SPACING: 190,      // 工具箱子卡 CSS 里缩到 150 宽，间距跟着收
            KID_DY0: 177,
            KID_DY_SPAN: 14,
            KID_ROT: 6,
            KID_HALF: 115          // 150×204 倾斜后包围盒半高
        }
    },

    // ==================== 数据表 ====================
    // self:true 标记"这张卡自己有父级面板"（sensevoice / active / tts / napcat / flux_painter）。
    // 注意：点父卡的统一行为是"摊开 / 收起"，不从这里进面板。
    // 其中 sensevoice、active 的父级面板和子卡面板内容完全一样（只是标题不同，已确认）；
    // tts / napcat / flux_painter 是"总设置"合并表单，各部分在子卡里都有，
    // 只是不能一次保存 —— 需要的话可以用这个标记给它们各生成一张"总设置"子卡。
    launcherPlanets: [
        { id: 'phone', label: '接口', card: 'launcher_phone', tooltip: '启动手机接口服务' },
        { id: 'main', label: '主程序', card: 'launcher_main', tooltip: '启动主程序' },
        { id: 'sovits', label: 'SoVITS', card: 'launcher_sovits', tooltip: '启动 SoVITS 服务' },
        { id: 'sensevoice', label: 'SenseVoice', card: 'launcher_sensevoice', tooltip: '启动 SenseVoice 服务' },
        { id: 'painting', label: '绘画', card: 'launcher_painting', tooltip: '启动内置 ComfyUI 绘画引擎' },
        { id: 'napcat', label: 'NapCat', card: 'launcher_napcat', tooltip: 'NapCat 快速启动' },
        { id: 'netease', label: '网易云', card: 'launcher_netease', tooltip: '启动网易云搜歌服务' },
        { id: 'rvc', label: 'RVC', card: 'launcher_rvc', tooltip: '启动 RVC 翻唱服务' },
        { id: 'desktopet', label: '桌宠', card: 'launcher_desktopet', tooltip: '启动桌宠' }
    ],

    outerPlanets: [
        { id: 'basic', label: '基本', card: 'basic', tooltip: '基础与 app 设置' },
        { id: 'character', label: '角色卡', card: 'character', tooltip: '角色卡配置' },
        {
            id: 'sensevoice', label: 'SenseVoice', card: 'sensevoice', tooltip: '语音识别配置', self: true,
            kids: [
                { id: 'sensevoice_config', label: '识别', card: 'sensevoice_config', tooltip: '语音识别配置' },
                { id: 'sensevoice_mic', label: '闭麦', card: 'sensevoice_mic', tooltip: '闭麦（麦克风开关）' },
                { id: 'sensevoice_audio', label: '音频', card: 'sensevoice_audio', tooltip: '音频采集设置' }
            ]
        },
        {
            id: 'llm', label: 'LLM', card: 'llm', tooltip: '大语言模型配置',
            kids: [
                { id: 'llm_model', label: '模型', card: 'llm_model', tooltip: 'LLM 模型设置' },
                { id: 'llm_prompt', label: '提示词', card: 'llm_prompt', tooltip: 'LLM 提示词设置' },
                { id: 'llm_algorithm', label: '算法', card: 'llm_algorithm', tooltip: 'LLM 算法设置' }
            ]
        },
        {
            id: 'active', label: '主动回复', card: 'active', tooltip: '角色主动回复配置', self: true,
            kids: [
                { id: 'active_config', label: '配置', card: 'active_config', tooltip: '主动回复配置' },
                { id: 'active_browse', label: '浏览', card: 'active_browse', tooltip: 'B站内容浏览' }
            ]
        },
        {
            id: 'catbrain', label: 'CatBrain', card: 'catbrain', tooltip: '角色灵魂配置',
            kids: [
                { id: 'ltmem', label: '长期记忆', card: 'catbrain_ltmem', tooltip: '长期记忆配置' },
                { id: 'abstract', label: '记忆摘要', card: 'catbrain_abstract', tooltip: '记忆摘要配置' },
                { id: 'rulesbreak', label: '原则词', card: 'catbrain_rulesbreak', tooltip: '破甲原则词配置' },
                { id: 'values', label: '价值观', card: 'catbrain_values', tooltip: '价值观配置' },
                { id: 'usermem', label: '用户记忆', card: 'catbrain_usermem', tooltip: '用户记忆配置' }
            ]
        },
        {
            id: 'database', label: '数据库', card: 'database', tooltip: '数据库知识库配置',
            kids: [
                { id: 'db_search', label: '搜索', card: 'db_search', tooltip: '搜索学习配置' },
                { id: 'db_store', label: '知识', card: 'db_store', tooltip: '存储及检索配置' },
                { id: 'db_source', label: '来源', card: 'db_source', tooltip: '网页数据来源配置' },
                { id: 'db_prefill', label: '预填', card: 'db_prefill', tooltip: '一键预填充知识库' }
            ]
        },
        {
            id: 'tts', label: 'TTS', card: 'tts', tooltip: '语音合成与 SoVITS 配置', self: true,
            kids: [
                { id: 'tts_model', label: '模型', card: 'tts_model', tooltip: '语音模型设置' },
                { id: 'tts_params', label: '参数', card: 'tts_params', tooltip: '语音参数设置' },
                { id: 'tts_config', label: '配置', card: 'tts_config', tooltip: '语音合成配置' },
                { id: 'tts_pause', label: '间隔', card: 'tts_pause', tooltip: '合成间隔设置' }
            ]
        },
        { id: 'subtitle', label: '字幕', card: 'subtitle', tooltip: '字幕模块配置' },
        {
            id: 'vts', label: 'VTS', card: 'vts', tooltip: 'VTuber / VTS 配置',
            kids: [
                { id: 'vts_config', label: '配置', card: 'vts_config', tooltip: 'VTS 配置' },
                { id: 'vts_emotion', label: '表情', card: 'vts_emotion', tooltip: 'VTS 表情绑定' },
                { id: 'desktopet', label: '桌宠', card: 'desktopet', tooltip: '桌宠配置' },
                { id: 'vts_params', label: '参数', card: 'vts_params', tooltip: 'VTS 模型参数' }
            ]
        },
        { id: 'toolbox', label: '工具箱', card: 'toolbox', tooltip: '工具箱（Minecraft 等工具）', overlay: true },
        {
            id: 'meowsinger', label: '歌曲', card: 'meowsinger', tooltip: '点歌翻唱与感想配置',
            kids: [
                { id: 'meowsinger_model', label: '模型', card: 'meowsinger_model', tooltip: '歌曲模型设置' },
                { id: 'meowsinger_song', label: '歌曲', card: 'meowsinger_song', tooltip: '点歌设置' },
                { id: 'meowsinger_cover', label: '翻唱', card: 'meowsinger_cover', tooltip: '翻唱设置' },
                { id: 'meowsinger_sentiment', label: '感想', card: 'meowsinger_sentiment', tooltip: '感想设置' }
            ]
        },
        { id: 'calendar', label: '待办', card: 'calendar', tooltip: '待办提醒' }
    ],

    toolboxPlanets: [
        { id: 'minecraft', label: 'Minecraft', card: 'minecraft', tooltip: 'Minecraft 日志读取配置' },
        { id: 'meowvision', label: '视觉', card: 'meowvision', tooltip: 'MeowVision 视觉模块配置' },
        {
            id: 'napcat', label: 'NapCat', card: 'napcat', tooltip: 'NapCat QQ 机器人配置', self: true,
            kids: [
                { id: 'napcat_private', label: '私聊回复', card: 'napcat_private', tooltip: '私聊回复配置' },
                { id: 'napcat_group', label: '群聊回复', card: 'napcat_group', tooltip: '群聊回复与主动插话配置' },
                { id: 'napcat_send', label: '主动发送', card: 'napcat_send', tooltip: '主动发送触发型工具配置' },
                { id: 'napcat_account', label: '角色名', card: 'napcat_account', tooltip: '连接与角色名配置' }
            ]
        },
        { id: 'weather', label: '天气', card: 'weather', tooltip: '天气查询配置' },
        { id: 'news', label: '新闻', card: 'news', tooltip: '新闻查询配置' },
        { id: 'danmaku', label: '弹幕', card: 'danmaku', tooltip: 'B站直播弹幕配置' },
        { id: 'add_backlog', label: '提醒', card: 'add_backlog', tooltip: '新建待办触发工具配置' },
        { id: 'meowsongs', label: '哼唱', card: 'meowsongs', tooltip: '即兴哼唱配置' },
        { id: 'turtle_soup', label: '海龟汤', card: 'turtle_soup', tooltip: '海龟汤触发工具配置' },
        {
            id: 'flux_painter', label: '绘画', card: 'flux_painter', tooltip: 'Flux 绘画（内置 ComfyUI 文生图）配置', self: true,
            kids: [
                { id: 'flux_painter_service', label: '服务', card: 'flux_service', tooltip: '绘画引擎服务与运行环境' },
                { id: 'flux_painter_model', label: '模型', card: 'flux_model', tooltip: '底模与提示词模型配置' },
                { id: 'flux_painter_prompt', label: '提示词', card: 'flux_prompt', tooltip: '提示词固定件与画师配置' },
                { id: 'flux_painter_workflow', label: '工作流', card: 'flux_workflow', tooltip: '采样与画质、Pro 流程配置' }
            ]
        }
    ],

    // ==================== 运行时状态 ====================
    rotation: 0,
    toolboxRotation: 0,
    launcherRotation: 0,
    suppressClick: false,
    launcherOpen: false,
    launchEls: [],
    _deck: {},

    /**
     * 半径以原版几何为准（扁平比 2:1），只在视口太矮时按比例收一点，
     * 免得最上/最下的卡被视口裁掉。形状比例始终不变。
     */
    _fitRadius() {
        const c = this.CFG;
        const CARD_H = 168;                                   // 与 css/cards.css 的 .slot 高度一致
        const half = (window.innerHeight || 900) / 2 - 10;
        c.RY = Math.max(220, Math.min(300, Math.round(half - 0.5 * CARD_H)));
        c.RX = c.RY * 2;                                      // 原版扁平比 2:1
        c.LRY = Math.round(c.RY * 2 / 3);                     // 原版 400 / 200
        c.LRX = c.LRY * 2;
        return c;
    },

    /** 椭圆轨道环的视觉尺寸跟着半径走 */
    _fitRing(ringEl, RX, RY, dw, dh) {
        if (!ringEl) return;
        const w = RX * 2 + dw, h = RY * 2 + dh;
        ringEl.style.width = w + 'px';
        ringEl.style.height = h + 'px';
        ringEl.style.margin = (-h / 2) + 'px 0 0 ' + (-w / 2) + 'px';
    },

    /** 取某个 deck 用的扇形参数（'tool' 用更小一号的那套） */
    _kidCfg(name) {
        if (name === 'tool') return this.CFG.TOOL;
        return {
            FOCUS_SCALE: this.CFG.FOCUS_SCALE, PARENT_DY: this.CFG.PARENT_DY,
            KID_SPACING: this.CFG.KID_SPACING, KID_DY0: this.CFG.KID_DY0,
            KID_DY_SPAN: this.CFG.KID_DY_SPAN, KID_ROT: this.CFG.KID_ROT,
            KID_HALF: this.CFG.KID_HALF
        };
    },

    /**
     * 子卡扇形的"弧差"按可用纵向空间自适应。
     * 子卡很大（198×270），最外侧那张因为倾斜，包围盒半高会涨到 ~155；
     * 空间不够时就把弧压平，否则最外侧两张的底角会被切掉。
     * 主界面按浏览器视口算，工具箱按面板的固定可见半高算。
     */
    _fanSpan(name) {
        const kc = this._kidCfg(name);
        const half = (name === 'tool') ? 330 : (window.innerHeight || 900) / 2;
        const room = half - 8 - kc.KID_HALF - kc.KID_DY0;
        return Math.max(0, Math.min(kc.KID_DY_SPAN, Math.floor(room / 2)));
    },

    init() {
        const orbitOuter = document.getElementById('orbitOuter');
        const cluster = document.getElementById('launcherCluster');
        const system = document.getElementById('orbitSystem');
        if (!orbitOuter || !cluster || !system) {
            console.error('[Orbit] 缺少 #orbitOuter / #launcherCluster / #orbitSystem');
            return;
        }

        this._fitRadius();
        this._fitRing(document.querySelector('#orbitOuter .ring-outer'), this.CFG.RX, this.CFG.RY, 20, 10);
        this._fitRing(document.querySelector('#toolboxOrbit .toolbox-ring'), this.CFG.TRX, this.CFG.TRY, 20, 10);

        // ---------- 子卡容器 ----------
        const kidsBox = document.createElement('div');
        kidsBox.className = 'children';
        system.appendChild(kidsBox);

        // ---------- 外层配置卡 ----------
        const outerEls = this.outerPlanets.map((p, i) => {
            const el = this._buildCard(p, this.outerPlanets.length, i, null, null, true);
            this._place(el, el._ang, 0, this.CFG.RX, this.CFG.RY);
            el.addEventListener('click', (e) => this._onCardClick(e, 'outer', el, p));
            orbitOuter.appendChild(el);
            return el;
        });
        this.outerEls = outerEls;
        this._initDeck('outer', kidsBox, outerEls, [this.CFG.RX, this.CFG.RY], () => this.rotation,
                       (node, src) => this._toPanel(node.id, src, window.App && App.onPlanetClick), system);

        // ---------- 启动卡 ----------
        const lTotal = this.launcherPlanets.length;
        this.launchEls = this.launcherPlanets.map((p, i) => {
            const el = this._buildCard(p, lTotal, i, null, 'slot-launch', true);
            el._lang = (2 * Math.PI / lTotal) * i - Math.PI / 2;   // 启动轨道的均匀分布角
            this._applyLaunch(el, i, lTotal, false);
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                if (this.suppressClick) return;
                this.closeAll();   // 启动卡与"摊开子卡"互斥
                this._flipThen(el, () => this._toPanel(p.id, el, window.App && App.onLaunchClick));
            });
            cluster.appendChild(el);
            return el;
        });

        // ---------- 中心球：展开/收起启动卡，并收起子卡 ----------
        const center = document.getElementById('centerLauncher');
        center.addEventListener('click', (e) => {
            e.stopPropagation();
            this.closeAll();
            this.toggleLauncher();
        });

        // ---------- 点空白：收起 ----------
        system.addEventListener('click', (e) => {
            const t = e.target;
            if (t && t.closest && (t.closest('.slot') || t.closest('.sub'))) return;
            this.closeAll();
        });

        this.bindDragRotation();
        this.initToolboxSub();
        this._routeDeckClick(document.getElementById('orbitSystem'), 'outer');
        this._setAnim(true);   // 默认允许轨道旋转动画
        this._startFxLoop();   // 主界面卡片的呼吸 + 随机涟漪

        console.log('[Orbit] ' + this.outerPlanets.length + ' 外环卡 / ' +
                    this.launchEls.length + ' 启动卡 / ' + this.toolboxPlanets.length + ' 工具箱卡');
    },

    // ==================== 建卡 / 定位 ====================
    /**
     * 一张卡 = .slot > [.card-glow + .card-ripple] + .card > (.face.front 卡面 + .face.back 卡背)
     * 点击时 .card 加 .flipped 做 3D 翻牌，翻完再摊开子卡 / 打开配置。
     * fx=true 时插入呼吸/涟漪两层（只有主界面卡片要）
     */
    _buildCard(node, total, index, cardId, extraClass, fx) {
        const id = cardId || node.card || node.id;
        const th = Cards.theme(id);
        const label = I18n.text(Cards.name(id, node.label));
        const desc = I18n.text(node.tooltip || node.label);
        const el = document.createElement('div');
        el.className = 'slot' + (extraClass ? ' ' + extraClass : '');
        el.dataset.id = node.id;
        el.dataset.card = id;
        el.dataset.tooltip = desc;
        el._ang = (2 * Math.PI / total) * index - Math.PI / 2;
        el._node = node;   // 反向引用：捕获阶段仲裁后要用它走 _onCardClick
        // 启动卡加角标：和同名的配置卡区分开（绘画/NapCat/SenseVoice/桌宠）
        const badge = node.badge || (id.indexOf('launcher_') === 0 ? '启动' : '');
        el.innerHTML =
            (fx ? '<span class="card-glow"></span><span class="card-ripple"></span>' : '') +
            '<div class="card" style="--a:' + th.a + ';--b:' + th.b + '">' +
                '<div class="face front">' +
                    (badge ? '<span class="card-badge">' + badge + '</span>' : '') +
                    '<div class="card-art">' +
                        '<img class="card-img" alt="" draggable="false" src="' + Cards.img(id) + '">' +
                        '<span class="card-emoji">' + Cards.emoji(id) + '</span>' +
                    '</div>' +
                    '<div class="card-name">' + label + '</div>' +
                '</div>' +
                '<div class="face back">' +
                    '<span class="bn">' + label + '</span>' +
                    '<span class="bd">' + desc + '</span>' +
                '</div>' +
            '</div>';
        if (fx) {
            // 每张卡自己的呼吸周期与相位：故意全不一样，才不是"整体一起闪"
            el.style.setProperty('--bd', (4.2 + Math.random() * 3.4).toFixed(2) + 's');
            el.style.setProperty('--bdel', (-Math.random() * 7.6).toFixed(2) + 's');
        }
        const img = el.querySelector('.card-img');        img.addEventListener('error', () => {
            const art = img.parentNode;
            if (art) art.classList.add('no-img');
            img.remove();
        }, { once: true });
        return el;
    },

    /**
     * 主界面卡片：不定期随机挑一张放涟漪。
     * 间隔 0.8~3.6s 随机、目标随机、且不连着同一张 —— 刻意不同步。
     * 只从主界面卡片池里挑（外环 13 张；启动轨道展开时把 9 张也算进来）。
     */
    _startFxLoop() {
        const pool = () => {
            const out = (this.outerEls || []).filter(el => !el.classList.contains('dim'));
            if (this.launcherOpen) {
                (this.launchEls || []).forEach(el => {
                    if (el.style.display !== 'none' && el.style.opacity === '1') out.push(el);
                });
            }
            return out;
        };
        const tick = () => {
            this._fxTimer = setTimeout(() => {
                try {
                    // 面板打开时整层在做模糊，再放动画会逼浏览器每帧重算模糊 → 直接停掉
                    if (document.body.classList.contains('modal-open')) { tick(); return; }
                    const list = pool();
                    if (list.length) {
                        let el = list[Math.floor(Math.random() * list.length)];
                        if (el === this._fxLast && list.length > 1) {
                            el = list[(list.indexOf(el) + 1 + Math.floor(Math.random() * (list.length - 1))) % list.length];
                        }
                        this._fxLast = el;
                        const r = el.querySelector('.card-ripple');
                        if (r) {
                            r.classList.remove('go');
                            void r.offsetWidth;      // 强制重排，同一个元素也能重放动画
                            r.classList.add('go');
                        }
                    }
                } catch (e) { /* 动画出错不影响交互 */ }
                tick();
            }, 800 + Math.random() * 2800);
        };
        tick();
    },

    /**
     * 翻牌 → 翻完再执行动作（子卡与父卡共用）
     *
     * ⚠️ 这里必须用「全局唯一」的待执行动作：
     * 之前是每张卡各存一个 timer，连点两张卡时两个 timer 都会到点，
     * 于是先弹出「上一张卡」的面板 → 看起来就是"点这张出别的界面"。
     * 现在任何一次新点击都会作废上一个还没执行的动作。
     */
    _flipThen(el, cb) {
        this._cancelPending();
        const card = el.querySelector ? el.querySelector('.card') : null;
        if (!card) { cb(); return; }
        if (card.classList.contains('flipped')) { cb(); return; }
        card.classList.add('flipped');
        this._pendingEl = el;
        this._pendingTimer = setTimeout(() => {
            this._pendingTimer = null;
            this._pendingEl = null;
            cb();
        }, this.CFG.FLIP_DELAY);
    },

    /** 作废还没执行的动作（点空白/点主球/关面板时调用，避免"人都走开了面板才弹出来"） */
    _cancelPending() {
        if (this._pendingTimer) {
            clearTimeout(this._pendingTimer);
            this._pendingTimer = null;
        }
        if (this._pendingEl) {
            this._unflip(this._pendingEl);
            this._pendingEl = null;
        }
    },

    /** 给"打开的不是 Modal"的入口用：翻回那张打开浮层的卡（toolbox 节点带 overlay:true） */
    unflipOverlayCard() {
        this._unflip(this._overlayCard);
    },

    /** 把卡片翻回正面 */
    _unflip(el) {
        if (!el || !el.querySelector) return;
        const card = el.querySelector('.card');
        if (card) card.classList.remove('flipped');
    },

    /** 椭圆轨道定位 + 景深缩放（uniform scale，不会把卡拉斜） */
    _place(el, baseAngle, rotDeg, RX, RY) {
        const a = baseAngle + rotDeg * Math.PI / 180;
        const depth = Math.cos(a);
        const sc = this.CFG.SCALE_MIN + (depth + 1) / 2 * this.CFG.SCALE_SPAN;
        el.style.transform = 'translate3d(' + (RX * Math.sin(a)).toFixed(1) + 'px, ' +
                             (RY * Math.cos(a)).toFixed(1) + 'px, 0) scale(' + sc.toFixed(3) + ')';
        el.style.zIndex = String(Math.round((depth + 1) * 50 + 5));
        el.style.setProperty('--inv', (1 / sc).toFixed(3));
    },

    /** 启动卡：自己的一圈椭圆轨道（和外壳同款景深），展开时从主球中心弹出去 */
    _applyLaunch(el, index, total, open) {
        if (!open) {
            el.style.transform = 'translate3d(0px, 0px, 0px) scale(0.15)';
            el.style.opacity = '0';
            el.style.pointerEvents = 'none';
            // 收完直接从渲染树里摘掉：9 张看不见的卡没必要一直堆在球心，
            // 也彻底排除"看不见却截获点击"的可能
            clearTimeout(el._hideTimer);
            el._hideTimer = setTimeout(() => {
                if (!this.launcherOpen) el.style.display = 'none';
            }, 560);
            return;
        }
        clearTimeout(el._hideTimer);
        const wasHidden = el.style.display === 'none';
        el.style.display = '';
        if (wasHidden) void el.offsetWidth;   // 先让"贴在球心"的起始态落地，过渡才会跑
        const a = el._lang + this.launcherRotation * Math.PI / 180;
        const depth = Math.cos(a);
        const sc = this.CFG.SCALE_MIN + (depth + 1) / 2 * this.CFG.SCALE_SPAN;
        el.style.transform = 'translate3d(' + (this.CFG.LRX * Math.sin(a)).toFixed(1) + 'px, ' +
                             (this.CFG.LRY * Math.cos(a)).toFixed(1) + 'px, 0) scale(' + sc.toFixed(3) + ')';
        el.style.zIndex = String(Math.round((depth + 1) * 50 + 5));
        el.style.setProperty('--inv', (1 / sc).toFixed(3));
        el.style.opacity = '1';
        el.style.pointerEvents = 'auto';
    },

    /** 轨道转动时重排启动卡 */
    _syncLauncher() {
        if (!this.launcherOpen) return;
        const total = this.launchEls.length;
        this.launchEls.forEach((el, i) => this._applyLaunch(el, i, total, true));
    },

    toggleLauncher() {
        this.launcherOpen = !this.launcherOpen;
        const open = this.launcherOpen;
        const center = document.getElementById('centerLauncher');
        if (center) center.classList.toggle('active', open);
        const total = this.launchEls.length;
        this.launchEls.forEach((el, i) => {
            clearTimeout(el._launchTimer);
            if (open) {
                // 错峰飞出：一张一张从主球位置弹到轨道位，像发牌
                el._launchTimer = setTimeout(() => {
                    if (this.launcherOpen) this._applyLaunch(el, i, total, true);
                }, i * this.CFG.LAUNCH_STAGGER);
            } else {
                this._applyLaunch(el, i, total, false);
                this._unflip(el);
            }
        });
        const system = document.getElementById('orbitSystem');
        if (system) system.classList.toggle('launcher-open', open);
        // 启动轨道展开时把外环压暗：两圈椭圆在上下方向会挨得很近，压暗就不会糊在一起
        this._syncDim();
    },

    /**
     * 统一计算谁该变暗（唯一入口，避免各处分头 add/remove 打架）：
     * - 摊开子卡时：除父卡外全暗
     * - 展开启动卡时：外环卡全暗
     */
    _syncDim() {
        const sets = { outer: this._deck.outer, tool: this._deck.tool };
        for (const key in sets) {
            const d = sets[key];
            if (!d) continue;
            d.els.forEach(el => {
                const isParent = d.open && d.parent === el;
                const dimByKids = d.open && !isParent;
                const dimByLauncher = (key === 'outer') && this.launcherOpen && !d.open;
                el.classList.toggle('dim', !!(dimByKids || dimByLauncher));
            });
        }
    },

    // ==================== 子卡扇形摊开 ====================
    _initDeck(name, boxEl, els, radius, rotGetter, openPanel, sysEl) {
        this._deck[name] = {
            box: boxEl, els: els, sysEl: sysEl || null, subs: [], parent: null, open: false,
            radius: radius, rot: rotGetter, openPanel: openPanel,
            timer: null, gcTimer: null,
            restore: (el) => this._place(el, el._ang, rotGetter(), radius[0], radius[1])
        };
    },

    /**
     * 摊开状态下按"几何就近"仲裁点击（捕获阶段，先于子卡自己的 handler）。
     *
     * 为什么需要：子卡扇形很宽（5 张时最外侧在 ±448），而外环卡片的轨道位置
     * 也在同一带（例如 catbrain 在 (450,199)、最外侧子卡在 (448,238)），必然重叠。
     * 子卡层必须在 .orbit-outer 之上（后者是 1500×1500 的拖拽容器，压下去会把子卡全挡死），
     * 于是"点父卡却弹出子卡面板"。
     *
     * 仲裁规则：比较点击点到「那张变暗父卡的中心」与「被打中的子卡中心」的距离，
     * 谁近听谁的 —— 两张卡在各自中心附近都点得到，重叠区按直觉归属。
     */
    _routeDeckClick(system, name) {
        system.addEventListener('click', (e) => {
            const d = this._deck[name];
            if (!d || !d.open) return;
            const t = e.target;
            if (!t || !t.closest) return;
            const sub = t.closest('.sub');
            const card = this._nearestSiblingCard(name, e.clientX, e.clientY);

            if (sub) {
                if (!card) return;                                  // 没压到别的父卡 → 子卡自己处理
                const sr = sub.getBoundingClientRect();
                const ds = Math.hypot(e.clientX - (sr.left + sr.width / 2),
                                      e.clientY - (sr.top + sr.height / 2));
                if (card.dist >= ds) return;                        // 子卡更近 → 子卡自己处理
                e.stopPropagation();                                // 否则判成"点那张暗父卡"
                this._onCardClick(e, name, card.el, card.el._node);
                return;
            }
            // 点到的既不是子卡也不是卡片（点了空白）：
            // 如果这个位置其实落在某张暗父卡身上，就切换焦点，而不是收起
            if (t.closest('.slot') || !card) return;
            e.stopPropagation();
            this._onCardClick(e, name, card.el, card.el._node);
        }, true);
    },

    /** 找离 (x,y) 最近、且包含该点的"非父卡"卡片（暗卡），没有则 null */
    _nearestSiblingCard(name, x, y) {
        const d = this._deck[name];
        if (!d || !d.els) return null;
        let best = null, bestD = Infinity;
        d.els.forEach(el => {
            if (el === d.parent) return;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return;
            if (x < r.left || x > r.right || y < r.top || y > r.bottom) return;
            const dd = Math.hypot(x - (r.left + r.width / 2), y - (r.top + r.height / 2));
            if (dd < bestD) { bestD = dd; best = el; }
        });
        return best ? { el: best, dist: bestD } : null;
    },

    /** 卡片点击总入口（父卡与子卡共用 deck.openPanel 分发） */
    _onCardClick(e, name, el, node) {
        e.stopPropagation();
        if (this.suppressClick) return;
        const d = this._deck[name];
        if (!d) return;

        // 再点已摊开的父卡：统一收起（和 llm 行为一致）。
        // 以前对 self:true 的卡会打开它自己的父级面板，但"摊开后点头顶那张卡"
        // 的直觉是"收起/关掉"，弹出设置面板很反直觉（sensevoice/active/tts/napcat/flux_painter 都中招）。
        if (d.open && d.parent === el) {
            this._collapse(name);
            return;
        }
        if (d.open) this._collapse(name);
        // 展开启动卡时点外环卡：先把启动卡收起来（外环卡此时是暗的，正常点不到，保险）
        if (name === 'outer' && this.launcherOpen) this.toggleLauncher();

        if (node.kids && node.kids.length) {
            this._flipThen(el, () => this._spread(name, el, node));   // 先翻牌，翻完再摊开
            return;
        }
        if (node.overlay) this._overlayCard = el;                     // 打开浮层的卡，关浮层时翻回
        this._flipThen(el, () => d.openPanel(node, el));
    },

    _spread(name, parentEl, node) {
        const d = this._deck[name];
        if (!d) return;
        this._collapse(name);

        d.parent = parentEl;
        d.open = true;
        parentEl.classList.add('focus');
        if (d.sysEl) d.sysEl.classList.add('focusing');   // 把轨道层提到主球之上（见 orbit.css）
        const kc = this._kidCfg(name);
        parentEl.style.zIndex = '900';
        parentEl.style.transform = 'translate3d(0px, ' + kc.PARENT_DY + 'px, 0) scale(' +
                                    kc.FOCUS_SCALE + ')';
        parentEl.style.setProperty('--inv', (1 / kc.FOCUS_SCALE).toFixed(3));
        this._syncDim();

        const kids = node.kids;
        const total = kids.length;
        const mid = (total - 1) / 2;
        d.box.innerHTML = '';
        d.subs = kids.map((k, i) => {
            const el = this._buildCard({ id: k.id, label: k.label, tooltip: k.tooltip }, total, i, k.card);
            el.className = 'sub';
            const off = i - mid;
            el.dataset.dx = (off * kc.KID_SPACING).toFixed(1);
            el.dataset.dy = (kc.KID_DY0 + Math.abs(off) * this._fanSpan(name)).toFixed(1);
            el.dataset.rot = (off * kc.KID_ROT).toFixed(1);
            el.style.transform = 'translate3d(0px, 0px, 0) scale(0.25)';
            el.addEventListener('click', (ev) => {
                ev.stopPropagation();
                if (this.suppressClick) return;
                this._flipThen(el, () => d.openPanel(k, el));   // 子卡同样翻牌后再开面板
            });
            d.box.appendChild(el);
            return el;
        });

        // 先落回父卡中心，下一帧再摊开 → 视觉上是"从这张卡长出来的"
        d.timer = setTimeout(() => {
            if (!d.open) return;
            d.box.classList.add('open');
            d.subs.forEach(el => {
                el.style.transform = 'translate3d(' + el.dataset.dx + 'px, ' + el.dataset.dy +
                                      'px, 0) rotate(' + el.dataset.rot + 'deg) scale(1)';
            });
        }, 80);
    },

    _collapse(name) {
        const d = this._deck[name];
        if (!d || !d.open) return;
        d.open = false;
        clearTimeout(d.timer);
        d.box.classList.remove('open');
        if (d.sysEl) d.sysEl.classList.remove('focusing');

        if (d.parent) {
            d.parent.classList.remove('focus');
            d.parent.style.removeProperty('--inv');
            this._setAnim(true);
            d.restore(d.parent);
            // 父卡先滑回轨道位再翻回正面，两个动画不打架
            const p = d.parent;
            setTimeout(() => { if (!d.open) this._unflip(p); }, 280);
        }
        d.subs.forEach(el => {
            this._unflip(el);
            el.style.transform = 'translate3d(0px, 0px, 0) scale(0.25)';
        });
        this._syncDim();

        const box = d.box;
        clearTimeout(d.gcTimer);
        d.gcTimer = setTimeout(() => { if (!d.open) box.innerHTML = ''; }, 700);

        d.subs = [];
        d.parent = null;
    },

    closeAll() {
        this._cancelPending();   // 人已经点开了，别再补一个面板出来
        Object.keys(this._deck).forEach(k => this._collapse(k));
    },

    /** 打开配置面板：把来源卡交给 Modal，让面板从卡片位置放大 */
    _toPanel(id, srcEl, fn) {
        if (typeof Modal !== 'undefined') Modal.source = srcEl || null;
        if (typeof fn === 'function') fn.call(window.App, id, srcEl);
    },

    _setAnim(on) {
        Object.keys(this._deck).forEach(k => {
            (this._deck[k].els || []).forEach(el => el.classList.toggle('anim', !!on));
        });
    },

    // ==================== 拖动 + 惯性 ====================
    _bindDrag(container, deckName, getRot, setRot) {
        if (!container) return;
        let dragging = false;
        let lastX = 0;
        let velocity = 0;
        let rafId = null;

        const apply = () => {
            // 启动轨道展开时，拖空白转的是启动轨道（外环此时是暗的，转了也看不见）
            if (deckName === 'outer' && this.launcherOpen) { this._syncLauncher(); return; }
            const d = this._deck[deckName];
            if (!d) return;
            d.els.forEach(el => this._place(el, el._ang, getRot(), d.radius[0], d.radius[1]));
        };

        const inertia = () => {
            setRot(getRot() + velocity);
            velocity *= 0.92;          // 惯性衰减
            apply();
            if (Math.abs(velocity) < 0.05) {
                rafId = null;
                this._setAnim(true);
                return;
            }
            rafId = requestAnimationFrame(inertia);
        };

        const onMove = (e) => {
            if (!dragging) return;
            const dx = e.clientX - lastX;
            velocity = dx * 0.35;
            lastX = e.clientX;
            setRot(getRot() + dx * 0.3);
            apply();
            if (Math.abs(dx) > 5) this.suppressClick = true;
        };

        const onUp = () => {
            dragging = false;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            setTimeout(() => { this.suppressClick = false; }, 50);
            if (rafId !== null) cancelAnimationFrame(rafId);
            if (Math.abs(velocity) > 0.05) rafId = requestAnimationFrame(inertia);
            else { rafId = null; this._setAnim(true); }
        };

        container.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            if (this._deck[deckName] && this._deck[deckName].open) return;   // 摊开子卡时不转轨道
            dragging = true;
            lastX = e.clientX;
            velocity = 0;
            this.suppressClick = false;
            this._setAnim(false);
            if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
            e.preventDefault();
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    },

    bindDragRotation() {
        // 绑在整个轨道容器上（而不是只绑 .orbit-outer）：
        // 启动卡在 #launcherCluster 里、属于 .orbit-outer 的兄弟节点，
        // 只绑 .orbit-outer 的话 mousedown 落在启动卡上不会触发，转不动。
        // 启动轨道展开时转启动轨道，否则转外环配置轨道。
        this._bindDrag(document.getElementById('orbitSystem'), 'outer',
                       () => (this.launcherOpen ? this.launcherRotation : this.rotation),
                       (v) => { if (this.launcherOpen) this.launcherRotation = v; else this.rotation = v; });
    },

    initToolboxSub() {
        const orbit = document.getElementById('toolboxOrbit');
        const system = document.getElementById('toolboxSystem');
        if (!orbit || !system) return;

        const kidsBox = document.createElement('div');
        kidsBox.className = 'children';
        system.appendChild(kidsBox);

        const els = this.toolboxPlanets.map((p, i) => {
            const el = this._buildCard(p, this.toolboxPlanets.length, i);
            this._place(el, el._ang, 0, this.CFG.TRX, this.CFG.TRY);
            el.addEventListener('click', (e) => this._onCardClick(e, 'tool', el, p));
            orbit.appendChild(el);
            return el;
        });
        this._initDeck('tool', kidsBox, els, [this.CFG.TRX, this.CFG.TRY], () => this.toolboxRotation,
                       (node, src) => this._toPanel(node.id, src, window.App && App.onToolboxPlanetClick), system);
        this._routeDeckClick(system, 'tool');   // 工具箱同样按几何仲裁"点父卡还是点子卡"

        const center = document.getElementById('toolboxCenter');
        if (center) {
            center.addEventListener('mousedown', (e) => e.stopPropagation());
            center.addEventListener('click', (e) => {
                if (e && e.stopPropagation) e.stopPropagation();
                this._collapse('tool');
                this._toPanel('center', center, window.App && App.onToolboxPlanetClick);
            });
        }

        // 点工具箱空白 → 收起摊开的子卡（和外层"点空白收起"一致）
        system.addEventListener('click', (e) => {
            const t = e.target;
            if (t && t.closest && (t.closest('.slot') || t.closest('.sub'))) return;
            this._collapse('tool');
        });

        this._bindDrag(system, 'tool',
                       () => this.toolboxRotation, (v) => { this.toolboxRotation = v; });
    }
};
