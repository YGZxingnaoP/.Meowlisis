#!/usr/bin/env node
/**
 * MeowLLM 实验台后端（零依赖，Node 18+）。
 *
 * 职责只有两件：
 *   1. 把 MeowLLM 的 SSE 双流转成"带时间戳的 NDJSON"给浏览器，
 *      这样前端能把「思考」和「输出」画在同一条时间轴上。
 *   2. 跑一组对照实验（A_async / S_seq），把指标落盘。
 *
 * 两个臂的区别（诚实说明）
 * ------------------------
 *   A_async : thinking_level=low → 引擎走双流，reasoning 与 content 交错产出
 *   S_seq   : thinking_level=off → 不单独思考，单流直接回答
 *
 * 注意：真正的「先想完再说」串行基线需要 llama.cpp 引擎，本项目里已删除
 * （bags/ 里还有压缩包，需要时可解压恢复）。所以这里的 S_seq 是
 * 「无后台思考」而不是「串行思考」，前端会明确标注这一点。
 *
 * 端点
 * ----
 *   GET  /                 页面
 *   GET  /api/info         目标地址、引擎信息、健康状态
 *   POST /api/chat         实时对话（NDJSON：start/reasoning/content/meta/finish）
 *   POST /api/run          跑对照实验并落盘
 */

'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');

// 参数优先级：命令行 > 环境变量 > 默认值（run_lab.bat 用命令行形式传）
const ARGV = process.argv.slice(2);
function argOf(flag) {
  const i = ARGV.indexOf(flag);
  return i >= 0 && ARGV[i + 1] ? ARGV[i + 1] : null;
}

const LAB_PORT = Number(argOf('--port') || process.env.LAB_PORT || 18700);
const MEOWLLM = (argOf('--meowllm') || process.env.MEOWLLM || 'http://127.0.0.1:18100')
  .replace(/\/+$/, '');
const OUT_DIR = process.env.LAB_OUT || path.join(__dirname, 'out');
const PUBLIC_DIR = path.join(__dirname, 'public');
const V1 = `${MEOWLLM}/meowllm/v1`;
const CTL = `${MEOWLLM}/meowllm/control`;

const MODES = {
  A_async: { label: 'A 双流 · 边想边说', thinking: 'low' },
  S_seq: { label: 'S 单流 · 不想直说', thinking: 'off' },
};

// ------------------------------------------------------------------ 工具
function sendJSON(res, code, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      let text = Buffer.concat(chunks).toString('utf8');
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
      try {
        resolve(text ? JSON.parse(text) : {});
      } catch {
        resolve({});
      }
    });
  });
}

