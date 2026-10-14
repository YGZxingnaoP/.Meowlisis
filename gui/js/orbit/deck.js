/**
 * Orbit 子卡展开 / 点击分发（从 orbit.js 拆出）
 * 需在 js/orbit.js 之后加载。
 */
Object.assign(Orbit, {
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
     * 点击未聚焦的卡：先把它快速转到正对观众的位置（260ms），到位再执行动作。
     * 转动期间 _setAnim(false) → 整条轨道变成刚体，任何 transform 过渡都停掉，
     * 所以不会出现"卡片追着目标滑、轨道半径看着在变"。
     */
    _focusCard(name, el, cb) {
        const isLauncher = name === 'launcher';
        const d = this._deck[name];
        const base = ((isLauncher ? el._lang : el._ang) || 0) * 180 / Math.PI;
        const getR = () => isLauncher ? this.launcherRotation
            : (name === 'tool' ? this.toolboxRotation : this.rotation);
        const setR = (v) => {
            if (isLauncher) { this.launcherRotation = v; return; }
            if (name === 'tool') { this.toolboxRotation = v; return; }
            this.rotation = v;
        };
        const paint = () => {
            if (isLauncher) { this._syncLauncher(); return; }
            if (d) d.els.forEach(x => d.restore(x));
        };
        const cur = getR();
        let goal = -base;
        goal += 360 * Math.round((cur - goal) / 360);        // 就近方向转
        if (Math.abs(goal - cur) < 0.5) { cb(); return; }
        this._setAnim(false);
        const t0 = performance.now(), dur = 260;
        const ease = (t) => {
            const p = Math.min(1, (t - t0) / dur);
            const k = 1 - Math.pow(1 - p, 3);
            setR(cur + (goal - cur) * k);
            paint();
            if (p < 1) { requestAnimationFrame(ease); return; }
            this._setAnim(true);
            cb();
        };
        requestAnimationFrame(ease);
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

        const act = () => {
            if (node.kids && node.kids.length) {
                this._flipThen(el, () => this._spread(name, el, node));   // 先翻牌，翻完再摊开
                return;
            }
            if (node.overlay) this._overlayCard = el;                 // 打开浮层的卡，关浮层时翻回
            this._flipThen(el, () => d.openPanel(node, el));
        };
        // 没聚焦就先快速转到正对观众的聚焦位，转到位再打开
        this._focusCard(name, el, act);
    },

    _spread(name, parentEl, node) {
        const d = this._deck[name];
        if (!d) return;
        this._collapse(name);

        d.parent = parentEl;
        d.open = true;
        parentEl.classList.add('focus');
        if (d.sysEl) d.sysEl.classList.add('focusing');   // 轨道层提到主球之上（见 orbit.css）
        const kc = this._kidCfg(name);
        parentEl.style.zIndex = '900';
        // 父卡推到屏幕正中并放大（布局和以前完全一致）
        parentEl.style.transform = 'translate3d(0px, ' + kc.PARENT_DY + 'px, 0) scale(' +
                                    kc.FOCUS_SCALE + ')';
        parentEl.style.setProperty('--inv', (1 / kc.FOCUS_SCALE).toFixed(3));

        // ★ 子卡的【动画原点】= 父卡被点中前的那个位置（屏幕正下方那张，a≈0 的聚焦卡）。
        //   子卡从那里"长出来"，再飞到各自的扇位 —— 这就是"直接从底部聚焦卡展开"。
        //   位置本身没变：终点仍是原来的扇形（相对容器中心算），只是起点换成了这张卡。
        //   原点按几何算，不用 getBoundingClientRect：父卡这会儿身上挂着正在跑的
        //   过渡 transform（正往正中飞），量出来是中间态。
        const g = this.GEO || this._applyGeometry();
        const pp = this._orbitPoint(parentEl._ang, (d.rot ? d.rot() : 0), g.R, g.FLAT);
        // .children 的 0 点在 #orbitSystem 正中心，pp 是相对【轨道中心】算的；
        // 配置层在 CSS 里下移了 2vh，要补回来，否则起手点会比那张卡高 2vh。
        // 工具箱那套轨道居中在面板里，没有这个偏移。
        const ringDy = (name === 'tool') ? 0 : (window.innerHeight || 900) * (this.CFG.RING_DY_VH || 0);
        d.subOrigin = { x: pp.x, y: pp.y + ringDy };
        this._syncDim();

        const kids = node.kids;
        const total = kids.length;
        const mid = (total - 1) / 2;
        d.box.innerHTML = '';
        d.subs = kids.map((k, i) => {
            const el = this._buildCard({ id: k.id, label: k.label, tooltip: k.tooltip }, total, i, k.card);
            el.className = 'sub';
            // 扇展错峰：第 i 张晚 i × SUB_STAGGER 秒再飞出去（纯视觉，位置 80ms 后一次性算完）
            el.style.transitionDelay = (i * (this.CFG.SUB_STAGGER || 0)).toFixed(3) + 's';
            const off = i - mid;
            el.dataset.dx = (off * kc.KID_SPACING).toFixed(1);
            el.dataset.dy = (kc.KID_DY0 + Math.abs(off) * this._fanSpan(name)).toFixed(1);
            el.dataset.rot = (off * kc.KID_ROT).toFixed(1);
            // 出生点 = 那张被点中的卡（屏幕正下方），缩小态；80ms 后飞到上面的扇位
            el.style.transform = 'translate3d(' + d.subOrigin.x.toFixed(1) + 'px, ' +
                                 d.subOrigin.y.toFixed(1) + 'px, 0) scale(0.25)';
            el.addEventListener('click', (ev) => {
                ev.stopPropagation();
                if (this.suppressClick) return;
                this._flipThen(el, () => d.openPanel(k, el));   // 子卡同样翻牌后再开面板
            });
            d.box.appendChild(el);
            return el;
        });

        // 先落在父卡卡心里，下一帧再摊开 → 视觉上是"从这张卡长出来的"
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
        // 收回走同一套原点：子卡一起缩回那张聚焦卡（展开时的起手点）
        const o = d.subOrigin || { x: 0, y: 0 };
        d.subs.forEach(el => {
            this._unflip(el);
            el.style.transitionDelay = '0s';      // 收起时不带错峰延迟：同时往回缩
            el.style.transform = 'translate3d(' + o.x.toFixed(1) + 'px, ' +
                                 o.y.toFixed(1) + 'px, 0) scale(0.25)';
        });
        this._syncDim();

        const box = d.box;
        clearTimeout(d.gcTimer);
        d.gcTimer = setTimeout(() => { if (!d.open) box.innerHTML = ''; }, 700);

        d.subs = [];
        d.subOrigin = null;
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
        // rotating = 转动中：连 .slot-launch 的回弹过渡一起停掉，
        // 否则启动轨每帧写 transform 都是在 0.5s 过渡里追目标（看着像半径在变）
        ['orbitSystem', 'launcherCluster', 'toolboxSystem'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.toggle('rotating', !on);
        });
    }
});