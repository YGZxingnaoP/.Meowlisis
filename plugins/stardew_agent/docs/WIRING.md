# 接线（0.7.0）

```text
主模型
  └─ stardew(action, args)
       ├─ help / get_state / get_guide → MCP http://127.0.0.1:18080/mcp
       └─ 其它动作 → REST POST http://127.0.0.1:8765/command
  └─ StardewAgent 模组 Tools.Execute（52 个动作）
```

- `help` 的规则和动作列表来自 MCP `initialize.instructions` + `tools/list`。
- `get_state` 优先走 MCP（带长期笔记）；MCP 不可用时退回 REST `/state`。
- `cancel` 走 REST `/cancel`（`MainThread.CancelCurrent`）。
- QQ 控制指令只接管 `状态/开始玩/别玩了/去 x y/睡/取消/帮助`；自然语言交给主模型。
