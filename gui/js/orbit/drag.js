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
        let rafId = null;    // 惯性 / 吸附的逐帧推进句柄
        let tickId = null;   // 唯一的"逐帧写 transform"循环句柄

        const place = () => {
            // 启动轨道展开时，拖空白转的是启动轨道（外环此时是暗的，转了也看不见）
            if (deckName === 'outer' && this.launcherOpen) { this._syncLauncher(); return; }
            const d = this._deck[deckName];
            if (!d) return;
            const r0 = d.radius[0], r1 = d.radius[1];
            // ⚠️ 摊开子卡时父卡正被 .slot.focus 送往屏幕正中，不能被这里摆回轨道位
            d.els.forEach(el => { if (el === d.parent) return; this._place(el, el._ang, getRot(), r0, r1); });
        };

        // 逐帧重摆：拖动 / 惯性 / 吸附三项都停下后【自己退出】，不再空转 60fps。
        // .anim（过渡）只在这个循环真正停止写入之后才恢复 —— 否则每帧的新目标会被过渡插值，
        // 肉眼就是"卡片缩一下再弹回来"。
        const tick = () => {
            tickId = null;
            place();
            if (!dragging && rafId === null) { this._setAnim(true); return; }
            tickId = requestAnimationFrame(tick);
        };

        const wake = () => {
            if (tickId === null) {
                this._setAnim(false);
                tickId = requestAnimationFrame(tick);
            }
        };

        const inertia = () => {
            rafId = null;
            setRot(getRot() + velocity);
            velocity *= 0.92;          // 惯性衰减
            if (Math.abs(velocity) < 0.05) { velocity = 0; snapToCard(); return; }
            rafId = requestAnimationFrame(inertia);
            wake();
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
            if (!stepDeg) { rafId = null; wake(); return; }
            const goal = 90 + Math.round((getRot() - 90) / stepDeg) * stepDeg;
            const step = () => {
                rafId = null;
                if (dragging) { wake(); return; }
                const now = getRot();
                const diff = goal - now;
                // ⚠️ 这里【绝对不能】调 this._setAnim(true)：
                //    吸附期间还在每帧写 transform，早期 .anim 带 transform 弹簧过渡 →
                //    每帧都在追一个 0.5s 的目标 → 看着像"卡片缩一下再弹回来"。
                //    收尾统一交给 tick（它只在真正停止写入之后才恢复 .anim）。
                //    也不会留下 .rotating：tick 退出时会自己 _setAnim(true)。
                if (Math.abs(diff) < 0.2) { setRot(goal); wake(); return; }
                setRot(now + diff * 0.22);
                rafId = requestAnimationFrame(step);
                wake();
            };
            rafId = requestAnimationFrame(step);
            wake();
        };

        const onMove = (e) => {
            if (!dragging) return;
            const dx = e.clientX - lastX;
            velocity = dx * 0.35;
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
            if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
            if (Math.abs(velocity) > 0.05) { rafId = requestAnimationFrame(inertia); wake(); }
            else { velocity = 0; snapToCard(); }
        };

        container.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            if (this._deck[deckName] && this._deck[deckName].open) return;   // 摊开子卡时不转轨道
            dragging = true;
            this._dragging = true;
            lastX = e.clientX;
            velocity = 0;
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