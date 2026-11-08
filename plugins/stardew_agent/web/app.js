const $ = (id) => document.getElementById(id);
const esc = (value) => String(value == null ? "" : value).replace(/[&<>"]/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
}[c]));

const SEASON = { spring: "春", summer: "夏", fall: "秋", winter: "冬" };
const STATUS_MARK = {
  done: "✔", failed: "✘", active: "…", blocked: "!", cancelled: "×",
  skipped: "–", pending: "·", doing: "…", open: "·", dropped: "×", deferred: "»",
};
const KIND_CN = {
  action: "行为", dialogue: "对话", thought: "心声", event: "事件",
  plan: "计划", system: "系统", share: "分享", sleep: "睡觉",
};

let state = null;
let activeTab = "today";
let saves = [];
let currentSave = "";
let currentDate = "";
let diarySave = "";
let diaryDate = "";
let diaryItems = [];
let diaryPage = 1;
const DIARY_PAGE_SIZE = 4;

const THEME_KEY = "stardew_panel_theme";
function applyTheme(theme) {
  const value = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = value;
  try { localStorage.setItem(THEME_KEY, value); } catch (_) {}
  const button = $("theme-toggle");
  if (button) button.textContent = value === "dark" ? "☀️" : "🌙";
}
applyTheme(localStorage.getItem(THEME_KEY) || "light");

function clockText() {
  if (!state || !state.agent) return "读取中…";
  if (!state.agent.game && state.day) return `历史存档 · ${state.day}`;
  const game = state.agent.game || {};
  const season = SEASON[game.season] || game.season || "?";
  const time = Number(game.time || 0);
  return `第 ${game.year ?? "?"} 年 ${season} ${game.day ?? "?"} 日 · ${String(Math.floor(time / 100)).padStart(2, "0")}:${String(time % 100).padStart(2, "0")} · ${game.raining ? "雨天" : "晴天"}`;
}

function renderHeader() {
  const agent = (state && state.agent) || {};
  $("title").textContent = agent.playing ? "正在星露谷生活" : "今天在星露谷";
  $("clock").textContent = clockText();
  $("play-state").textContent = agent.playing ? "自己玩" : "未开始";
  $("play-state").className = "pill" + (agent.playing ? "" : " ghost");
  $("world-key").textContent = agent.world_key || "未读档";
  const dot = $("conn-dot");
  dot.classList.toggle("on", !!agent.connected);
  $("conn-text").textContent = agent.connected ? "mod 已连接" : "未连接";
}

