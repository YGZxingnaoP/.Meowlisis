/**
 * Orbit 拖动 / 惯性 / 吸附（从 orbit.js 拆出）
 * 需在 js/orbit.js 之后加载。
 */
Object.assign(Orbit, {
    // ==================== 拖动 + 惯性 ====================
    _bindDrag(container, deckName, getRot, setRot) {
        if (!container) return;
        let dragging = false;
        let lastX = 0;
        let velocity = 0;
        let rafId = null;
        let spin = 0;        // 当前角速度（度/帧），驱动卡片倾角
        let tilt = 0;        // 当前倾角（度）
        let tiltVel = 0;     // 倾角速度（弹簧用）
        let tickId = null;   // 倾角弹簧的动画句柄
        const TILT_GAIN = 0.55;
        const TILT_MAX = 7;
        const TILT_STIFF = 0.03;    // 弹簧刚度：越小摆动越慢
        const TILT_DAMP = 0.94;     // 阻尼：越大摇晃越久，越小收敛越快

        const place = () => {
            // 启动轨道展开时，拖空白转的是启动轨道（外环此时是暗的，转了也看不见）
            if (deckName === 'outer' && this.launcherOpen) { this._syncLauncher(); return; }
            const d = this._deck[deckName];
            if (!d) return;
            const r0 = d.radius[0], r1 = d.radius[1];
            // ⚠️ 第 6 个参数是 tiltDeg，现在恒传 0：tilt 弹簧算了但没接上轨道。
            //    想真让它生效就传 tilt，但要先确认它不是"每帧写 transform 却挂着过渡"的那个坑。
            // ⚠️ 摊开子卡时父卡正被 .slot.focus 送往屏幕正中，不能被这里摆回轨道位
            d.els.forEach(el => { if (el === d.parent) return; this._place(el, el._ang, getRot(), r0, r1, 0); });
        };

        // 倾角走弹簧：目标 = 角速度，松手后带左右摇晃地回到 0
        const tick = () => {
            const target = Math.max(-TILT_MAX, Math.min(TILT_MAX, -spin * TILT_GAIN));
            tiltVel = (tiltVel + (target - tilt) * TILT_STIFF) * TILT_DAMP;
            tilt += tiltVel;
            place();
            const lively = dragging || rafId !== null || Math.abs(tilt) > 0.05 || Math.abs(tiltVel) > 0.05;
            if (lively) { tickId = requestAnimationFrame(tick); return; }
            tilt = 0;
            tiltVel = 0;
            place();
            tickId = null;
            this._setAnim(true);
        };

        const wake = () => {
            if (tickId === null) {
                this._setAnim(false);
                tickId = requestAnimationFrame(tick);
            }
        };

        const inertia = () => {
            setRot(getRot() + velocity);
            spin = velocity;
            velocity *= 0.92;          // 惯性衰减
            wake();
            if (Math.abs(velocity) < 0.05) { rafId = null; spin = 0; snapToCard(); return; }
            rafId = requestAnimationFrame(inertia);
        };

        /** 吸附：拖到最后/惯性停下后，把轨道转到最近一张卡正对观众 */
        const snapStep = () => {
            const d = this._deck[deckName];
            const n = (deckName === 'outer' && this.launcherOpen)
                ? (this.launchEls || []).length : ((d && d.els) ? d.els.length : 0);
            return n ? 360 / n : 0;
        };
        const snapToCard = () => {
            const stepDeg = snapStep();
            if (!stepDeg) return;
            this._setAnim(false);
            const goal = 90 + Math.round((getRot() - 90) / stepDeg) * stepDeg;
            const tick = () => {
                if (dragging) return;
                const now = getRot();
                const diff = goal - now;
                // ⚠️ 这里【绝对不能】调 this._setAnim(true)。
                //    .slot.anim 挂的是 transform 0.5s 弹簧过渡（cubic-bezier .34,1.56,.64,1），
                //    而 tilt tick 这时候还在每帧 place() 写新 transform →
                //    每帧都在追一个 0.5s 弹簧的目标，scale() 被弹簧插值 →
                //    肉眼就是"卡片缩一下再弹回来"（快速拖动时 spin 大、tilt 晃得久，最明显）。
                //    .anim 的恢复只交给 tilt tick 自己收尾那一次（那才是真的停止写入了）。
                // 收尾要把动画态还回去：不还的话 .rotating 永远留在容器上，
                // 子卡/浮层的过渡全被 .rotating 的 !important 杀掉 → 扇展变"闪现"。
                // 不会重现"快速滑动收缩"：现在 .slot 上没有 transform 过渡（见 cards.css），
                // 逐帧写 transform 不可能被弹簧插值。
                if (Math.abs(diff) < 0.2) { setRot(goal); place(); this._setAnim(true); return; }
                setRot(now + diff * 0.22);
                place();
                rafId = requestAnimationFrame(tick);
            };
            rafId = requestAnimationFrame(tick);
        };

        const onMove = (e) => {
            if (!dragging) return;
            const dx = e.clientX - lastX;
            velocity = dx * 0.35;
            spin = dx * 0.3;
            lastX = e.clientX;
            setRot(getRot() + dx * 0.3);
            wake();
            if (Math.abs(dx) > 5) this.suppressClick = true;
        };

        const onUp = () => {
            dragging = false;
            this._dragging = false;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            setTimeout(() => { this.suppressClick = false; }, 50);
            if (rafId !== null) cancelAnimationFrame(rafId);
            if (Math.abs(velocity) > 0.05) rafId = requestAnimationFrame(inertia);
            else { rafId = null; spin = 0; snapToCard(); }
            wake();
        };

        container.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            if (this._deck[deckName] && this._deck[deckName].open) return;   // 摊开子卡时不转轨道
            dragging = true;
            this._dragging = true;
            lastX = e.clientX;
            velocity = 0;
            spin = 0;
            if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
            this.suppressClick = false;
            wake();
            e.preventDefault();
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    },

    /** 吸附看门狗：滚轮 / 拖动 / 惯性 / 按键，任何来源停下后都吸到最近的卡正对观众 */
    _startSnapLoop() {
        let last = this.rotation;
        let still = 0;
        const tick = () => {
            // 手还按着就绝不吸附。旧逻辑只看"12 帧内变化 < 0.08°"，
            // 慢速拖动（< 4.8°/秒）会被误判成已停下 → 鼠标没松轨道就被抢去吸附，
            // 一圈 13 张 → 整轨自己跳 27.7° 的整数倍。
            if (this._dragging) {
                last = this.launcherOpen ? this.launcherRotation : this.rotation;
                still = 0;
                requestAnimationFrame(tick);
                return;
            }
            const launcher = this.launcherOpen;
            const now = launcher ? this.launcherRotation : this.rotation;
            if (Math.abs(now - last) > 0.08) {
                last = now;
                still = 0;
            } else {
                still++;
                if (still === 12) {
                    const n = launcher ? (this.launchEls || []).length
                                       : ((this._deck.outer && this._deck.outer.els) ? this._deck.outer.els.length : 0);
                    const stepDeg = n ? 360 / n : 0;
                    if (stepDeg) {
                        const goal = 90 + Math.round((now - 90) / stepDeg) * stepDeg;
                        this._setAnim(false);
                        const apply = (v) => {
                            if (launcher) { this.launcherRotation = v; this._syncLauncher(); return; }
                            this.rotation = v;
                            const d = this._deck.outer;
                            if (d) d.els.forEach(el => { if (el !== d.parent) d.restore(el); });
                        };
                        const ease = () => {
                            const cur = launcher ? this.launcherRotation : this.rotation;
                            const diff = goal - cur;
                            // 同 snapToCard：这里不许恢复 .anim，否则会在"还在每帧写 transform"的时候
                            // 打开 transform 弹簧过渡 → 半径/大小被弹簧插值 → 看着像在收缩。
                            if (Math.abs(diff) < 0.2) { apply(goal); this._setAnim(true); return; }
                            apply(cur + diff * 0.2);
                            requestAnimationFrame(ease);
                        };
                        requestAnimationFrame(ease);
                    }
                }
            }
            requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
    },

    bindDragRotation() {
        // 绑在整个轨道容器上（而不是只绑 .orbit-outer）：
        // 启动卡在 #launcherCluster 里、属于 .orbit-outer 的兄弟节点，
        // 只绑 .orbit-outer 的话 mousedown 落在启动卡上不会触发，转不动。
        // 启动轨道展开时转启动轨道，否则转外环配置轨道。
        this._bindDrag(document.getElementById('orbitSystem'), 'outer',
                       () => (this.launcherOpen ? this.launcherRotation : this.rotation),
                       (v) => { if (this.launcherOpen) this.launcherRotation = v; else this.rotation = v; });
    }
});