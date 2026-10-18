/**
 * MeowLLM 配置页 —— 编排
 *
 * 职责：拉配置 → 渲染（侧边栏 + 全部配置区，非当前区只隐藏不卸载）→
 *       收集改动 → 保存 → 重渲染。
 *
 * 为什么「全部渲染、只隐藏」：collect() 要一次拿到所有区的值。
 * 如果切区时销毁 DOM，保存就只能保存当前区，用户切来切去会丢改动。
 * 70 来个字段全渲染没有性能问题。
 */

const MLApp = {
  config: {},
  cfgPath: '',
  current: 'status',
  dirty: false,

  els: {},

  async boot() {
    this.els = {
      side: document.getElementById('mllSide'),
      body: document.getElementById('mllBody'),
      path: document.getElementById('mllPath'),
      status: document.getElementById('mllStatus'),
      save: document.getElementById('mllSave'),
      reload: document.getElementById('mllReload'),
    };

    this.els.save?.addEventListener('click', () => this.save());
    this.els.reload?.addEventListener('click', () => this.load(true));
    window.addEventListener('beforeunload', (ev) => {
      if (!this.dirty) return undefined;
      ev.preventDefault();
      ev.returnValue = '有未保存的改动';
      return ev.returnValue;
    });

    this.bindDirtyTracker();
    await this.load(false);
  },

  /* ------------------------------------------------------------ 加载 */
  async load(force) {
    this.setStatus('读取中…', '');
    try {
      const res = await MLApi.getConfig();
      this.config = res.data || {};
      this.cfgPath = res.path || '';
      if (this.els.path) this.els.path.textContent = this.cfgPath;
      const hash = String(location.hash || '').replace('#', '');
      const known = ['status'].concat(MLL_SCHEMA.map((s) => s.id));
      this.current = known.includes(hash) ? hash : this.current;
      if (!known.includes(this.current)) this.current = 'status';
      this.render();
      this.markDirty(false);
      this.setStatus(force ? '已重新读取' : '', '');
    } catch (e) {
      this.setStatus(`读取失败：${e.message}`, 'err');
      if (this.els.body) {
        this.els.body.innerHTML = `<div class="mll-error-box">
            <b>读不到配置</b>
            <div>${MLFields.esc(e.message)}</div>
            <div class="mll-dim">确认主项目配置服务（config_gui.py）在跑，
            并且 .vendor/.MeowLLM/config.yml 存在。</div>
          </div>`;
      }
    }
  },

  /* ------------------------------------------------------------ 渲染 */
  render() {
    if (this.els.side) {
      this.els.side.innerHTML = MLSidebar.render(MLL_SCHEMA, this.current);
      MLSidebar.bind(this.els.side, (id) => this.goto(id));
      document.getElementById('mllSaveSide')?.addEventListener('click', () => this.save());
    }
    if (!this.els.body) return;

    const blocks = [MLPanels.renderStatus(this.config)]
      .concat(MLL_SCHEMA.map((sec) => MLPanels.renderSection(sec, this.config)));
    this.els.body.innerHTML = blocks.join('');

    MLPanels.bindStatus(this.els.body);
    this.bindDirtyTracker();
    this.goto(this.current, true);
  },

  goto(id, silent) {
    this.current = id;
    document.querySelectorAll('.mll-section').forEach((sec) => {
      sec.classList.toggle('mll-hidden', sec.dataset.section !== id);
    });
    document.querySelectorAll('[data-goto]').forEach((btn) => {
      btn.classList.toggle('mll-nav-active', btn.dataset.goto === id);
    });
    if (!silent) history.replaceState(null, '', `#${id}`);
    const main = document.querySelector('.mll-main');
    if (main && !silent) main.scrollTop = 0;
  },

  /* ------------------------------------------------------ 脏状态跟踪 */
  bindDirtyTracker() {
    this.els.body?.querySelectorAll('[data-path]').forEach((el) => {
      if (el.dataset.mllBound) return;
      el.dataset.mllBound = '1';
      el.addEventListener('input', () => this.markDirty(true));
      el.addEventListener('change', () => {
        this.markDirty(true);
        if (el.type === 'checkbox') {
          const text = el.closest('.mll-switch')?.querySelector('.mll-switch-text');
          if (text) text.textContent = el.checked ? '开启' : '关闭';
        }
      });
    });
  },

  markDirty(flag) {
    this.dirty = flag;
    const box = document.getElementById('mllDirty');
    if (box) box.hidden = !flag;
  },

  /* ------------------------------------------------------------ 收集 */
  collect() {
    const next = JSON.parse(JSON.stringify(this.config || {}));
    const skipped = [];
    this.els.body?.querySelectorAll('[data-path]').forEach((el) => {
      const path = el.dataset.path;
      const field = MLApp.findField(path);
      if (!field) return;
      const value = MLFields.valueOf(el, field);
      if (value === undefined) {
        skipped.push(path);
        return;
      }
      MLFields.write(next, path, value);
    });
    return { next, skipped };
  },

  findField(path) {
    for (const sec of MLL_SCHEMA) {
      for (const group of sec.groups || []) {
        for (const field of group.fields || []) {
          if (field.path === path) return field;
        }
      }
    }
    return null;
  },

  /* ------------------------------------------------------------ 保存 */
  async save() {
    const { next, skipped } = this.collect();
    this.setStatus('保存中…', '');
    if (this.els.save) this.els.save.disabled = true;
    try {
      const res = await MLApi.saveConfig(next);
      this.config = res.data || next;
      this.render();
      this.markDirty(false);
      const tail = skipped.length ? `（${skipped.length} 个数字框留空，保持原值）` : '';
      this.setStatus(`已保存${tail}；引擎 / δ-mem 结构参数需重启 MeowLLM 生效`, 'ok');
    } catch (e) {
      this.setStatus(`保存失败：${e.message}`, 'err');
    } finally {
      if (this.els.save) this.els.save.disabled = false;
    }
  },

  setStatus(text, kind) {
    if (!this.els.status) return;
    this.els.status.textContent = text;
    this.els.status.className = `mll-status${kind ? ` mll-status-${kind}` : ''}`;
  },
};

document.addEventListener('DOMContentLoaded', () => MLApp.boot());