function renderStats() {
  const agent = (state && state.agent) || {};
  const player = agent.player || {};
  const game = agent.game || {};
  const current = agent.current || {};
  $("activity").textContent = current.title || current.label || agent.activity || "闲着";
  $("progress").textContent = current.op
    ? `${current.op} · ${current.progress || "进行中"} · 第 ${current.step || 0}/${current.total || 0} 步`
    : (agent.thought || "还没什么心事");
  const mood = agent.mood || "还算平静";
  $("mood").textContent = mood;
  $("thought").textContent = agent.thought || "——";
  const energy = Number(player.energy || 0);
  const maxEnergy = Number(player.max_energy || 1) || 1;
  $("energy").textContent = `${energy} / ${maxEnergy}`;
  $("energy-bar").style.width = `${Math.max(0, Math.min(100, (energy / maxEnergy) * 100))}%`;
  $("money").textContent = `${player.money ?? "-"} g · 技能 ${agent.skills_text || "-"}`;
  $("where").textContent = `${player.location || "-"} (${player.tile_x ?? "-"},${player.tile_y ?? "-"})`;
  $("weather").textContent = `${game.raining ? "雨天" : "晴天"} · ${SEASON[game.season] || ""}`;
  $("inventory").textContent = agent.inventory_text || "空";
  $("bag-state").textContent = agent.inventory_full ? "背包满了" : `背包 ${player.inventory_slots ?? 36} 格`;
  $("skills").textContent = agent.skills_text || "还没有技能数据";
  if (agent.pending_profession) {
    $("skills").textContent += ` · 升级要选职业：${agent.pending_profession.title || ""}`;
  }
  const farm = agent.farm || {};
  $("farm-loc").textContent = farm.location || "Farm";
  $("farm-stats").innerHTML = [
    ["作物", farm.crops ?? 0], ["可收", farm.ready ?? 0],
    ["待浇", farm.thirsty ?? 0], ["杂物", farm.debris ?? 0],
    ["树", farm.trees ?? 0], ["动物", farm.animals ?? 0],
  ].map(([label, value]) => `<div><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
}

function nodeHtml(node, depth = 0) {
  const status = node.status || "pending";
  const mark = STATUS_MARK[status] || "·";
  const action = node.action || {};
  const meta = [];
  if (node.necessity != null) meta.push(`必要 ${node.necessity}`);
  if (node.priority != null) meta.push(`优先 ${node.priority}`);
  if (node.frequency) meta.push(node.frequency);
  if (action.goal) meta.push(`→ ${action.goal}`);
  const children = node.children || [];
  const why = node.detail || node.reason || node.source || "";
  return `<li>
    <div class="node ${esc(status)}">
      <span class="mark">${esc(mark)}</span>
      <span class="title">${esc(node.title || "?")}</span>
      <span class="meta">${meta.map((item) => `<span class="mini">${esc(item)}</span>`).join("")}</span>
      ${why ? `<span class="why">${esc(why)}</span>` : ""}
    </div>
    ${children.length ? `<ul>${children.map((child) => nodeHtml(child, depth + 1)).join("")}</ul>` : ""}
  </li>`;
}

function renderTree(target, nodes, emptyText) {
  if (!nodes || !nodes.length) {
    target.innerHTML = `<div class="empty">${esc(emptyText)}</div>`;
    return;
  }
  target.innerHTML = `<ul>${nodes.map((node) => nodeHtml(node)).join("")}</ul>`;
}

function renderGraph(target, nodes, emptyText) {
  if (!target) return;
  if (!nodes || !nodes.length) {
    target.innerHTML = `<div class="empty">${esc(emptyText)}</div>`;
    return;
  }
  const NS = "http://www.w3.org/2000/svg";
  const levels = [];
  const edges = [];
  const walk = (node, depth, parent) => {
    if (!levels[depth]) levels[depth] = [];
    const item = { node, depth, row: levels[depth].length, parent };
    levels[depth].push(item);
    if (parent) edges.push([parent, item]);
    (node.children || []).forEach((child) => walk(child, depth + 1, item));
  };
  nodes.forEach((node) => walk(node, 0, null));

  const pad = 18, colW = 238, rowH = 88, nodeW = 204, nodeH = 62;
  const rows = Math.max(...levels.map((level) => level.length));
  const width = pad * 2 + Math.max(1, levels.length) * colW;
  const height = pad * 2 + Math.max(1, rows) * rowH;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));

  edges.forEach(([parent, child]) => {
    const x1 = pad + parent.depth * colW + nodeW;
    const y1 = pad + parent.row * rowH + nodeH / 2;
    const x2 = pad + child.depth * colW;
    const y2 = pad + child.row * rowH + nodeH / 2;
    const mid = (x1 + x2) / 2;
    const path = document.createElementNS(NS, "path");
    path.setAttribute("class", "graph-edge");
    path.setAttribute("d", `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`);
    svg.appendChild(path);
  });

  levels.forEach((level) => level.forEach((item) => {
    const node = item.node;
    const status = node.status || "pending";
    const mark = STATUS_MARK[status] || "·";
    const x = pad + item.depth * colW;
    const y = pad + item.row * rowH;
    const group = document.createElementNS(NS, "g");
    group.setAttribute("class", `graph-node ${status}`);
    const rect = document.createElementNS(NS, "rect");
    rect.setAttribute("x", String(x));
    rect.setAttribute("y", String(y));
    rect.setAttribute("width", String(nodeW));
    rect.setAttribute("height", String(nodeH));
    rect.setAttribute("rx", "10");
    group.appendChild(rect);

    const title = document.createElementNS(NS, "text");
    title.setAttribute("class", "gtitle");
    title.setAttribute("x", String(x + 10));
    title.setAttribute("y", String(y + 23));
    title.textContent = `${mark} ${String(node.title || "?").slice(0, 18)}`;
    group.appendChild(title);

    const metaText = document.createElementNS(NS, "text");
    metaText.setAttribute("class", "gmeta");
    metaText.setAttribute("x", String(x + 10));
    metaText.setAttribute("y", String(y + 45));
    const bits = [];
    if (node.necessity != null) bits.push(`必${node.necessity}`);
    if (node.priority != null) bits.push(`优${node.priority}`);
    if (node.frequency) bits.push(node.frequency);
    if ((node.action || {}).goal) bits.push(`→${node.action.goal}`);
    metaText.textContent = bits.join(" · ").slice(0, 30);
    group.appendChild(metaText);

    const titleEl = document.createElementNS(NS, "title");
    titleEl.textContent = `${node.title || ""}\n${node.detail || node.reason || ""}`;
    group.appendChild(titleEl);
    svg.appendChild(group);
  }));

  target.innerHTML = "";
  target.appendChild(svg);
}

function renderDayPlan() {
  const plan = (state && state.plan) || null;
  const nodes = (plan && plan.nodes) || [];
  renderTree($("day-plan"), nodes, "还没有今日计划");
  renderTree($("day-plan-full"), nodes, "还没有今日计划");
  renderGraph($("day-graph"), nodes, "还没有今日计划");
  $("plan-reason").textContent = (plan && plan.reason) || "——";
  $("day-updated").textContent = plan ? `更新于 ${new Date((plan.updated || 0) * 1000).toLocaleTimeString()}` : "——";
}

function renderLongPlan() {
  const data = (state && state.long_term) || null;
  const roots = (data && data.roots) || [];
  renderTree($("long-plan"), roots, "还没有长线规划");
  renderTree($("long-plan-full"), roots, "还没有长线规划");
  renderGraph($("long-graph"), roots, "还没有长线规划");
  $("long-updated").textContent = data && data.updated ? new Date(data.updated * 1000).toLocaleString() : "——";
}

function renderTodos() {
  const data = (state && state.todos) || null;
  const items = (data && data.items) || [];
  $("todo-count").textContent = `${items.length} 条`;
  if (!items.length) {
    $("todos").innerHTML = '<div class="empty">今天没有待办</div>';
    return;
  }
  $("todos").innerHTML = items.map((item) => {
    const status = item.status || "open";
    const mark = STATUS_MARK[status] || "·";
    const by = item.by || item.source || "";
    const done = status === "done";
    const box = done
      ? `<span class="box done">${esc(mark)}</span>`
      : `<button class="box todo-check" data-todo-id="${esc(item.id)}" title="勾掉（重复的会一起打勾）">${esc(mark)}</button>`;
    return `<div class="todo ${esc(status)}">
      ${box}
      <div><div class="todo-title">${esc(item.content)}</div>
        <div class="todo-meta">必要 ${esc(item.necessity)} / 优先 ${esc(item.priority)} / ${esc(item.frequency)}${by ? " · " + esc(by) : ""}${item.note ? " · " + esc(item.note) : ""}</div>
      </div>
      <span class="prio">${esc(status)}</span>
    </div>`;
  }).join("");
}

function dayLabel(date) {
  const parts = String(date || "").split("_");
  if (parts.length < 3) return date || "-";
  const season = SEASON[parts[1]] || parts[1];
  return `第 ${parts[0]} 年 ${season} ${Number(parts[2])} 日`;
}

function fillDiarySaves() {
  const box = $("diary-save");
  if (!box) return;
  const keys = saves.map((item) => item.key);
  if (!keys.includes(diarySave) && diarySave) keys.unshift(diarySave);
  box.innerHTML = keys.map((key) =>
    `<option value="${esc(key)}"${key === diarySave ? " selected" : ""}>${esc(key)}</option>`
  ).join("") || `<option value="">（没有存档）</option>`;
}

function fillDiaryDates() {
  const box = $("diary-date");
  if (!box) return;
  const dates = [];
  for (const item of diaryItems) {
    if (item.date && !dates.includes(item.date)) dates.push(item.date);
  }
  box.innerHTML = [`<option value="">全部日期</option>`].concat(
    dates.map((date) =>
      `<option value="${esc(date)}"${date === diaryDate ? " selected" : ""}>${esc(dayLabel(date))}</option>`
    )
  ).join("");
}

function diaryFiltered() {
  if (!diaryDate) return diaryItems;
  return diaryItems.filter((item) => item.date === diaryDate);
}

function renderDiary() {
  const items = diaryFiltered();
  const pages = Math.max(1, Math.ceil(items.length / DIARY_PAGE_SIZE));
  diaryPage = Math.min(Math.max(1, diaryPage), pages);
  const start = (diaryPage - 1) * DIARY_PAGE_SIZE;
  const pageItems = items.slice(start, start + DIARY_PAGE_SIZE);
  $("diary-page").textContent = `${diaryPage} / ${pages}`;
  const body = $("diary-list");
  if (!pageItems.length) {
    body.innerHTML = '<div class="empty">这个存档还没有日记（睡前会写）</div>';
    return;
  }
  body.innerHTML = pageItems.map((item) => {
    const tags = (item.tags || []).map((tag) => `<span class="tag">${esc(tag)}</span>`).join("");
    const summary = item.summary && item.summary !== item.content
      ? `<div class="hint">摘要：${esc(item.summary)}</div>` : "";
    return `<article class="diary-card">
      <div class="diary-head">
        <div class="diary-date">${esc(dayLabel(item.date))}</div>
        <div class="diary-meta">${esc(item.weather || "")} · 心情：${esc(item.mood || "-")}</div>
      </div>
      ${summary}
      <div class="diary-body">${esc(item.content || "")}</div>
      ${tags ? `<div class="diary-tags">${tags}</div>` : ""}
    </article>`;
  }).join("");
}

function renderDigestBox(target, digest, date) {
  if (!target) return;
  if (!digest) {
    target.innerHTML = '<div class="empty">这一天还没有记忆摘要（睡前会写）</div>';
    return;
  }
  const shares = (digest.shares || []).slice(0, 3);
  const thoughts = (digest.thoughts || []).slice(0, 3);
  const tips = digest.tips || [];
  const lines = [];
  if (digest.summary) lines.push(`<div class="line"><b>摘要</b> ${esc(digest.summary)}</div>`);
  if (shares.length) lines.push(`<div class="line"><b>分享</b> ${shares.map(esc).join("；")}</div>`);
  if (thoughts.length) lines.push(`<div class="line"><b>心声</b> ${thoughts.map(esc).join("；")}</div>`);
  if (tips.length) lines.push(`<div class="line"><b>长期记忆</b> ${tips.map((tip) => esc(tip.content)).join("；")}</div>`);
  target.innerHTML = `<h3>${esc(dayLabel(date))} · 记忆摘要</h3>` + (lines.join("") || '<div class="empty">没有可展示的内容</div>');
}

async function loadDiaryDigest() {
  const date = diaryDate || (diaryItems[0] && diaryItems[0].date) || "";
  const target = $("diary-digest");
  if (!date) {
    renderDigestBox(target, null, "");
    return;
  }
  const params = new URLSearchParams({ date });
  if (diarySave) params.set("save", diarySave);
  try {
    const response = await fetch(`/api/digest?${params}`, { cache: "no-store" });
    const data = await response.json();
    renderDigestBox(target, data.digest || null, date);
  } catch (_) {
    renderDigestBox(target, null, date);
  }
}

async function loadDiary() {
  if (!diarySave) diarySave = currentSave || (saves[0] && saves[0].key) || "";
  const params = new URLSearchParams({ limit: "500" });
  if (diarySave) params.set("save", diarySave);
  try {
    const response = await fetch(`/api/diary?${params}`, { cache: "no-store" });
    const data = await response.json();
    diaryItems = (data.items || []).slice().reverse();
  } catch (_) {
    diaryItems = [];
  }
  fillDiarySaves();
  fillDiaryDates();
  diaryPage = 1;
  renderDiary();
  loadDiaryDigest();
}

function renderMemoryDigest() {
  const box = $("memory-digest");
  if (!box) return;
  const payload = (state && state.digest) || {};
  const digest = payload.digest || null;
  const date = payload.date || (state && state.day) || "";
  $("digest-date").textContent = date ? dayLabel(date) : "—";
  renderDigestBox(box, digest, date);
}


function renderJournal() {
  const items = (state && state.journal && state.journal.items) || [];
  $("journal-count").textContent = `${items.length} 条`;
  const body = $("journal-list");
  if (!items.length) {
    body.innerHTML = '<div class="empty">今天还没有记录</div>';
    return;
  }
  body.innerHTML = items.map((row) => `<div class="jrow">
    <span class="jtime">${esc(row.time || "--:--")}</span>
    <span class="jkind ${esc(row.kind || "")}">${esc(KIND_CN[row.kind] || row.kind || "")}</span>
    <span class="jcontent">${esc(row.content || "")}</span>
  </div>`).join("");
}

function renderMemory() {
  const data = (state && state.memory) || null;
  const items = (data && data.items) || [];
  $("memory-count").textContent = `${data && data.total ? data.total : items.length} 条`;
  const body = $("memory-list");
  if (!items.length) {
    body.innerHTML = '<div class="empty">还没有长期记忆</div>';
    return;
  }
  body.innerHTML = items.map((tip) => {
    const tags = (tip.tag || []).map((tag) => `<span class="tag">${esc(tag)}</span>`).join("");
    const attrs = tip.attributes || {};
    const meta = [];
    meta.push(`价值 ${attrs.value ?? "?"}`);
    meta.push(`可信 ${attrs.accuracy ?? "?"}`);
    if (attrs.npc) meta.push(`${attrs.npc} · 好感 ${attrs.friendship ?? "?"}`);
    if (attrs.relationship) meta.push(attrs.relationship);
    return `<article class="memory">
      <div class="content">${esc(tip.content || "")}</div>
      <div class="foot">${tags}<span class="v">${esc(meta.join(" · "))}</span></div>
    </article>`;
  }).join("");
}

function renderHabits() {
  const data = (state && state.habits) || null;
  const windows = (data && data.windows) || [];
  const body = $("habit-list");
  if (!windows.length) {
    body.innerHTML = '<div class="empty">还不到 7 天</div>';
    return;
  }
  body.innerHTML = windows.slice().reverse().map((win) => {
    const info = win.window || {};
    const habits = win.habits || [];
    return `<div class="habit-window">
      <h3>${esc(info.start || "?")} ~ ${esc(info.end || "?")}</h3>
      ${habits.length ? habits.map((habit) => `<div class="habit">
        <span class="when">${esc((habit.week_day || []).join("、"))} ${esc((habit.time || []).join("、"))}</span>
        <span class="what">${esc(habit.content || "")}</span>
        <span class="why">${esc(habit.reason || "")}</span>
      </div>`).join("") : '<div class="empty">这一周没有总结出习惯</div>'}
    </div>`;
  }).join("");
}

function render() {
  if (!state || state.ok === false) {
    $("clock").textContent = (state && state.reason) || "面板还没连上角色";
    return;
  }
  renderHeader();
  renderStats();
  renderConsole();
  renderDayPlan();
  renderLongPlan();
  renderTodos();
  renderDiary();
  renderJournal();
  renderMemory();
  renderMemoryDigest();
  renderHabits();
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tab}`);
  });
  if (tab === "diary" && !diaryItems.length) loadDiary();
}

