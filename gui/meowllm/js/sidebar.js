/**
 * MeowLLM 配置页 —— 侧边栏
 *
 * 侧边栏是这套配置的主导航：
 *   状态与自检 | 服务与连接 | 引擎·DualStream | 上下文与生成
 *   | 记忆·δ-mem | 记忆·落盘与隔离 | 缓存·队列·路径 | 安全闸
 *
 * 「引擎·DualStream」和「记忆·δ-mem」是两条独立的线，刻意分开放：
 * 一个是「怎么算」，一个是「记住谁」，混在一起最容易配错。
 */

const MLSidebar = {
  /** @param {Array} schema 参数表 @param {string} activeId 当前区 */
  render(schema, activeId) {
    const items = [{
      id: 'status', icon: '🔎', title: '状态与自检', desc: '实时探测 / 试写记忆',
    }].concat(schema.map((sec) => ({
      id: sec.id, icon: sec.icon, title: sec.title,
    })));

    const nav = items.map((item) => {
      const active = item.id === activeId ? ' mll-nav-active' : '';
      return `<button type="button" class="mll-nav${active}" data-goto="${item.id}">
          <span class="mll-nav-icon">${item.icon || '•'}</span>
          <span class="mll-nav-title">${MLFields.esc(item.title)}</span>
        </button>`;
    }).join('');

    return `<div class="mll-brand">
        <div class="mll-brand-title">MeowLLM</div>
        <div class="mll-brand-sub">本地推理子服务配置</div>
      </div>
      <nav class="mll-navs">${nav}</nav>
      <div class="mll-side-foot">
        <div class="mll-dirty" id="mllDirty" hidden>● 有未保存的改动</div>
        <button type="button" class="mll-side-btn" id="mllSaveSide">保存配置</button>
      </div>`;
  },

  /** 绑定导航点击（回调交给 app.js 处理切换） */
  bind(root, onGoto) {
    root.querySelectorAll('[data-goto]').forEach((btn) => {
      btn.addEventListener('click', () => onGoto(btn.dataset.goto));
    });
  },
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { MLSidebar };
}
