/**
 * MeowLLM 配置页 —— 页面装配与状态面板
 *
 * 两个渲染入口：
 *   MLPanels.renderSection(section, config)  → 普通配置区（schema 驱动）
 *   MLPanels.renderStatus(config)            → 状态区（实时探测 + δ-mem 试写）
 *
 * 这个文件只管「把 HTML 拼出来并绑事件」，不发任何请求；
 * 请求都在 api.js，编排在 app.js。
 */

const MLPanels = {
  /** 哪些区/字段改了必须重启进程才生效 */
  _needsRestart(sectionId, path) {
    if (sectionId === 'dualstream') return true;
    if (sectionId === 'safety') return true;
    return /^(memory\.delta_mem\.(weights|rank|n_states|chunk|layers|alpha|calibrate_on_load|layout|userinfo_dir|state_dir))$/.test(path);
  },

  /* ------------------------------------------------------ 普通配置区 */
  renderSection(section, config) {
    const head = `<div class="mll-sec-head">
        <h2><span class="mll-sec-icon">${section.icon || '•'}</span>${MLFields.esc(section.title)}</h2>
        ${section.desc ? `<p class="mll-sec-desc">${MLFields.esc(section.desc)}</p>` : ''}
      </div>`;

    const groups = (section.groups || []).map((group) => {
      const fields = (group.fields || []).map((field) => {
        const prepared = MLPanels._needsRestart(section.id, field.path)
          ? Object.assign({}, field, { restart: true })
          : field;
        return MLFields.render(prepared, MLFields.read(config, field.path));
      }).join('');
      return `<div class="mll-card">
          <h3>${MLFields.esc(group.title)}</h3>
          ${fields}
        </div>`;
    }).join('');

    return `<div class="mll-section" data-section="${section.id}">${head}${groups}</div>`;
  },

  /* ---------------------------------------------------------- 状态区 */
  renderStatus(config) {
    const dmem = MLFields.read(config, 'memory.delta_mem') || {};
    const kind = MLFields.read(config, 'engine.kind') || '?';
    const port = MLFields.read(config, 'server.port') ?? '?';
    const weights = dmem.weights || '(未填)';
    const onOff = dmem.enabled ? '<b class="mll-ok">已开启</b>' : '<b class="mll-warn">已关闭</b>';

    return `<div class="mll-section" data-section="status">
      <div class="mll-sec-head">
        <h2><span class="mll-sec-icon">🔎</span>状态与自检</h2>
        <p class="mll-sec-desc">只读信息 + 一个刷新按钮。这些都不进 config.yml。
        子服务没起来时这里会显示「未连接」，属于正常（先把 MeowLLM 启动起来再看）。</p>
      </div>

      <div class="mll-card">
        <h3>配置文件</h3>
        <div class="mll-kv">
          <div><span>引擎</span><code>${MLFields.esc(kind)}</code></div>
          <div><span>端口</span><code>${MLFields.esc(port)}</code></div>
          <div><span>δ-mem</span><code>${onOff}</code></div>
          <div><span>权重</span><code>${MLFields.esc(weights)}</code></div>
        </div>
      </div>

      <div class="mll-card">
        <h3>子服务实时状态 <button type="button" class="mll-mini" id="mllProbe">刷新</button></h3>
        <div id="mllProbeOut" class="mll-probe">
          <span class="mll-dim">点「刷新」探测 127.0.0.1 上的 MeowLLM。</span>
        </div>
        <div class="mll-row-btns">
          <button type="button" class="mll-mini" id="mllReloadCfg">让子服务重载配置</button>
          <span class="mll-dim">只重载生成/思考/缓存这类热参数；引擎与端口仍需重启。</span>
        </div>
      </div>
    </div>`;
  },

  /* ------------------------------------------------------ 状态区事件 */
  bindStatus(root) {
    const out = root.querySelector('#mllProbeOut');

    const setOut = (html, cls) => {
      if (!out) return;
      out.className = `mll-probe ${cls || ''}`;
      out.innerHTML = html;
    };

    const probe = async () => {
      setOut('<span class="mll-dim">探测中…</span>');
      const [health, dmem] = await Promise.all([
        MLApi.controlGet('health').catch((e) => ({ __err: e.message })),
        MLApi.controlGet('dmem/status').catch((e) => ({ __err: e.message })),
      ]);
      const failed = health.__err || dmem.__err;
      if (failed) {
        setOut(`<b class="mll-warn">未连接</b> <span class="mll-dim">${MLFields.esc(failed)}</span>`
          + '<div class="mll-dim">子服务没起来：先跑 .vendor/.MeowLLM/start.bat</div>', 'mll-err');
        return;
      }
      const info = health.engine || {};
      const rows = [
        ['引擎', info.engine || '?'],
        ['权重已加载', info.loaded ? '是' : '否'],
        ['模型', `${info.model || '?'}（${info.params_b ?? '?'}B，${info.device || '?'}）`],
        ['模式', info.mode || '?'],
        ['服务运行', `${health.uptime_s ?? '?'}s`],
        ['版本', health.version || '?'],
        ['δ-mem', dmem.enabled ? '已挂载' : `未挂载（${dmem.reason || '?'}）`],
      ];
      if (dmem.enabled && dmem.params) {
        rows.push(['δ-mem 参数',
          `${((dmem.params.delta_mem_params || 0) / 1e6).toFixed(2)}M（${((dmem.params.ratio || 0) * 100).toFixed(3)}%）`]);
      }
      if (dmem.enabled && dmem.registry) {
        const reg = dmem.registry;
        rows.push(['存储布局', `${reg.layout || '?'} → ${reg.root || '?'}`]);
        rows.push(['当前 owner', reg.current || '（无）']);
        rows.push(['常驻用户',
          `${(reg.owners_cached || []).length} / ${reg.max_cached ?? '?'}`
          + ((reg.evictions || 0) > 0 ? `（已淘汰 ${reg.evictions}）` : '')]);
        rows.push(['每个状态', reg.state_kb_per_owner == null ? '—' : `${reg.state_kb_per_owner} KB`]);
        rows.push(['累计写入', `${reg.writes ?? 0} 次，平均 ${reg.write_ms_avg ?? 0} ms`]);
      }
      if (dmem.enabled && dmem.params && dmem.params.layers != null) {
        rows.push(['挂载层数', `${dmem.params.layers} 层（配置白名单：${(dmem.config && dmem.config.layers || []).length || '全层'}）`]);
      }
      setOut(`<div class="mll-kv">${rows.map(([k, v]) => `<div><span>${MLFields.esc(k)}</span><code>${MLFields.esc(v)}</code></div>`).join('')}</div>`, 'mll-ok-box');
    };

    root.querySelector('#mllProbe')?.addEventListener('click', probe);

    root.querySelector('#mllReloadCfg')?.addEventListener('click', async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      try {
        const res = await MLApi.controlPost('reload', {});
        setOut(`<b class="mll-ok">已重载</b> <span class="mll-dim">变更：${MLFields.esc((res.changed || []).join(', ') || '无')}；${MLFields.esc(res.note || '')}</span>`, 'mll-ok-box');
      } catch (e) {
        setOut(`<b class="mll-warn">重载失败</b> <span class="mll-dim">${MLFields.esc(e.message)}</span>`, 'mll-err');
      } finally {
        btn.disabled = false;
      }
    });
  },
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { MLPanels };
}
