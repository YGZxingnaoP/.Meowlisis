/**
 * 卡片压感反馈（按下 → 下沉 + 微倾斜 + 触点光斑，松开 → 弹簧回弹）
 *
 * 只写 CSS 变量、不碰布局、不写 element.transform 的绝对坐标：
 * .slot 的 transform 是轨道每帧重写的（js/orbit/rotation.js 的 _placeAt），
 * 往那儿写会被下一帧吞掉，还会重演"半径在变"的老 bug。
 * 压感落在 .card-press 这一层（见 css/cards.css），由 Orbit._buildCard 给每张卡调 bind()：
 * 外环 13 张 / 启动 9 张 / 工具箱 10 张 / 所有子卡都走同一套。
 *
 * 手感参数：
 *   MAX_TILT  按住时的最大倾斜（度）—— 越大越"抓得住"，但也越容易和轨道缩放抢视线
 *   HOVER_TILT 没按下、指针划过时的轻微倾斜（告诉用户"这张能按"）
 *   DRAG_TOLERANCE 指针位移超过这么多 px 就当成在拖轨道，立刻复位
 */
const PressFx = {
    MAX_TILT: 26,
    HOVER_TILT: 9,
    DRAG_TOLERANCE: 4,

    /** 当前正在被按的那张（同一时刻只允许一张有"按下"态，避免多点触控串味） */
    _active: null,

    /**
     * 给一张卡绑压感。el 是 .slot / .sub（外面那层，由轨道用 transform 定位）。
     * 缺 .card-press 的卡（老缓存/插件卡）直接跳过，不报错。
     */
    bind(el) {
        if (!el || el._pressBound) return;
        const wrap = el.querySelector('.card-press');
        if (!wrap) return;
        el._pressBound = true;

        const glare = el.querySelector('.card-glare');
        const ring = el.querySelector('.card-ring');
        const st = {
            down: false, press: 0, tx: 0, ty: 0,
            sx: 50, sy: 50, ox: 0, oy: 0, pointerId: null,
            raf: 0, dirty: false,
            rect: null        // ★ 缓存卡片矩形：pointermove 里不再每次量（那会强制重算样式/布局）
        };

        const flush = () => {
            st.raf = 0;
            if (!st.dirty) return;
            st.dirty = false;
            wrap.style.setProperty('--press', st.press.toFixed(3));
            wrap.style.setProperty('--tx', st.tx.toFixed(2));
            wrap.style.setProperty('--ty', st.ty.toFixed(2));
            wrap.style.setProperty('--sx', st.sx.toFixed(1));
            wrap.style.setProperty('--sy', st.sy.toFixed(1));
            if (glare) {
                wrap.style.setProperty('--mx', st.sx.toFixed(1));
                wrap.style.setProperty('--my', st.sy.toFixed(1));
            }
        };
        const schedule = () => {
            st.dirty = true;
            if (!st.raf) st.raf = requestAnimationFrame(flush);
        };
        const measure = () => { st.rect = el.getBoundingClientRect(); };

        // 指针 → 卡内百分比（0..1）。只算数，样式统一在 flush 里写（每帧最多一组）。
        const track = (e) => {
            const r = st.rect || (st.rect = el.getBoundingClientRect());
            const px = Math.max(0, Math.min(1, (e.clientX - r.left) / (r.width || 1)));
            const py = Math.max(0, Math.min(1, (e.clientY - r.top) / (r.height || 1)));
            st.sx = px * 100;
            st.sy = py * 100;
            return { px: px, py: py };
        };

        const tiltTo = (px, py, maxDeg) => {
            st.tx = (px - 0.5) * maxDeg * 2;      // 右边按下 → 右边往里陷
            st.ty = (0.5 - py) * maxDeg * 2;      // 下边按下 → 下边往里陷
        };

        const reset = () => {
            if (st.pointerId !== null) {
                try { el.releasePointerCapture(st.pointerId); } catch (e) { /* 已释放 */ }
                st.pointerId = null;
            }
            st.down = false;
            st.press = 0;
            st.tx = 0;
            st.ty = 0;
            el.classList.remove('pressing');
            if (PressFx._active === st) PressFx._active = null;
            schedule();
        };
        st.reset = reset;
        el._pressState = st;

        // 进入卡片时量一次矩形（之后 pointermove 复用），离开/旋转后下次进入会重新量
        el.addEventListener('pointerenter', measure);

        el.addEventListener('pointerdown', (e) => {
            if (e.button !== 0 && e.pointerType === 'mouse') return;
            // 已经有一张在按（多点触控）→ 先把上一张放开
            if (PressFx._active && PressFx._active !== st) PressFx._active.reset();
            measure();                       // 按下那一刻位置最准，重新量
            const p = track(e);
            st.down = true;
            st.ox = e.clientX;
            st.oy = e.clientY;
            st.pointerId = e.pointerId;
            PressFx._active = st;
            el.classList.add('pressing');
            try { el.setPointerCapture(e.pointerId); } catch (err) { /* 老浏览器 */ }
            // 真压感：笔/触屏用 pointer.pressure（0..1），鼠标固定 0.5
            const raw = (typeof e.pressure === 'number' && e.pressure > 0) ? e.pressure : 0.5;
            st.press = Math.min(1, 0.55 + raw * 0.45);
            tiltTo(p.px, p.py, PressFx.MAX_TILT);
            if (ring) {
                ring.classList.remove('go');
                void ring.offsetWidth;            // 强制重排，同一张卡也能重放动画
                ring.classList.add('go');
            }
            if (navigator.vibrate) { try { navigator.vibrate(8); } catch (err2) { /* 忽略 */ } }
            schedule();
        });

        el.addEventListener('pointermove', (e) => {
            const p = track(e);
            if (st.down) {
                // 动了就是在搓轨道，不是按卡：立刻复位，别让卡跟着手指歪
                if (Math.abs(e.clientX - st.ox) > PressFx.DRAG_TOLERANCE ||
                    Math.abs(e.clientY - st.oy) > PressFx.DRAG_TOLERANCE) {
                    reset();
                    return;
                }
                tiltTo(p.px, p.py, PressFx.MAX_TILT);
            } else {
                tiltTo(p.px, p.py, PressFx.HOVER_TILT);
            }
            schedule();
        });

        el.addEventListener('pointerleave', () => {
            st.rect = null;                                   // 下次进入重新量
            if (!st.down) { st.tx = 0; st.ty = 0; schedule(); }
        });
        el.addEventListener('pointerup', reset);
        el.addEventListener('pointercancel', reset);
        el.addEventListener('lostpointercapture', reset);
    },

    /** 立刻复位所有按下的卡（收起扇形 / 打开面板 / 转轨道时调） */
    releaseAll() {
        const st = this._active;
        if (st && st.reset) st.reset();
    }
};

window.PressFx = PressFx;
