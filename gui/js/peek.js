/**
 * 右上角"看壁纸"按钮：点一下 → 主界面卡片整体下沉淡出，露出壁纸；再点一次恢复。
 *
 * 开销：只是切一个 body 类（peek-wall）。
 *   - 过渡只动 transform / opacity（合成层友好，不触发重排）；
 *   - 淡出后 visibility:hidden，浏览器整棵子树跳过绘制；
 *   - 同时暂停卡片的呼吸/涟漪动画（和 body.modal-open 同一套思路）。
 *   所以"看壁纸"期间比平时更省，不是更贵。
 *
 * 为什么不写内联 transform：orbit/rotation.js 的半径锁会盯住轨道容器的 style，
 * 而这里的下沉是纯 CSS 类（只影响绘制位置，不改任何半径）。
 */
(function () {
    'use strict';

    const BODY_CLASS = 'peek-wall';

    function init() {
        const btn = document.getElementById('peekBtn');
        if (!btn) return;

        const isOn = () => document.body.classList.contains(BODY_CLASS);

        const apply = (on) => {
            document.body.classList.toggle(BODY_CLASS, on);
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
            if (!on) return;
            // 卡片要藏起来了：别留一张"按下未弹起"的卡，也别留着半个待开的面板
            if (window.PressFx && PressFx.releaseAll) PressFx.releaseAll();
            if (window.Orbit && Orbit._cancelPending) Orbit._cancelPending();
        };

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            apply(!isOn());
        });

        // Esc 也能收回（配置面板的 Esc 关窗不受影响：这里只在"看壁纸"状态下接管）
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && isOn()) apply(false);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
