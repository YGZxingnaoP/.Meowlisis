#!/usr/bin/env node
/**
 * 无界面跑对照实验（A_async vs S_seq），复用实验台的 /api/run。
 *
 * 为什么要走实验台而不是直连
 * --------------------------
 * 双流的时间戳（首个思考片 / 首个输出片 / 输出开始时思考已跑多久）是在
 * 实验台那一层打的；直连 MeowLLM 拿不到这些相对时间，指标就不可比。
 *
 * 用法（先起实验台）
 * ------------------
 *   node run_headless.js                       # 用内置三轮
 *   node run_headless.js --turn "第一句" --turn "第二句"
 *   node run_headless.js --mode A_async --max-tokens 256
 *   node run_headless.js --lab http://127.0.0.1:18700
 */

'use strict';

function argOf(flag, dflt) {
  const i = process.argv.indexOf(flag);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}

function allOf(flag) {
  const out = [];
  process.argv.forEach((a, i) => {
    if (a === flag && process.argv[i + 1]) out.push(process.argv[i + 1]);
  });
  return out;
}

const LAB = argOf('--lab', 'http://127.0.0.1:18700');

const DEFAULT_TURNS = [
  '先记一下：我对花生严重过敏，吃了会进医院。',
  '今天好热啊，风扇都不够用。',
  '晚上想吃花生酱拌面，帮我出个主意？',
];

async function main() {
  const turns = allOf('--turn');
  const onlyMode = argOf('--mode');
  const body = {
    turns: turns.length ? turns : DEFAULT_TURNS,
    max_tokens: Number(argOf('--max-tokens', '192')),
  };
  if (onlyMode) body.modes = [onlyMode];

  console.log(`[headless] lab = ${LAB}`);
  console.log(`[headless] 轮数 = ${body.turns.length}，臂 = ${body.modes || '全部'}`);
  console.log('');

  const resp = await fetch(`${LAB}/api/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    console.error(`[headless] 失败：HTTP ${resp.status}`);
    process.exit(1);
  }
  const data = await resp.json();
  if (data.error) {
    console.error(`[headless] 失败：${data.error}`);
    process.exit(1);
  }

  const avg = (arr) => (arr && arr.length
    ? Math.round(arr.reduce((a, b) => a + b, 0) / arr.length) : null);
  const pad = (s, n) => String(s).padEnd(n);

  console.log(`${pad('臂', 22)}${pad('首思考', 9)}${pad('首输出', 9)}${pad('输出时思考已跑', 16)}${pad('总耗时', 9)}思考/输出字`);
  for (const [key, s] of Object.entries(data.summary)) {
    console.log(
      pad(s.label || key, 22)
      + pad(avg(s.first_reasoning_ms) ?? '-', 9)
      + pad(avg(s.first_content_ms) ?? '-', 9)
      + pad(avg(s.think_ahead_ms) ?? '-', 16)
      + pad(avg(s.total_ms), 9)
      + `${s.reasoning_chars}/${s.content_chars}`);
  }
  console.log('');
  console.log(`落盘：${data.out_dir}`);
  console.log('');
  console.log('读法：A 臂的「输出时思考已跑」应明显 > 0，说明输出在思考未结束时开始；');
  console.log('      S 臂没有思考流（首思考为 -），所以该项也是 -。');
}

main().catch((err) => {
  console.error(`[headless] 异常：${(err && err.message) || err}`);
  process.exit(1);
});
