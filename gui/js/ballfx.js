/* =========================================================
   中心启动球：3D 指针跟随 + 球面高光
   ---------------------------------------------------------
   卡片那套压感（js/press.js）动的是 .card-press 那一层，
   中心球是独立元素，所以单独一小份：只写三个自定义属性，
   真正的 3D/高光全在 css/style.css 的 .center-launcher / .launcher-glare 里。

   为什么要自己插值（而不是 CSS transition）：
     指针事件频率跟帧率不同步，直接把角度写成 --lx/--ly 会一顿一顿；
     这里用固定系数的弹簧（每帧向目标靠 18%），松手后自己收敛到 0，
     收敛到足够小就停掉 rAF，静止时零开销。

   和轨道转动的关系：球本身不被轨道改写 transform（轨道只写 .slot 的），
   所以这里可以放心独占 .center-launcher 的 transform。
   ========================================================= */
(function () {
    'use strict';

    var MAX_TILT = 16;      // 最大倾角（度）
    var EASE = 0.18;        // 每帧向目标靠近的比例
    var EPS = 0.02;         // 足够小就吸附并停帧

    var el = document.getElementById('centerLauncher');
    if (!el) return;

    var tx = 0, ty = 0;     // 目标角度
    var cx = 0, cy = 0;     // 当前角度
    var rafId = 0;
    var rect = null;        // 缓存矩形：pointermove 里不再每次量（会强制重算样式）

    function write() {
        el.style.setProperty('--lx', cx.toFixed(2) + 'deg');
        el.style.setProperty('--ly', cy.toFixed(2) + 'deg');
        // 高光位置跟着倾斜方向走（最大值限制在球面内）
        el.style.setProperty('--gx', (50 + cx * 2.2).toFixed(1) + '%');
        el.style.setProperty('--gy', (50 - cy * 2.2).toFixed(1) + '%');
    }

    function tick() {
        rafId = 0;
        cx += (tx - cx) * EASE;
        cy += (ty - cy) * EASE;
        if (Math.abs(tx - cx) < EPS && Math.abs(ty - cy) < EPS) {
            cx = tx;
            cy = ty;
            write();
            return;                    // 收敛完成，不再排帧
        }
        write();
        rafId = requestAnimationFrame(tick);
    }

    function kick() {
        if (!rafId) rafId = requestAnimationFrame(tick);
    }

    el.addEventListener('pointerenter', function () {
        rect = el.getBoundingClientRect();
    });

    el.addEventListener('pointermove', function (e) {
        if (!rect) rect = el.getBoundingClientRect();
        var px = (e.clientX - rect.left) / (rect.width || 1);
        var py = (e.clientY - rect.top) / (rect.height || 1);
        var nx = Math.max(-1, Math.min(1, (px - 0.5) * 2));
        var ny = Math.max(-1, Math.min(1, (py - 0.5) * 2));
        tx = nx * MAX_TILT;            // 左右 → rotateY
        ty = -ny * MAX_TILT;           // 上下 → rotateX（往下按 → 上边缘后仰）
        kick();
    });

    el.addEventListener('pointerleave', function () {
        rect = null;
        tx = 0;
        ty = 0;
        kick();
    });

    // 触摸屏没有 pointerleave 的可靠语义：抬手就回正
    el.addEventListener('pointerup', function () {
        tx = 0;
        ty = 0;
        kick();
    });
})();