async function refresh() {
  try {
    const query = new URLSearchParams();
    if (currentSave) query.set("save", currentSave);
    if (currentDate) query.set("date", currentDate);
    const response = await fetch(`/api/state?${query.toString()}`, { cache: "no-store" });
    state = await response.json();
    if (!currentSave && state && state.save) {
      currentSave = state.save;
      const item = saves.find((entry) => entry.key === currentSave);
      currentDate = (item && item.latest_day) || state.day || "";
      fillSaves();
      fillDates();
    }
    render();
  } catch (error) {
    $("clock").textContent = `读取失败：${error.message}`;
  }
}

function fillSaves() {
  const box = $("save-select");
  if (!box) return;
  box.innerHTML = saves.map((item) =>
    `<option value="${esc(item.key)}"${item.key === currentSave ? " selected" : ""}>${esc(item.key)}</option>`
  ).join("") || `<option value="">（没有存档数据）</option>`;
}

function fillDates() {
  const box = $("date-select");
  if (!box) return;
  const item = saves.find((entry) => entry.key === currentSave);
  const days = (item && item.days) || [];
  box.innerHTML = days.map((day) =>
    `<option value="${esc(day)}"${day === currentDate ? " selected" : ""}>${esc(dayLabel(day))}</option>`
  ).join("") || `<option value="">${esc(currentDate || "最近一天")}</option>`;
}

