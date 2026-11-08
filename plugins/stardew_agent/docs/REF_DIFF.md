# 与参考项目的关系（0.7.0）

- 执行层：`game_mod` 移植自 `BlindWhaleFarmer`，并跟进当前上游的 `ShellClosed` / `MonsterName` /
  家具右键 / 逐格走路 + 顺手采集。
- 操作层：照参考项目的 DSH gateway 做法，主模型通过一个 `stardew` 工具调用全部动作。
  旧的 Python 规划器（36 个 goal + 硬编码 `steps_for`）已删除。
- 本插件额外保留：REST `/state`、`/command`、`/cancel`、截图、自动读档、MCP 18080。
- 商店仍是“走到柜台”版本（`GameActions.Shop.cs`），不是 `Utility.TryOpenShopMenu` 直接开店。
