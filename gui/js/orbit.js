/**
 * Orbit 系统（卡片版）
 *
 * - 中心启动球 / 工具箱父级模型球：保留球形态
 * - 外层配置卡 13 / 启动卡 9 / 工具箱卡 10：卡面 = resource/cat_photos_alpha/{id}.webp（抠像透明版）
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
    ...OrbitData,

    // ==================== 运行时状态 ====================
    rotation: 0,
    toolboxRotation: 0,
    launcherRotation: 0,
    suppressClick: false,
    launcherOpen: false,
    launchEls: [],
    _deck: {},

    // 旋转几何（半径常量 R + 压扁系数 FLAT）全部在 js/orbit/rotation.js：
    //   _applyGeometry / _lockRadius / _orbitPoint / _depthScale / _placeAt
    //   _place / _fitRing / _applyRingLines / _applyLaunch / _syncLauncher
    // 本文件不再保留第二份实现，避免"两个半径"这种老坑。
    // （_applyZoom 已删除：它按视口给容器写 scale，是"半径会缩放"的唯一来源。）

    /**
     * 取某个 deck 用的扇形参数（'tool' 用更小一号的那套）。
     * 主轨道直接用 CFG 顶层，不再逐字段拷一份 —— 拷贝会让"改了 data.js 忘了同步拷贝"
     * 变成第二份真值，调参时永远有一个坑在等着。
     */
    _kidCfg(name) {
        return name === 'tool' ? this.CFG.TOOL : this.CFG;
    },

    /**
     * 子卡扇形排布：所有子卡落在【同一段圆弧】上，倾角 = 它在弧上的极角。
     *   弦长 = KID_SPACING，圆心角 = KID_ROT  →  弧半径 Rf = KID_SPACING / (2·sin(KID_ROT/2))
     *   dx = Rf·sin(θ)      dy = base + Rf·(1 − cos θ)      rot = θ      θ = off·KID_ROT
     *
     * 位置和倾角是同一条几何推出来的：缝隙处处相等，弧也永远"圆"。
     * 旧实现是两套账 —— 位置用「KID_DY0 + |off|×固定弧差」，倾角用 off×KID_ROT：
     *   弧的曲率由 18px/档决定，倾角由 7°/档决定，两者不成比例，偏差随 |off| 变大
     *   （两档时约偏 18px），越往两侧越不对。
     *   而且父卡底边和扇形上沿没对齐：中间那张压进父卡下沿约 3px，最外侧反而低 13px。
     *   它为了适配小窗口还会压"弧差"，一压弧和倾角就更对不上。
     * 现在：基准下移由父卡尺寸 + KID_GAP 算出来，纵向放不下时【整块上移】（lift），
     * 弧的形状一点不变。
     *
     * parentHalf / kidW / kidH 由调用方量真实尺寸传进来：父卡用 offsetHeight（布局值，
     * 不受 transform 影响，读不到过渡中间态），子卡用 offsetWidth/Height（工具箱那套更小）。
     */
    _fanLayout(name, total, parentHalf, kidW, kidH) {
        const kc = this._kidCfg(name);
        const rotDeg = kc.KID_ROT || 0;
        const step = rotDeg * Math.PI / 180;
        // 角度为 0 时退化成"一条横排"，不会 NaN
        const Rf = step > 1e-4 ? (kc.KID_SPACING / (2 * Math.sin(step / 2))) : 0;
        const mid = (total - 1) / 2;
        const base = kc.PARENT_DY + parentHalf + (kc.KID_GAP || 0) + kidH / 2;
        const thMax = Math.abs(mid) * step;
        // 最外侧那张倾斜后的包围盒下沿
        const bottom = base + Rf * (1 - Math.cos(thMax)) +
                       (kidH / 2) * Math.cos(thMax) + (kidW / 2) * Math.sin(thMax);
        // 可用纵向空间：主界面按视口，工具箱按面板固定可见半高（.toolbox-system 690 的一半）
        const half = (name === 'tool') ? 345 : (window.innerHeight || 900) / 2;
        const margin = 10;
        // 上移上限：父卡上沿顶到边界为止（再往上就切父卡了，宁可让扇形出界一点）
        const maxLift = Math.max(0, kc.PARENT_DY - parentHalf + half - margin);
        const lift = Math.min(Math.max(0, bottom - (half - margin)), maxLift);
        const items = [];
        for (let i = 0; i < total; i++) {
            const off = i - mid;
            const th = off * step;
            items.push({
                dx: Rf * Math.sin(th),
                dy: base + Rf * (1 - Math.cos(th)) - lift,
                rot: off * rotDeg
            });
        }
        return { items: items, parentDy: kc.PARENT_DY - lift };
    },

    init() {
        const orbitOuter = document.getElementById('orbitOuter');
        const cluster = document.getElementById('launcherCluster');
        const system = document.getElementById('orbitSystem');
        if (!orbitOuter || !cluster || !system) {
            console.error('[Orbit] 缺少 #orbitOuter / #launcherCluster / #orbitSystem');
            return;
        }

        // 几何只在这里展开一次：R / FLAT 是常量，运行时不再重算（详见 orbit/rotation.js）
        this._applyGeometry();
        this._applyRingLines();  // 两条轨道环线的视觉尺寸
        this._lockRadius();      // ★ 半径锁：任何写 transform 缩放轨道的路径当场被拆掉
        this._applyCenterZ();    // 中心球的层级（和卡片按深度交错，见 rotation.js _depthZ）
        // 窗口尺寸变化只影响"容器缩放"，半径与卡片尺寸不受影响
        // resize 只重摆卡片，不再缩放容器（半径是常量）
        window.addEventListener('resize', () => { this._syncRing(); });
        // 兜底重摆：万一有没排查到的路径把卡片 transform 弄没了（表现为一堆卡堆在容器正中），
        // 松手后立刻按 GEO 恢复。幂等，正常路径下写的是同一批坐标。
        document.addEventListener('mouseup', () => setTimeout(() => this._syncRing(), 0));
        window.__orbitDiag = () => this._diag();   // 控制台诊断入口：__orbitDiag()
        window.__orbitRadiusAudit = () => this.radiusAudit();   // 半径审计：看谁在缩放
        this._startRingWatchdog();   // 每 3 秒自检：卡片被任何路径弄丢位置就自动摆回来

        // ---------- 子卡容器 ----------
        const kidsBox = document.createElement('div');
        kidsBox.className = 'children';
        system.appendChild(kidsBox);

        // ---------- 外层配置卡 ----------
        // 最后一参 = opaque：false → 用抠像透明版；true → 用不透明 jpg
        const outerEls = this.outerPlanets.map((p, i) => {
            const el = this._buildCard(p, this.outerPlanets.length, i, null, null, true, false);
            this._place(el, el._ang, 0, this.GEO.R, this.GEO.RY);
            el.addEventListener('click', (e) => this._onCardClick(e, 'outer', el, p));
            orbitOuter.appendChild(el);
            return el;
        });
        this.outerEls = outerEls;
        this._initDeck('outer', kidsBox, outerEls, [this.GEO.R, this.GEO.RY], () => this.rotation,
                       (node, src) => this._toPanel(node.id, src, window.App && App.onPlanetClick), system);

        // ---------- 启动卡 ----------
        const lTotal = this.launcherPlanets.length;
        this.launchEls = this.launcherPlanets.map((p, i) => {
            const el = this._buildCard(p, lTotal, i, null, 'slot-launch', true, true);
            el._lang = (2 * Math.PI / lTotal) * i - Math.PI / 2;   // 启动轨道的均匀分布角
            this._applyLaunch(el, i, lTotal, false);
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                if (this.suppressClick) return;
                this.closeAll();   // 启动卡与"摊开子卡"互斥
                this._flipThen(el, () => {
                    // 启动卡不开配置面板，所以不能走 _toPanel：那条路会把 Modal.source
                    // 指到这张卡上，之后随便哪个面板都会"从启动卡长出来"。
                    // 翻转只作"已收到点击"的反馈，请求回来就翻回正面（失败/成功都一样）。
                    const done = (window.App && App.onLaunchClick) ? App.onLaunchClick(p.id, el) : null;
                    if (done && typeof done.then === 'function') done.then(() => this._unflip(el));
                    else this._unflip(el);
                });
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
        this._setAnim(true);   // 默认允许轨道旋转动画
        this._startFxLoop();   // 主界面卡片的呼吸 + 随机涟漪
        this._startSnapLoop(); // 吸附：任何来源的转动停下后归位到最近的卡

        console.log('[Orbit] GEO = ' + JSON.stringify(this.GEO));
        console.log('[Orbit] ' + this.outerPlanets.length + ' 外环卡 / ' +
                    this.launchEls.length + ' 启动卡 / ' + this.toolboxPlanets.length + ' 工具箱卡');
    },

    // ==================== 建卡 / 定位 ====================
    /**
     * 一张卡 = .slot > [.card-glow + .card-ripple + .card-ring-focus] + .card > .card-press > (.face.front + .face.back)
     * 点击时 .card 加 .flipped 做 3D 翻牌，翻完再摊开子卡 / 打开配置。
     * .card-press 是压感层（下沉 + 微倾斜，见 css/cards.css / js/press.js）：
     * 翻牌和压感各占一层 transform，互不抢过渡时序。
     * fx=true 时插入呼吸/涟漪两层（只有主界面卡片要）
     * opaque=true → 用不透明 jpg（启动卡 / 工具箱卡 / 插件卡不抠像），false → 抠像透明版
     */
    _buildCard(node, total, index, cardId, extraClass, fx, opaque) {
        const id = cardId || node.card || node.id;
        const th = Cards.theme(id);
        const label = I18n.text(Cards.name(id, node.label));
        let desc = I18n.text(node.tooltip || node.label);
        // 有"自己的总设置"（self）的父卡：提示可以长按打开（deck.js 的 _bindSelfPanel）
        if (node.self) desc += ' · ' + I18n.text('长按打开总设置');
        const el = document.createElement('div');
        el.className = 'slot' + (extraClass ? ' ' + extraClass : '');
        el.dataset.id = node.id;
        el.dataset.card = id;
        el.dataset.tooltip = desc;
        el._ang = (2 * Math.PI / total) * index - Math.PI / 2;
        el._node = node;   // 反向引用：捕获阶段仲裁后要用它走 _onCardClick
        // 启动卡加角标：和同名的配置卡区分开（绘画/NapCat/SenseVoice/桌宠）
        const badge = node.badge || (id.indexOf('launcher_') === 0 ? I18n.text('启动') : '');
        el.innerHTML =
            (fx ? '<span class="card-glow"></span><span class="card-ripple"></span>' : '') +
            '<span class="card-ring-focus"></span>' +
            '<div class="card" style="--a:' + th.a + ';--b:' + th.b + '">' +
                '<div class="card-press">' +
                    '<div class="face front">' +
                        (badge ? '<span class="card-badge">' + badge + '</span>' : '') +
                        '<div class="card-art">' +
                            '<img class="card-img" alt="" draggable="false" decoding="async" src="' + Cards.img(id, opaque) + '">' +
                            '<span class="card-emoji">' + Cards.emoji(id) + '</span>' +
                        '</div>' +
                        '<div class="card-name">' + label + '</div>' +
                        '<span class="card-glare"></span>' +
                        '<span class="card-spot"></span>' +
                        '<span class="card-ring"></span>' +
                    '</div>' +
                    '<div class="face back">' +
                        '<span class="bn">' + label + '</span>' +
                        '<span class="bd">' + desc + '</span>' +
                    '</div>' +
                '</div>' +
            '</div>';
        if (fx) {
            // 每张卡自己的呼吸周期与相位：故意全不一样，才不是"整体一起闪"
            el.style.setProperty('--bd', (4.2 + Math.random() * 3.4).toFixed(2) + 's');
            el.style.setProperty('--bdel', (-Math.random() * 7.6).toFixed(2) + 's');
        }
        const img = el.querySelector('.card-img');
        img.addEventListener('error', () => {
            // 递进回退：alpha.webp → jpg → png → 都没有才退成 emoji
            const next = Cards.nextImg(id, img.getAttribute('src'));
            if (next) {
                img.setAttribute('src', next);
                return;
            }
            const art = img.parentNode;
            if (art) art.classList.add('no-img');
            img.remove();
        });
        if (window.PressFx) PressFx.bind(el);   // 压感：外环 / 启动 / 工具箱 / 子卡统一
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
                    if (this.launcherOpen) this._applyLaunch(el, i, total, true, true);   // fly=true：这一次要回弹
                }, i * this.CFG.LAUNCH_STAGGER);
            } else {
                this._applyLaunch(el, i, total, false, true);                          // fly=true：收回也要回弹
                this._unflip(el);
            }
        });
        const system = document.getElementById('orbitSystem');
        if (system) system.classList.toggle('launcher-open', open);
        this._applyCenterZ();    // 启动器展开时中心球整层抬到启动卡那一带（255）
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











    initToolboxSub() {
        const orbit = document.getElementById('toolboxOrbit');
        const system = document.getElementById('toolboxSystem');
        if (!orbit || !system) return;

        const kidsBox = document.createElement('div');
        kidsBox.className = 'children';
        system.appendChild(kidsBox);

        const els = this.toolboxPlanets.map((p, i) => {
            // 工具箱卡不抠像：用不透明 jpg（opaque=true）
            const el = this._buildCard(p, this.toolboxPlanets.length, i, null, null, false, true);
            this._place(el, el._ang, 0, this.GEO.TR, this.GEO.TRY);
            el.addEventListener('click', (e) => this._onCardClick(e, 'tool', el, p));
            orbit.appendChild(el);
            return el;
        });
        this._initDeck('tool', kidsBox, els, [this.GEO.TR, this.GEO.TRY], () => this.toolboxRotation,
                       (node, src) => this._toPanel(node.id, src, window.App && App.onToolboxPlanetClick), system);
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