async function loadSaves() {
  try {
    const response = await fetch("/api/saves", { cache: "no-store" });
    const data = await response.json();
    saves = (data && data.items) || [];
    fillSaves();
    fillDates();
  } catch (_) {}
}

$("save-select").addEventListener("change", (event) => {
  currentSave = event.target.value;
  const item = saves.find((entry) => entry.key === currentSave);
  currentDate = (item && item.latest_day) || "";
  fillDates();
  if (activeTab === "diary") {
    diarySave = currentSave;
    diaryDate = "";
    loadDiary();
  }
  refresh();
});
$("date-select").addEventListener("change", (event) => {
  currentDate = event.target.value;
  refresh();
});
$("diary-save").addEventListener("change", (event) => {
  diarySave = event.target.value;
  diaryDate = "";
  diaryPage = 1;
  loadDiary();
});
$("diary-date").addEventListener("change", (event) => {
  diaryDate = event.target.value;
  diaryPage = 1;
  renderDiary();
  loadDiaryDigest();
});
$("diary-prev").addEventListener("click", () => {
  if (diaryPage > 1) {
    diaryPage -= 1;
    renderDiary();
  }
});
$("diary-next").addEventListener("click", () => {
  const pages = Math.max(1, Math.ceil(diaryFiltered().length / DIARY_PAGE_SIZE));
  if (diaryPage < pages) {
    diaryPage += 1;
    renderDiary();
  }
});
$("theme-toggle").addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});
$("todos").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-todo-id]");
  if (!button) return;
  button.disabled = true;
  try {
    await postJson("/api/todo", { action: "done", id: button.dataset.todoId });
    refresh();
  } catch (_) {
    button.disabled = false;
  }
});

