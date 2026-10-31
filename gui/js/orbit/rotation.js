/**
 * Orbit 旋转几何（从 orbit.js 拆出）
 *
 * ============================================================================
 * 一、几何模型（照抄经典「圆轨道 + 压扁」写法，务必先读完这一段再改任何数字）
 * ============================================================================
 *
 * 卡片先均匀落在一个【正圆】上，再把整圈【垂直压扁】得到屏幕上的椭圆：
 *
 *      a  = 卡片基准角 el._ang + 当前转动角 rotation        （只有它在变）
 *      x  = R   · sin(a)                                   （正圆）
 *      y  = R   · FLAT · cos(a)                            （压扁 → 椭圆）
 *
 * 参考实现（LESS 版）是这么写的：
 *      @r: @w1 / 2;                                  ← 半径就一个数，轨道宽的一半
 *      left: @r + @r * sin(m);  bottom: @r + @r * cos(m);   ← 每张卡用同一个 @r
 *      @keyframes spin { transform: scaleY(.5) rotate(θ) }  ← 压扁是【容器】上的一步
 *
 * 【两条铁律，踩过坑】
 *
 *   铁律 1：R 是常量。
 *     只在 data.js 的 CFG 里配一次，运行时任何人都不许重算它、不许按视口高度夹取、
 *     不许因为"要适配小窗口/要让半径变大"去改它。
 *     历史事故：曾经有个 _fitRadius() 在 init 时按视口高度重算 RX/RY，
 *     于是"半径会收缩"这个 bug 永远修不干净 —— 窗口一变、面板一开，半径就被重算一次。
 *     现在改成：半径写死；小窗口塞不下就切边，连容器都不缩 —— _applyZoom 已删除，
 *     并由 _lockRadius() 兜底：任何给轨道元素写 transform 的路径都会被当场抹掉。
 *
 *   铁律 2：扁平只由 FLAT 一个系数控制，不要再引入第二个半径。
 *     历史事故：曾用 RX / RY 两个独立半径来表达扁平，结果"调半径"和"调形状"
 *     变成同一个动作，每次改需求都在同时动两件事，反复出新 bug（一会儿 840/280，
 *     一会儿 368/320，一会儿又做成正圆）。现在 R 管大小、FLAT 管形状，互不干扰。
 *
 *   为什么不用参考实现的 scaleY(0.5)：
 *     - 容器 scaleY 会把卡片本身也压扁，得在每张卡上再乘 scaleY(1/FLAT) 抵消；
 *     - .slot 里挂着 perspective 和 3D 翻牌，嵌套非均匀缩放会让翻牌变形。
 *     直接把 FLAT 乘进 y 坐标，屏幕结果完全一致，卡片却始终正立、零变形。
 *
 *   卡片尺寸（挂点 = 参考实现 anti-spin 末尾那个 scale(1)）：
 *     sc = 基准倍率 × (SCALE_MIN + 深度归一 × SCALE_SPAN)
 *     深度归一 = (cos(a) + 1) / 2   ∈ [0,1]    1 = 最近（正对观众），0 = 最远
 *     它是【均匀】缩放，所以 FLAT 不会把它拉变形。
 *
 *     ★ 尺寸【必须】随 depth 变（SCALE_SPAN 不为 0）—— 这就是本项目的"远大近小"，
 *       用户已明确确认过方向，不要再抹平成常量。
 *       - 配置轨 / 工具箱轨：sc ∈ 0.864~1.440（118×162 ~ 196×271）
 *       - 启动轨：           sc ∈ 0.700~1.040（95×132 ~ 141×196），每个深度都更小
 *     ⚠️ 位置坐标永远用 cos(a)，深度才乘 DEPTH_DIR —— 两者混用会把椭圆翻过来。
 *
 * 半径与尺寸是【两个独立的旋钮】，别再互相抵消：
 *     要卡片更大/更小 → 改 SCALE_*；要轨道更大/更小 → 改 R；要更扁 → 改 FLAT。
 *
 * ============================================================================
 * 二、对外契约（改了会连带打断交互，禁止随手改签名）
 * ============================================================================
 *   _place(el, baseAngle, rotDeg, RX, RY)
 *       ← deck.js 的 deck.restore()、drag.js 的 place() 都按这个签名调用，
 *         且半径是从 deck 捕获的 [RX, RY] 数组里取的。签名必须保持稳定。
 *   _applyLaunch(el, index, total, open, fly)  ← toggleLauncher(fly=true) / _syncLauncher(fly 省略=false)
 *   _syncLauncher()                        ← drag.js 的 place() / _focusCard / 吸附
 *   GEO = { R, RY, LR, LRY, TR, TRY, ... }  ← init 时算一次，之后只读
 *
 * 加载顺序：必须在 js/orbit.js 之后（和 deck.js / drag.js 同一个 Object.assign 约定）。
 */

