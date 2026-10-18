// 验证 labs 里的 node -> python 调用在当前环境能不能跑（沙箱可能拦 piped stdio）
const { execFileSync } = require('child_process');
const path = require('path');

const script = path.resolve('D:/.Meowlisis/.vendor/.MeowLLM/labs/build_prompt.py');
const py = 'D:/.Meowlisis/runtime/311/python.exe';
try {
  const out = execFileSync(py, [script, '--uid', '000001', '--text', '在吗', '--full'],
    { encoding: 'utf-8', timeout: 180000, maxBuffer: 64 << 20 });
  const line = out.trim().split('\n').filter((l) => l.trim().startsWith('{')).pop();
  const d = JSON.parse(line);
  console.log('OK msgs=%d system=%d hist=%d mem_ok=%s',
    d.messages.length, d.system_chars, d.history_rounds, d.memory_unchanged);
} catch (err) {
  console.log('FAIL', String(err.message).slice(0, 200));
}