async function sendAdvice() {
  const input = $("advice-input");
  const text = input.value.trim();
  if (!text) return;
  $("advice-reply").textContent = "她正在想…";
  try {
    const response = await fetch("/api/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await response.json();
    const result = (data && data.result) || {};
    $("advice-reply").textContent = result.reply || "她听到了。";
    input.value = "";
    refresh();
  } catch (error) {
    $("advice-reply").textContent = `发送失败：${error.message}`;
  }
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});
$("advice-btn").addEventListener("click", sendAdvice);
$("advice-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") sendAdvice();
});

// ---- 操作台：真的打到插件 HTTP API，再走主链路的模型能力 ----
function consoleLog(text, ok) {
  const box = $("console-log");
  const time = new Date().toLocaleTimeString();
  box.textContent = `[${time}] ${text}`;
  box.className = "reply console-log" + (ok === false ? " error" : "");
  box.scrollTop = box.scrollHeight;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  return response.json();
}

async function playAction(action, extra) {
  consoleLog(`正在执行 ${action} …`);
  try {
    const data = await postJson("/api/play", Object.assign({ action }, extra || {}));
    consoleLog(data.message || data.status || (data.ok ? "完成" : "失败"), data.ok);
    refresh();
  } catch (error) {
    consoleLog(`请求失败：${error.message}`, false);
  }
}

