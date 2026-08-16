/**
 * Orbit animation and planet positioning
 * 外层行星：位置随滚轮绕圈，但自身保持正立不旋转
 */
const Orbit = {
    innerPlanets: [
        { id: 'llm', label: 'LLM', tooltip: '大语言模型配置', type: 'inner' },
        { id: 'sovits', label: 'SoVITS', tooltip: 'SoVITS 语音合成', type: 'sovits' },
        { id: 'sensevoice', label: 'SenseVoice', tooltip: '语音识别配置', type: 'inner' }
    ],

    outerPlanets: [
        { id: 'basic', label: '基本', tooltip: '基本设置', type: 'outer' },
        { id: 'obs', label: 'OBS', tooltip: 'OBS 服务设置', type: 'outer' },
        { id: 'vtuber', label: 'VTuber', tooltip: 'VTuber 设置', type: 'outer' },
        { id: 'minecraft', label: 'Minecraft', tooltip: 'Minecraft 设置', type: 'outer' },
        { id: 'tts', label: 'TTS', tooltip: 'TTS 设置', type: 'outer' }
    ],

    rotation: 0,
    outerPlanetEls: [],
    innerPlanetEls: [],
    innerRotation: 0,
    innerRafId: null,

    init() {
        const orbitInner = document.getElementById('orbitInner');
        const orbitOuter = document.getElementById('orbitOuter');
        
        if (!orbitInner || !orbitOuter) {
            console.error('Orbit elements not found');
            return;
        }

        console.log('Initializing orbit system...');
        
        // 创建内层行星（缓慢自动旋转）
        this.innerPlanets.forEach((p, i) => {
            const el = this.createInnerPlanet(p, i, this.innerPlanets.length);
            orbitInner.appendChild(el);
            this.innerPlanetEls.push(el);
        });

        // 创建外层行星（滚轮控制绕圈，但自身不旋转）
        this.outerPlanets.forEach((p, i) => {
            const el = this.createOuterPlanet(p, i, this.outerPlanets.length);
            orbitOuter.appendChild(el);
            this.outerPlanetEls.push(el);
        });

        // 绑定滚轮旋转
        this.bindWheelRotation();

        // 启动内层缓慢旋转
        this.startInnerRotation();

        console.log(`Created ${this.innerPlanets.length + this.outerPlanets.length} planets`);
    },

    createInnerPlanet(p, index, total) {
        const el = document.createElement('div');
        const cls = p.type === 'sovits' ? 'planet-sovits' : 'planet-inner';
        el.className = `planet ${cls}`;
        el.innerHTML = `<span class="planet-label">${p.label}</span>`;
        el.dataset.tooltip = p.tooltip;
        el.dataset.id = p.id;

        // 保存基础角度用于旋转
        const baseAngle = (2 * Math.PI / total) * index - Math.PI / 2;
        el.dataset.baseAngle = baseAngle;
        
        // 初始位置
        this.updateInnerPlanetPosition(el, 0);

        el.addEventListener('click', (e) => {
            e.stopPropagation();
            if (window.App && typeof window.App.onPlanetClick === 'function') {
                window.App.onPlanetClick(p.id);
            }
        });

        return el;
    },

    updateInnerPlanetPosition(el, rotationDeg) {
        const baseAngle = parseFloat(el.dataset.baseAngle);
        const currentAngle = baseAngle + (rotationDeg * Math.PI / 180);
        
        const radius = 250; // 500px / 2
        const planetSize = 60; // 120px / 2
        
        const x = radius + radius * Math.sin(currentAngle) - planetSize;
        const y = radius + radius * Math.cos(currentAngle) - planetSize;
        
        el.style.left = `${x}px`;
        el.style.top = `${y}px`;
    },

    startInnerRotation() {
        const rotate = () => {
            this.innerRotation += 0.08; // 缓慢旋转速度
            
            this.innerPlanetEls.forEach(el => {
                this.updateInnerPlanetPosition(el, this.innerRotation);
            });
            
            requestAnimationFrame(rotate);
        };
        
        requestAnimationFrame(rotate);
    },

    createOuterPlanet(p, index, total) {
        const el = document.createElement('div');
        el.className = `planet planet-outer`;
        el.innerHTML = `<span class="planet-label">${p.label}</span>`;
        el.dataset.tooltip = p.tooltip;
        el.dataset.id = p.id;

        // 计算初始角度
        const baseAngle = (2 * Math.PI / total) * index - Math.PI / 2;
        
        // 保存数据用于滚轮旋转
        el.dataset.baseAngle = baseAngle;

        // 初始位置
        this.updateOuterPlanetPosition(el, 0);

        el.addEventListener('click', (e) => {
            e.stopPropagation();
            if (window.App && typeof window.App.onPlanetClick === 'function') {
                window.App.onPlanetClick(p.id);
            }
        });

        return el;
    },

    updateOuterPlanetPosition(el, rotationDeg) {
        const baseAngle = parseFloat(el.dataset.baseAngle);
        const currentAngle = baseAngle + (rotationDeg * Math.PI / 180);
        
        const radius = 600; // 1200px / 2
        const planetSize = 50; // 100px / 2
        
        const x = radius + radius * Math.sin(currentAngle) - planetSize;
        const y = radius + radius * Math.cos(currentAngle) - planetSize;
        
        el.style.left = `${x}px`;
        el.style.top = `${y}px`;
        
        // 近大远小：根据球在轨道前后位置计算缩放
        const depth = Math.cos(currentAngle); // -1 ~ 1
        const scale = 0.65 + (depth + 1) / 2 * 0.55; // 0.65 ~ 1.2
        
        // 球自身固定不动，不旋转，只改变位置和大小
        el.style.transform = `scale(${scale}, ${scale * 2})`;
        
        // 前方在上，后方在下
        el.style.zIndex = Math.round((depth + 1) * 50 + 5);
    },

    bindWheelRotation() {
        let rotation = 0;
        let velocity = 0;
        let rafId = null;

        const animate = () => {
            // 应用惯性
            rotation += velocity;
            velocity *= 0.90; // 摩擦衰减更快，惯性更小

            // 当速度足够小时停止动画
            if (Math.abs(velocity) < 0.01) {
                rafId = null;
                this.rotation = rotation;
                return;
            }

            this.rotation = rotation;

            // 更新所有外层行星位置
            this.outerPlanetEls.forEach(el => {
                this.updateOuterPlanetPosition(el, rotation);
            });

            rafId = requestAnimationFrame(animate);
        };

        document.addEventListener('wheel', (e) => {
            e.preventDefault();
            
            // 滚轮增加速度（惯性脉冲）
            const delta = e.deltaY > 0 ? 3 : -3;
            velocity += delta;

            if (rafId === null) {
                rafId = requestAnimationFrame(animate);
            }
        }, { passive: false });
    }
};