async function meowllmHealth() {
  try {
    const resp = await fetch(`${CTL}/health`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return { ok: false, status: resp.status };
    return { ok: true, data: await resp.json() };
  } catch (err) {
    return { ok: false, error: String((err && err.message) || err) };
  }
}

// ------------------------------------------------------------------ 双流中继
/**
 * 调 MeowLLM 的流式接口，把 SSE 增量转成 NDJSON 回调。
 * onEvent({type, ...})，type ∈ start / reasoning / content / meta / finish / error
 */
async function streamChat({ messages, mode, maxTokens }, onEvent) {
  const spec = MODES[mode] || MODES.A_async;
  const body = {
    model: 'meowllm-local',
    messages,
    stream: true,
    ...(maxTokens ? { max_tokens: maxTokens } : {}),
    meowllm: { thinking_level: spec.thinking },
  };

  const started = Date.now();
  let resp;
  try {
    resp = await fetch(`${V1}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(300000),
    });
  } catch (err) {
    onEvent({ type: 'error', message: String((err && err.message) || err) });
    return null;
  }
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => '');
    onEvent({ type: 'error', message: text.slice(0, 600) || `HTTP ${resp.status}` });
    return null;
  }

  onEvent({ type: 'start', mode, thinking: spec.thinking });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let reasoning = '';
  let content = '';
  let meta = {};
  let firstReason = null;
  let firstContent = null;
  let finish = '';
  let overlapChars = 0;      // 首个输出片**之后**才到达的思考字数
  let overlapChunks = 0;     // 同上，按片数

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload || payload === '[DONE]') continue;
      let obj;
      try { obj = JSON.parse(payload); } catch { continue; }
      if (obj.meowllm) meta = { ...meta, ...obj.meowllm };
      for (const choice of obj.choices || []) {
        const delta = choice.delta || {};
        const ms = Date.now() - started;
        if (delta.reasoning_content) {
          if (firstReason === null) firstReason = ms;
          // 输出已经开始之后仍在产出的思考 = "边说边想"的直接证据
          if (firstContent !== null) {
            overlapChars += delta.reasoning_content.length;
            overlapChunks += 1;
          }
          reasoning += delta.reasoning_content;
          onEvent({ type: 'reasoning', text: delta.reasoning_content, ms });
        }
        if (delta.content) {
          if (firstContent === null) firstContent = ms;
          content += delta.content;
          onEvent({ type: 'content', text: delta.content, ms });
        }
        if (choice.finish_reason) finish = choice.finish_reason;
      }
    }
  }

  const total = Date.now() - started;
  const stats = {
    mode,
    total_ms: total,
    first_reasoning_ms: firstReason,
    first_content_ms: firstContent,
    reasoning_chars: reasoning.length,
    content_chars: content.length,
    // 输出开始时，思考已经跑了多少毫秒（双流同时起步时约等于 0，属正常）
    think_ahead_ms: (firstContent !== null && firstReason !== null)
      ? Math.max(0, firstContent - firstReason) : null,
    // 关键指标：首个输出片之后仍在产出的思考字数/片数。
    // > 0 就证明"输出已经在说，思考还没停" —— 这正是 AsyncReasoning 的行为。
    overlap_chars: overlapChars,
    overlap_chunks: overlapChunks,
    finish_reason: finish,
    text: content,
    reasoning,
  };
  onEvent({ type: 'meta', meta, stats });
  onEvent({ type: 'finish', stats });
  return stats;
}

// ------------------------------------------------------------------ 路由
async function handle(req, res) {
  const url = new URL(req.url, `http://127.0.0.1:${LAB_PORT}`);
  const pathname = url.pathname;

  if (req.method === 'GET' && (pathname === '/' || pathname === '/index.html')) {
    try {
      const html = fs.readFileSync(path.join(PUBLIC_DIR, 'index.html'));
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(html);
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(`index.html 读取失败：${err.message}`);
    }
    return;
  }

  if (req.method === 'GET' && pathname === '/api/info') {
    const health = await meowllmHealth();
    return sendJSON(res, 200, {
      meowllm: MEOWLLM,
      out_dir: OUT_DIR,
      modes: MODES,
      health,
    });
  }

  if (req.method === 'POST' && pathname === '/api/chat') {
    const body = await readBody(req);
    res.writeHead(200, {
      'Content-Type': 'application/x-ndjson; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Accel-Buffering': 'no',
    });
    const emit = (event) => {
      if (!res.writableEnded) res.write(`${JSON.stringify(event)}\n`);
    };
    try {
      await streamChat({
        messages: body.messages || [],
        mode: body.mode || 'A_async',
        maxTokens: body.max_tokens,
      }, emit);
    } catch (err) {
      emit({ type: 'error', message: String((err && err.message) || err) });
    }
    if (!res.writableEnded) res.end();
    return;
  }

  if (req.method === 'POST' && pathname === '/api/run') {
    const body = await readBody(req);
    const turns = body.turns || [];
    const modes = body.modes && body.modes.length ? body.modes : Object.keys(MODES);
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const rows = [];

    for (const mode of modes) {
      const history = [];
      for (let i = 0; i < turns.length; i += 1) {
        const user = String(turns[i] || '').trim();
        if (!user) continue;
        history.push({ role: 'user', content: user });
        const stats = await streamChat({
          messages: history.slice(), mode, maxTokens: body.max_tokens,
        }, () => {});
        if (!stats) {
          rows.push({ mode, turn: i + 1, user, ok: false });
          continue;
        }
        rows.push({ mode, turn: i + 1, user, ok: true, ...stats });
        history.push({ role: 'assistant', content: stats.text });
      }
    }

    const summary = {};
    for (const row of rows) {
      if (!summary[row.mode]) {
        summary[row.mode] = {
          label: (MODES[row.mode] || {}).label || row.mode,
          turns: 0, errors: 0,
          first_reasoning_ms: [], first_content_ms: [],
          think_ahead_ms: [], total_ms: [],
          reasoning_chars: 0, content_chars: 0,
        };
      }
      const s = summary[row.mode];
      s.turns += 1;
      if (!row.ok) { s.errors += 1; continue; }
      if (row.first_reasoning_ms != null) s.first_reasoning_ms.push(row.first_reasoning_ms);
      if (row.first_content_ms != null) s.first_content_ms.push(row.first_content_ms);
      if (row.think_ahead_ms != null) s.think_ahead_ms.push(row.think_ahead_ms);
      s.total_ms.push(row.total_ms);
      s.reasoning_chars += row.reasoning_chars;
      s.content_chars += row.content_chars;
    }

    try {
      fs.mkdirSync(OUT_DIR, { recursive: true });
      const base = path.join(OUT_DIR, `${stamp}`);
      fs.writeFileSync(`${base}.jsonl`,
        rows.map((r) => JSON.stringify(r)).join('\n'), 'utf8');
      fs.writeFileSync(`${base}-summary.json`,
        JSON.stringify({ meowllm: MEOWLLM, summary, modes: MODES }, null, 2), 'utf8');
    } catch (err) {
      return sendJSON(res, 500, { error: `结果落盘失败：${err.message}` });
    }

    return sendJSON(res, 200, { rows, summary, modes: MODES, out_dir: OUT_DIR });
  }

  return sendJSON(res, 404, { error: 'not found', path: pathname });
}

// ------------------------------------------------------------------ 启动
const server = http.createServer((req, res) => {
  handle(req, res).catch((err) => {
    if (!res.writableEnded) {
      res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ error: String((err && err.message) || err) }));
    }
  });
});

server.on('error', (err) => {
  console.error(`[lab] 启动失败：${err.message}`);
  if (err.code === 'EADDRINUSE') {
    console.error(`[lab] 端口 ${LAB_PORT} 被占用；换端口：run_lab.bat port 18701`);
  }
  process.exit(1);
});

server.listen(LAB_PORT, '127.0.0.1', () => {
  console.log(`[lab] UI       http://127.0.0.1:${LAB_PORT}`);
  console.log(`[lab] MeowLLM  ${MEOWLLM}`);
  console.log(`[lab] results  ${OUT_DIR}`);
});