async function sendRequest() {
  const input = $("request-input");
  const text = input.value.trim();
  if (!text) return;
  consoleLog("她正在判断要不要做这件事…");
  try {
    const data = await postJson("/api/request", { text });
    const result = (data && data.result) || {};
    consoleLog(`${result.mode || "?"}：${result.reply || "她听到了。"}`, data.ok);
    input.value = "";
    refresh();
  } catch (error) {
    consoleLog(`发送失败：${error.message}`, false);
  }
}

document.querySelectorAll("[data-play]").forEach((btn) => {
  btn.addEventListener("click", () => playAction(btn.dataset.play));
});
document.querySelectorAll("[data-goal]").forEach((btn) => {
  btn.addEventListener("click", () => playAction("grant", { goal: btn.dataset.goal }));
});
$("request-btn").addEventListener("click", sendRequest);
$("request-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) sendRequest();
});

function renderConsole() {
  const agent = (state && state.agent) || {};
  const current = agent.current || {};
  const bits = [];
  bits.push(agent.connected ? "mod 已连接" : "mod 未连接");
  bits.push(agent.playing ? "自己玩" : "未开始");
  if (current.title || current.label) {
    bits.push(`正在：${current.title || current.label}`);
  }
  if (agent.reason) bits.push(`错误：${agent.reason}`);
  if (agent.thought) bits.push(`心声：${agent.thought}`);
  $("console-state").textContent = bits.join(" · ");
}

switchTab("today");
loadSaves().then(() => {
  diarySave = currentSave || (saves[0] && saves[0].key) || "";
  refresh();
  loadDiary();
});
setInterval(refresh, 5000);