Object.assign(Orbit, {
    // 旋转几何的运行时数值，init 时由 _applyGeometry() 算一次，之后只读
    GEO: null,

    /**
     * 把 CFG 里的常量（R / FLAT / LR / LFLAT / TR / TFLAT）展开成轨道要用的半轴，
     * 并算出"最大卡片尺寸"（视口安全缩放要用）。只在 init 调一次。
     */
    // 兜底默认值：只有当 CFG 里缺字段时才用得上（见下面 pick 的注释）
    GEO_DEFAULTS: { R: 430, FLAT: 0.5, LR: 200, LFLAT: 0.5, TR: 215, TFLAT: 0.5,
                    SCALE_MIN: 1, SCALE_SPAN: 0, CONFIG_SCALE: 1.2,
                    LAUNCH_SCALE: 1, L_SCALE_MIN: 0.7, L_SCALE_SPAN: 0.34 },

    _applyGeometry() {
        const c = this.CFG, D = this.GEO_DEFAULTS;
        // ⚠️ 这里每个值都必须能兜底。曾经出现过"data.js 与 rotation.js 版本不一致"，
        //    CFG.R 是 undefined → GEO.R = undefined → 每张卡写出的 transform 都是
        //    translate3d(NaNpx,…) → 浏览器整条丢弃 → 卡片回落到 CSS 的 top/left:50%
        //    → 一圈卡全部堆在容器正中。宁可退化成默认半径，也绝不能是 undefined/NaN。
        const pick = (v, d, name) => {
            if (isFinite(v) && v > 0) return v;
            if (!this._geoWarned) {
                this._geoWarned = true;
                console.error('[Orbit] CFG.' + name + ' 缺失或非法（data.js 可能是旧版本），' +
                              '已回落到内置默认值 ' + d + '。请强制刷新 Ctrl+F5 清缓存。');
            }
            return d;
        };
        const R = pick(c.R, D.R, 'R');
        const FLAT = pick(c.FLAT, D.FLAT, 'FLAT');
        const LR = pick(c.LR, D.LR, 'LR');
        const LFLAT = pick(c.LFLAT, D.LFLAT, 'LFLAT');
        const TR = pick(c.TR, D.TR, 'TR');
        const TFLAT = pick(c.TFLAT, D.TFLAT, 'TFLAT');
        const cs = isFinite(c.CONFIG_SCALE) && c.CONFIG_SCALE > 0 ? c.CONFIG_SCALE : D.CONFIG_SCALE;
        const smin = isFinite(c.SCALE_MIN) ? c.SCALE_MIN : D.SCALE_MIN;
        const sspan = isFinite(c.SCALE_SPAN) ? c.SCALE_SPAN : D.SCALE_SPAN;
        const k = cs * (smin + sspan);            // 最近那张的倍率
        this.GEO = {
            FLAT: FLAT, LFLAT: LFLAT, TFLAT: TFLAT,

            R: R,                                      // 半径（常量，别动）
            RY: Math.round(R * FLAT),                  // 纵向半轴 = R × FLAT

            LR: LR,                                    // 启动内环半径
            LRY: Math.round(LR * LFLAT),

            TR: TR,                                    // 工具箱环半径
            TRY: Math.round(TR * TFLAT),

            cardMaxW: Math.round(136 * k),             // 最近那张的真实宽（.slot 基准 136×188）
            cardMaxH: Math.round(188 * k),

            // 启动簇整体上移量（px）= LRY × LAUNCH_UP_K。
            // 让启动轨最低那张正好落在配置轨中心线上 → 启动卡整体高于配置卡。
            LAUNCH_UP: Math.round(LR * LFLAT * (isFinite(c.LAUNCH_UP_K) ? c.LAUNCH_UP_K : 1))
        };
        // 写到启动簇上：CSS 里用 top: calc(50% - var(--launcher-up)) 上移。
        // ⚠️ 不能用 transform 上移 —— transform 会生成层叠上下文，中心球就再也没法和卡片按深度交错。
        const cl = document.getElementById('launcherCluster');
        if (cl) cl.style.setProperty('--launcher-up', this.GEO.LAUNCH_UP + 'px');
        return this.GEO;
    },

    /* ★ 这里原本是 _applyZoom()：视口塞不下时给 #orbitSystem 写 scale()（等比缩整圈）。
       它已经被【彻底删除】—— 那是唯一能让半径在运行时变掉的机制，窗口一变就重算，
       表现就是"半径会缩放"。现在半径只由 CFG 常量决定，窗口小就切边，绝不改半径。
       相关：_lockRadius() 会盯住这几个元素，谁写 transform 就当场抹掉。 */


    /**
     * 半径审计：从环线一路往上走到 #orbitSystem，打出每层 computed transform 的 scale 分量。
     * 只该看到 1.000。任何一个 ≠1 就是"有人在缩放半径"。
     * 控制台：__orbitRadiusAudit()
     */
    radiusAudit() {
        const out = [];
        let el = document.querySelector('.ring-outer');
        while (el && el !== document.body) {
            const cs = getComputedStyle(el);
            const tr = cs.transform;
            let sx = 1, sy = 1;
            if (tr && tr !== 'none') {
                const m = tr.match(/matrix(?:3d)?\(([^)]+)\)/);
                if (m) {
                    const p = m[1].split(',').map(Number);
                    sx = p[0]; sy = (p.length > 6) ? p[5] : p[3];
                }
            }
            out.push({ node: el.id ? ('#' + el.id) : (el.className || el.tagName),
                       transform: tr, scaleX: +sx.toFixed(3), scaleY: +sy.toFixed(3) });
            el = el.parentElement;
        }
        const bad = out.filter(x => Math.abs(x.scaleX - 1) > 1e-3 || Math.abs(x.scaleY - 1) > 1e-3);
        console.log('[radiusAudit] 环线 → #orbitSystem 的祖先链：', out);
        console.log(bad.length ? '❌ 有东西在缩放半径：' : '✅ 没有任何缩放（半径是常量）', bad);
        return bad;
    },

    /**
     * 半径锁：半径必须是常量，所以这几个元素身上不许出现 transform。
     * 有人写了（自己人将来手滑、或别处代码）就当场抹掉并报警 —— 这是"删掉可能性"，
     * 不是"删掉某一处调用"。历史坑：_applyZoom 曾按视口给 #orbitSystem 写 scale()。
     */
    _lockRadius() {
        const targets = [];
        ['orbitSystem', 'orbitOuter', 'launcherCluster', 'toolboxSystem'].forEach(id => {
            const el = document.getElementById(id);
            if (el) targets.push(el);
        });
        ['.ring-outer', '.toolbox-ring', '.toolbox-orbit'].forEach(sel => {
            const el = document.querySelector(sel);
            if (el) targets.push(el);
        });
        const strip = (el) => {
            const t = el.style && el.style.transform;
            if (!t) return;
            el.style.removeProperty('transform');
            console.warn('[Orbit][半径锁] 抹掉了 ' + (el.id ? ('#' + el.id) : el.className) +
                         ' 上的 transform: ' + t + '（轨道半径必须是常量，不许缩放）');
            if (typeof window.__orbitRadiusWarned !== 'number') window.__orbitRadiusWarned = 0;
            window.__orbitRadiusWarned++;
        };
        targets.forEach(el => {
            strip(el);
            if (el.__radiusLocked) return;
            el.__radiusLocked = true;
            try {
                new MutationObserver(() => strip(el)).observe(el, { attributes: true, attributeFilter: ['style'] });
            } catch (e) { /* 老浏览器没有 MutationObserver 就算了，strip 平时也会被 walk 到 */ }
        });
    },

    /**
     * 轨道坐标解算（配置环 / 启动环 / 工具箱环共用，别再各写一份）
     *   baseAngle : 卡片基准角（弧度，el._ang / el._lang）
     *   rotDeg    : 当前转动角（度）
     *   R         : 正圆半径
     *   FLAT      : 垂直压扁系数
     * 返回 { a, depth, x, y }：
     *   depth = cos(a) ∈ [-1,1]，1 = 最近（屏幕最下方），-1 = 最远（最上方）
     */
    _orbitPoint(baseAngle, rotDeg, R, FLAT) {
        const a = baseAngle + rotDeg * Math.PI / 180;
        const cy = Math.cos(a);
        // ⚠️ depth 与坐标要分开算：
        //   坐标 y 永远用 cos(a)（这是几何，决定椭圆形状，不能翻）；
        //   depth 才乘 DEPTH_DIR（这是"哪边算近"的约定，决定大小/明暗/层级，可以翻）。
        //   以前这里只有 cos(a)，所以"上方算近"这种直觉没法表达，
        //   一旦感觉反了就只能在别处乱改，近大远小被改坏的根源之一。
        const depth = cy * (this.CFG.DEPTH_DIR === -1 ? -1 : 1);
        return {
            a: a, depth: depth,
            x: R * Math.sin(a),
            y: R * (FLAT === undefined ? 1 : FLAT) * cy
        };
    },

    /** 近大远小：深度 → 均匀缩放。挂点等价于参考实现里那个 scale(1) */
    _depthScale(depth, base, min, span) {
        return base * (min + (depth + 1) / 2 * span);
    },

    /**
     * 把解算结果写到元素上（transform / 层级 / 正对判定）
     * ⚠️ --inv 是 tooltip 的反向补偿变量，cards.css 在用，删了提示会跟着卡片一起缩放。
     */
    /** 深度 → z-index。zBase 是"整层垫高"：配置卡 0（z 5~105），启动卡 LAUNCH_Z_BASE（z 205~305）。
     *  中心球用同一套：配置态 depth=0、zBase=0 → 55；启动器展开时 zBase=LAUNCH_Z_BASE → 255。
     *  这样"卡"和"球"在同一层叠上下文里按深度交错：近半圈盖住球，远半圈被球盖住。 */
    _depthZ(depth, zBase) {
        return (zBase || 0) + Math.round((depth + 1) * 50 + 5);
    },

    /**
     * 把解算结果写到元素上。
     * transform 每帧都得写（位置在变），但 zIndex / --inv / .front 大多数时候没变 ——
     * 重复写同一个值也会让这个元素样式失效、触发重算和层重排。
     * 所以这三个都记忆化：只在真的变了才写。
     * ⚠️ 任何【绕开这里】直接改 zIndex 的路径（比如 deck.js 给父卡写 900）
     *    必须把 el._z 置空，否则这里的记忆值会让它卡在 900。
     */
    _placeAt(el, x, y, depth, sc, zBase) {
        const tf = 'translate3d(' + x.toFixed(1) + 'px, ' + y.toFixed(1) + 'px, 0) ' +
                   'scale(' + sc.toFixed(3) + ')';
        el.style.transform = tf;

        const z = this._depthZ(depth, zBase);                         // 越近越靠前
        if (el._z !== z) { el.style.zIndex = String(z); el._z = z; }

        const inv = (1 / sc).toFixed(3);
        if (el._inv !== inv) { el.style.setProperty('--inv', inv); el._inv = inv; }

        const front = depth > 0.985;                                   // 正对观众那一张
        if (el._front !== front) { el.classList.toggle('front', front); el._front = front; }
    },

    /** 中心球的 z：配置态 = 中心深度(0) 的 z；启动器展开时整层抬到启动卡那一带 */
    _applyCenterZ() {
        const z = this._depthZ(0, this.launcherOpen ? (this.CFG.LAUNCH_Z_BASE || 200) : 0);
        const a = document.getElementById('centerLauncher');
        if (a) a.style.zIndex = String(z);
        // 工具箱中心球永远是 55（它自己那套层叠上下文里，只和工具卡交错，跟启动器无关）
        const t = document.querySelector('.toolbox-center');
        if (t) t.style.zIndex = String(this._depthZ(0, 0));
    },

    /**
     * 【交互契约，签名不许改】把一张卡摆到轨道上。
     *   RX / RY : 横向 / 纵向半轴（= GEO.R 与 GEO.RY）
     * deck.js 的 restore 与 drag.js 的 place 都是 (el, _, rot, radius[0], radius[1]) 这个形状。
     * （原来的第 6 个形参 tiltDeg 已删：倾角弹簧从没接上轨道，所有调用方都不传它。）
     */
    _place(el, baseAngle, rotDeg, RX, RY) {
        // ---------- 护栏（排查"卡片全堆到中间"，不要删）----------
        // 半径/角度只要有一个非法，写出来的就是 translate3d(NaNpx,…)（整条声明被浏览器丢弃）
        // 或 translate3d(0px,0px,0)（卡片精确堆到容器正中，因为 .slot 是 top/left:50%）。
        // 这里统一回落到 GEO 并只报一次错，同时把真凶打印出来。
        if (!isFinite(RX) || !isFinite(RY) || RX <= 0 || RY <= 0 ||
            !isFinite(baseAngle) || !isFinite(rotDeg)) {
            if (!this._placeWarned) {
                this._placeWarned = true;
                console.error('[Orbit] _place 收到非法几何，已回落到 GEO。RX=' + RX + ' RY=' + RY +
                    ' _ang=' + baseAngle + ' rot=' + rotDeg +
                    ' el=' + (el && el.dataset ? el.dataset.id : el));
            }
            const g = (this.GEO && isFinite(this.GEO.R) && this.GEO.R > 0)
                ? this.GEO : this._applyGeometry();
            RX = g.R; RY = g.RY;
            baseAngle = (el && isFinite(el._ang)) ? el._ang : 0;
            rotDeg = isFinite(rotDeg) ? rotDeg : 0;
        }
        const flat = RY / RX;                                         // 由两个半轴反推压扁系数
        const p = this._orbitPoint(baseAngle, rotDeg, RX, flat);
        const sc = this._depthScale(p.depth, this.CFG.CONFIG_SCALE || 1,
                                    this.CFG.SCALE_MIN, this.CFG.SCALE_SPAN);
        this._placeAt(el, p.x, p.y, p.depth, sc, 0);   // 配置轨/工具箱：z 带基准 0
    },

    /**
     * 按 GEO 把整圈重摆一遍（幂等：正常路径下就是写同一批坐标）。
     * 唯一用处是"兜底"——万一有没排查到的路径把卡片 transform 弄没了，
     * 松手/缩放后立刻恢复，不至于一堆卡堆在容器正中。
     * ⚠️ 必须跳过摊开中的父卡（它此时被刻意摆在中央放大），否则会把扇形打断。
     */
    _syncRing() {
        let fixed = 0;
        Object.keys(this._deck).forEach(k => {
            const d = this._deck[k];
            if (!d || !d.els) return;
            d.els.forEach(el => {
                if (el === d.parent) return;                 // 摊开中的父卡：故意摆在中央，跳过
                const tf = el.style.transform || '';
                // 只看"明显坏了"的情况，不干扰正常的每帧定位：
                // 空 transform / 正好在正中 / 含 NaN —— 这三种都会让卡片堆在容器中心
                if (!tf || tf.indexOf('NaN') >= 0 || /translate3d\(0px, 0px, 0px\)/.test(tf)) {
                    d.restore(el);
                    fixed++;
                }
            });
        });
        if (fixed && !this._syncRingLogged) {
            this._syncRingLogged = true;
            console.warn('[Orbit] _syncRing 兜底修复了 ' + fixed + ' 张卡（说明有路径把 transform 清了，' +
                         '请把 __orbitDiag() 的输出发出来定位）');
        }
        return fixed;
    },

    /** 看门狗：每 3 秒自检一次，坏了自己摆回来；正常情况下什么都不做 */
    _startRingWatchdog() {
        if (this._ringTimer) return;
        this._ringTimer = setInterval(() => {
            try { this._syncRing(); } catch (e) { /* 兜底本身不许抛 */ }
        }, 3000);
    },

    /**
     * 诊断命令：出问题时在 F12 控制台执行 __orbitDiag()，把输出贴给我。
     * 它会一次性列出：几何常量、每个 deck 的半径、有多少张卡的 transform 是空的
     * 或正好是 translate3d(0px,0px,0)、容器缩放值、各容器里的卡片数量。
     */
    _diag() {
        const out = { GEO: this.GEO, CFG: {} };   // zoom 字段已删：半径不再缩放
        ['R', 'FLAT', 'LR', 'LFLAT', 'TR', 'TFLAT', 'SCALE_MIN', 'SCALE_SPAN', 'CONFIG_SCALE',
         'LAUNCH_SCALE', 'L_SCALE_MIN', 'L_SCALE_SPAN', 'RING_DY_VH']
            .forEach(k => { out.CFG[k] = this.CFG[k]; });
        const sys = document.getElementById('orbitSystem');
        out.systemTransform = sys ? (sys.style.transform || '(无)') : '(找不到 #orbitSystem)';
        out.decks = {};
        ['outer', 'tool'].forEach(k => {
            const d = this._deck[k];
            if (!d) { out.decks[k] = '(未初始化)'; return; }
            const els = d.els || [];
            out.decks[k] = {
                radius: d.radius,
                open: d.open,
                parent: d.parent ? d.parent.dataset.id : null,
                count: els.length,
                emptyTransform: els.filter(el => !el.style.transform).length,
                atCenter: els.filter(el => /translate3d\(0px, 0px, 0px\)/.test(el.style.transform || '')).length,
                sample: els.slice(0, 3).map(el => el.dataset.id + ' → ' + (el.style.transform || '(空)'))
            };
        });
        // 每张卡：深度 / 到中心距离 / 实际缩放 —— 用来肉眼核对"近大远小"
        out.ring = ['outer', 'tool'].reduce((acc, k) => {
            const d = this._deck[k];
            if (!d) return acc;
            const at = document.getElementById(k === 'tool' ? 'toolboxOrbit' : 'orbitOuter');
            const rc = at ? at.getBoundingClientRect() : null;
            const cx = rc ? rc.left + rc.width / 2 : 0, cy2 = rc ? rc.top + rc.height / 2 : 0;
            acc[k] = d.els.map(el => {
                const q = el.getBoundingClientRect();
                const dx = q.left + q.width / 2 - cx, dy = q.top + q.height / 2 - cy2;
                const m = /scale\(([0-9.]+)\)/.exec(el.style.transform || '');
                return { id: el.dataset.id, dist: Math.round(Math.sqrt(dx * dx + dy * dy)),
                         w: Math.round(q.width), scale: m ? +m[1] : null };
            });
            return acc;
        }, {});
        out.domCounts = {
            outer: document.querySelectorAll('#orbitOuter .slot').length,
            launch: document.querySelectorAll('#launcherCluster .slot').length,
            tool: document.querySelectorAll('#toolboxOrbit .slot').length
        };
        console.log('__ORBIT_DIAG__ ' + JSON.stringify(out, null, 2));
        return out;
    },

    /** 轨道环那圈线（纯视觉，必须正穿过卡片中心）：宽高 = 直径 + 边距 dw/dh
     *  ⚠️ dw / dh 必须传 0。传正数环就比卡心轨道大，看着就是"半径不对"。 */
    _fitRing(ringEl, R, FLAT, dw, dh) {
        if (!ringEl) return;
        const w = R * 2 + dw, h = R * (FLAT === undefined ? 1 : FLAT) * 2 + dh;
        ringEl.style.width = w + 'px';
        ringEl.style.height = h + 'px';
        ringEl.style.margin = (-h / 2) + 'px 0 0 ' + (-w / 2) + 'px';
    },

    /** 画两条环线（外层轨道 + 工具箱轨道），尺寸跟着 GEO 走 */
    _applyRingLines() {
        const g = this.GEO;
        if (!g) return;
        // ★ 边距传 0：环线的半径就是卡心轨道的半径（R 与 R×FLAT）。
        //   曾经传的是 20 / 10 → 环宽 880、高 440，半径比卡心大 10px / 5px；
        //   再叠加 border 画在内容盒外面（content-box），实际大了 11px / 6px，
        //   屏幕上就是"环和卡心没对齐"。参考实现里环是容器自己的 border、
        //   容器半径 = 元素定位半径，天生长在一起；这里靠这条 0 保证等价。
        this._fitRing(document.querySelector('#orbitOuter .ring-outer'), g.R, g.FLAT, 0, 0);
        this._fitRing(document.querySelector('#toolboxOrbit .toolbox-ring'), g.TR, g.TFLAT, 0, 0);
    },

    /**
     * 启动卡定位：自己的一圈椭圆轨道，展开时从中心球飞出去。
     * open = false 时缩回球心并隐藏（收完直接从渲染树摘掉，避免看不见却截获点击）。
     */
    _applyLaunch(el, index, total, open, fly) {
        const g = this.GEO || this._applyGeometry();
        // fly = 这一次是不是"真正的飞出/收回"（只有 toggleLauncher 才是）。
        // 挂 .launch-fly 才有 transform 回弹；轨道重排（_syncLauncher / 吸附 / 聚焦）
        // 一律不挂 —— 否则每帧写的目标会被 0.5s 回弹插值，看着像半径在变。
        clearTimeout(el._flyTimer);
        if (fly) {
            el.classList.add('launch-fly');
            el._flyTimer = setTimeout(() => el.classList.remove('launch-fly'), 560);
        } else {
            el.classList.remove('launch-fly');
        }
        if (!open) {
            el.style.transform = 'translate3d(0px, 0px, 0px) scale(0.15)';
            el.style.opacity = '0';
            el.style.pointerEvents = 'none';
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

        const p = this._orbitPoint(el._lang, this.launcherRotation, g.LR, g.LFLAT);
        const sc = this._depthScale(p.depth, this.CFG.LAUNCH_SCALE || 1,
                                    this.CFG.L_SCALE_MIN, this.CFG.L_SCALE_SPAN);
        // z 带基准抬到 LAUNCH_Z_BASE：启动卡整层压在配置卡之上
        this._placeAt(el, p.x, p.y, p.depth, sc, this.CFG.LAUNCH_Z_BASE || 200);
        el.style.opacity = '1';
        el.style.pointerEvents = 'auto';
    },

    /** 轨道转动后重排启动卡（drag.js / 吸附 / 点击聚焦都会调） */
    _syncLauncher() {
        if (!this.launcherOpen) return;
        const total = this.launchEls.length;
        this.launchEls.forEach((el, i) => this._applyLaunch(el, i, total, true));
    }
});
