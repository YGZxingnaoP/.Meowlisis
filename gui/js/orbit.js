/**
 * Orbit system
 * - 中心启动球：点击展开/收起 3 个服务启动球
 * - 外层配置环：鼠标左键拖动旋转，球自身保持正立
 */
const Orbit = {
    // 中心球分裂出的服务启动球
    launcherPlanets: [
        { id: 'main', label: '主程序', tooltip: '启动主程序', endpoint: 'http://127.0.0.1:1800' },
        { id: 'sovits', label: 'SoVITS', tooltip: '启动 SoVITS 服务', endpoint: 'http://127.0.0.1:9880' },
        { id: 'sensevoice', label: 'SenseVoice', tooltip: '启动 SenseVoice 服务', endpoint: 'ws://127.0.0.1:10095' }
    ],

    // 外层配置节点（与 config.yml 节点对应）
    outerPlanets: [
        { id: 'basic', label: '基本', tooltip: '基础与 app 设置' },
        { id: 'character', label: '角色卡', tooltip: '角色卡配置' },
        { id: 'sensevoice', label: 'SenseVoice', tooltip: '语音识别配置' },
        { id: 'llm', label: 'LLM', tooltip: '大语言模型配置' },
        { id: 'active', label: '主动回复', tooltip: '角色主动回复配置' },
        { id: 'catbrain', label: 'CatBrain', tooltip: '角色灵魂配置' },
        { id: 'tts', label: 'TTS', tooltip: '语音合成与 SoVITS 配置' },
        { id: 'danmaku', label: 'BiliLive', tooltip: 'B站直播弹幕配置' },
        { id: 'toolbox', label: 'Toolbox', tooltip: '工具箱（Minecraft/OBS/VTS）' }
    ],

    // Toolbox 子视图外围行星球（父级模型中心球 + 三个工具球）
    toolboxPlanets: [
        { id: 'minecraft', label: 'Minecraft', tooltip: 'Minecraft 日志读取配置' },
        { id: 'obs', label: 'OBS', tooltip: 'OBS 字幕模块（占位）' },
        { id: 'vts', label: 'VTS', tooltip: 'VTuber / VTS 配置' }
    ],

    rotation: 0,
    outerPlanetEls: [],
    launcherPlanetEls: [],
    launcherOpen: false,
    catbrainSubEls: [],
    catbrainOpen: false,
    catbrainEl: null,
    dragging: false,
    suppressClick: false,
    toolboxRotation: 0,
    toolboxPlanetEls: [],

    init() {
        const orbitOuter = document.getElementById('orbitOuter');
        const cluster = document.getElementById('launcherCluster');

        if (!orbitOuter || !cluster) {
            console.error('Orbit elements not found');
            return;
        }

        // 创建外层配置环
        this.outerPlanets.forEach((p, i) => {
            const el = this.createOuterPlanet(p, i, this.outerPlanets.length);
            orbitOuter.appendChild(el);
            this.outerPlanetEls.push(el);
        });

        // 创建启动球
        this.launcherPlanets.forEach((p, i) => {
            const el = this.createLauncherPlanet(p, i);
            cluster.appendChild(el);
            this.launcherPlanetEls.push(el);
        });

        // 中心球点击切换展开
        const center = document.getElementById('centerLauncher');
        center.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleLauncher();
        });

        // 外层拖动
        this.bindDragRotation();

        // Toolbox 子视图
        this.initToolboxSub();

        console.log(`Created ${this.outerPlanets.length} config planets + ${this.launcherPlanets.length} launcher planets`);
    },

    // ============ Toolbox 子视图 ============
    initToolboxSub() {
        const orbit = document.getElementById('toolboxOrbit');
        if (!orbit) return;
        this.toolboxPlanetEls = [];
        this.toolboxPlanets.forEach((p, i) => {
            const el = this.createToolboxPlanet(p, i, this.toolboxPlanets.length);
            orbit.appendChild(el);
            this.toolboxPlanetEls.push(el);
        });
        const center = document.getElementById('toolboxCenter');
        if (center) {
            center.addEventListener('mousedown', (e) => e.stopPropagation());
            center.addEventListener('click', () => {
                if (window.App && typeof window.App.onToolboxPlanetClick === 'function') {
                    window.App.onToolboxPlanetClick('center');
                }
            });
        }
        this.bindToolboxDragRotation();
    },

    createToolboxPlanet(p, index, total) {
        const el = document.createElement('div');
        el.className = 'toolbox-planet';
        el.innerHTML = `<span class="planet-label">${p.label}</span>`;
        el.dataset.tooltip = p.tooltip;
        el.dataset.id = p.id;
        const baseAngle = (2 * Math.PI / total) * index - Math.PI / 2;
        el.dataset.baseAngle = baseAngle;
        this.updateToolboxPlanetPosition(el, 0);
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            if (this.suppressClick) return;
            if (window.App && typeof window.App.onToolboxPlanetClick === 'function') {
                window.App.onToolboxPlanetClick(p.id);
            }
        });
        return el;
    },

    updateToolboxPlanetPosition(el, rotationDeg) {
        const baseAngle = parseFloat(el.dataset.baseAngle);
        const currentAngle = baseAngle + (rotationDeg * Math.PI / 180);
        const radius = 300;
        const planetSize = 48;
        const x = radius + radius * Math.sin(currentAngle) - planetSize;
        const y = radius + radius * Math.cos(currentAngle) - planetSize;
        el.style.left = `${x}px`;
        el.style.top = `${y}px`;
        const depth = Math.cos(currentAngle);
        const scale = 0.65 + (depth + 1) / 2 * 0.55;
        el.style.transform = `scale(${scale}, ${scale * 2})`;
        el.style.zIndex = Math.round((depth + 1) * 50 + 5);
    },

    bindToolboxDragRotation() {
        const orbit = document.getElementById('toolboxSystem');
        if (!orbit) return;
        let dragging = false;
        let lastX = 0;
        let velocity = 0;
        let rafId = null;

        const applyRotation = (rot) => {
            this.toolboxRotation = rot;
            this.toolboxPlanetEls.forEach(el => {
                this.updateToolboxPlanetPosition(el, rot);
            });
        };

        const inertia = () => {
            this.toolboxRotation += velocity;
            velocity *= 0.92;
            applyRotation(this.toolboxRotation);
            if (Math.abs(velocity) < 0.05) {
                rafId = null;
                return;
            }
            rafId = requestAnimationFrame(inertia);
        };

        const onMove = (e) => {
            if (!dragging) return;
            const dx = e.clientX - lastX;
            velocity = dx * 0.35;
            lastX = e.clientX;
            this.toolboxRotation += dx * 0.3;
            applyRotation(this.toolboxRotation);
            if (Math.abs(dx) > 5) {
                this.suppressClick = true;
            }
        };

        const onUp = () => {
            dragging = false;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            setTimeout(() => { this.suppressClick = false; }, 50);
            if (rafId !== null) {
                cancelAnimationFrame(rafId);
            }
            if (Math.abs(velocity) > 0.05) {
                rafId = requestAnimationFrame(inertia);
            } else {
                rafId = null;
            }
        };

        orbit.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            dragging = true;
            lastX = e.clientX;
            velocity = 0;
            this.suppressClick = false;
            if (rafId !== null) {
                cancelAnimationFrame(rafId);
                rafId = null;
            }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    },

    // ============ 启动球 ============
    createLauncherPlanet(p, index) {
        const el = document.createElement('div');
        el.className = 'launch-planet';
        el.innerHTML = `<span class="launch-label">${p.label}</span>`;
        el.dataset.tooltip = `${p.tooltip}：${p.endpoint}`;
        el.dataset.launchId = p.id;

        // 目标偏移（相对中心，沿主球右侧弧线排列，稍远）
        const offsets = [
            { x: 185, y: 92 },     // main 右上
            { x: 215, y: 0 },      // sovits 正右
            { x: 185, y: -92 }     // sensevoice 右下
        ];
        el.dataset.offsetX = offsets[index].x;
        el.dataset.offsetY = offsets[index].y;

        this._applyLauncherPosition(el, false);

        el.addEventListener('click', (e) => {
            e.stopPropagation();
            if (this.suppressClick) return;
            if (window.App && typeof window.App.onLaunchClick === 'function') {
                window.App.onLaunchClick(p.id);
            }
        });

        return el;
    },

    _applyLauncherPosition(el, open) {
        const x = parseFloat(el.dataset.offsetX);
        const y = parseFloat(el.dataset.offsetY);
        if (open) {
            // 展开：从中心滑出到弧线位置并放大（带回弹）
            el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px) scale(1)`;
            el.style.opacity = '1';
            el.style.pointerEvents = 'auto';
        } else {
            // 收回：从弧线位置滑回中心并缩小
            el.style.transform = `translate(-50%, -50%) translate(0px, 0px) scale(0)`;
            el.style.opacity = '0';
            el.style.pointerEvents = 'none';
        }
    },

    toggleLauncher() {
        this.launcherOpen = !this.launcherOpen;
        const center = document.getElementById('centerLauncher');
        center.classList.toggle('active', this.launcherOpen);
        this.launcherPlanetEls.forEach(el => this._applyLauncherPosition(el, this.launcherOpen));
    },

    // ============ 外层配置环 ============
    createOuterPlanet(p, index, total) {
        const el = document.createElement('div');
        el.className = `planet planet-outer`;
        el.innerHTML = `<span class="planet-label">${p.label}</span>`;
        el.dataset.tooltip = p.tooltip;
        el.dataset.id = p.id;

        const baseAngle = (2 * Math.PI / total) * index - Math.PI / 2;
        el.dataset.baseAngle = baseAngle;

        this.updateOuterPlanetPosition(el, 0);

        if (p.id === 'catbrain') {
            // CatBrain 球：点击分裂出 4 个子配置球
            this.catbrainEl = el;
            this.createCatbrainSubs(el);
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                if (this.suppressClick) return;
                this.toggleCatbrainSubs();
            });
        } else {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                if (this.suppressClick) return;
                if (window.App && typeof window.App.onPlanetClick === 'function') {
                    window.App.onPlanetClick(p.id);
                }
            });
        }

        return el;
    },

    // CatBrain 子球（长期记忆/记忆摘要/价值观/用户记忆）
    createCatbrainSubs(parent) {
        const subs = [
            { id: 'ltmem', label: '长期记忆', tooltip: '长期记忆配置' },
            { id: 'abstract', label: '记忆摘要', tooltip: '记忆摘要配置' },
            { id: 'values', label: '价值观', tooltip: '价值观配置' },
            { id: 'usermem', label: '用户记忆', tooltip: '用户记忆配置' }
        ];
        // 目标偏移：4 个子球沿 CatBrain 球右侧弧线排列
        const offsets = [
            { x: 82, y: -82 },    // ltmem 右上
            { x: 115, y: -27 },   // abstract 右中上
            { x: 115, y: 27 },    // values 右中下
            { x: 82, y: 82 }      // usermem 右下
        ];
        this.catbrainSubEls = [];
        subs.forEach((s, i) => {
            const el = document.createElement('div');
            el.className = 'catbrain-sub';
            el.innerHTML = `<span class="launch-label">${s.label}</span>`;
            el.dataset.tooltip = s.tooltip;
            el.dataset.subId = s.id;
            el.dataset.offsetX = offsets[i].x;
            el.dataset.offsetY = offsets[i].y;
            this._applyCatbrainSub(el, false);
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                if (this.suppressClick) return;
                if (window.App && typeof window.App.onPlanetClick === 'function') {
                    window.App.onPlanetClick(s.id);
                }
            });
            parent.appendChild(el);
            this.catbrainSubEls.push(el);
        });
    },

    _applyCatbrainSub(el, open) {
        const x = parseFloat(el.dataset.offsetX);
        const y = parseFloat(el.dataset.offsetY);
        if (open) {
            el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px) scale(1)`;
            el.style.opacity = '1';
            el.style.pointerEvents = 'auto';
        } else {
            el.style.transform = `translate(-50%, -50%) translate(0px, 0px) scale(0)`;
            el.style.opacity = '0';
            el.style.pointerEvents = 'none';
        }
    },

    toggleCatbrainSubs() {
        this.catbrainOpen = !this.catbrainOpen;
        if (this.catbrainEl) {
            this.catbrainEl.classList.toggle('active', this.catbrainOpen);
        }
        this.catbrainSubEls.forEach(el => this._applyCatbrainSub(el, this.catbrainOpen));
    },


    updateOuterPlanetPosition(el, rotationDeg) {
        const baseAngle = parseFloat(el.dataset.baseAngle);
        const currentAngle = baseAngle + (rotationDeg * Math.PI / 180);

        const radius = 600;
        const planetSize = 50;

        const x = radius + radius * Math.sin(currentAngle) - planetSize;
        const y = radius + radius * Math.cos(currentAngle) - planetSize;

        el.style.left = `${x}px`;
        el.style.top = `${y}px`;

        const depth = Math.cos(currentAngle);
        const scale = 0.65 + (depth + 1) / 2 * 0.55;
        el.style.transform = `scale(${scale}, ${scale * 2})`;
        el.style.zIndex = Math.round((depth + 1) * 50 + 5);
    },

    // ============ 鼠标左键拖动（带轻微惯性） ============
    bindDragRotation() {
        const outer = document.getElementById('orbitOuter');
        let dragging = false;
        let lastX = 0;
        let velocity = 0;
        let rafId = null;

        const applyRotation = (rot) => {
            this.rotation = rot;
            this.outerPlanetEls.forEach(el => {
                this.updateOuterPlanetPosition(el, rot);
            });
        };

        const inertia = () => {
            this.rotation += velocity;
            velocity *= 0.92; // 惯性衰减（较快，惯性不大）
            applyRotation(this.rotation);

            if (Math.abs(velocity) < 0.05) {
                rafId = null;
                return;
            }
            rafId = requestAnimationFrame(inertia);
        };

        const onMove = (e) => {
            if (!dragging) return;
            const dx = e.clientX - lastX;
            velocity = dx * 0.35; // 记录即时速度，作为惯性初速度
            lastX = e.clientX;

            this.rotation += dx * 0.3;
            applyRotation(this.rotation);

            if (Math.abs(dx) > 5) {
                this.suppressClick = true;
            }
        };

        const onUp = () => {
            dragging = false;
            this.dragging = false;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);

            // 延迟清除抑制，避免拖动结束的 click 被误触
            setTimeout(() => { this.suppressClick = false; }, 50);

            // 松手后按惯性继续滚动
            if (rafId !== null) {
                cancelAnimationFrame(rafId);
            }
            if (Math.abs(velocity) > 0.05) {
                rafId = requestAnimationFrame(inertia);
            } else {
                rafId = null;
            }
        };

        outer.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return; // 仅左键
            dragging = true;
            this.dragging = true;
            lastX = e.clientX;
            velocity = 0;
            this.suppressClick = false;

            if (rafId !== null) {
                cancelAnimationFrame(rafId);
                rafId = null;
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }
};
