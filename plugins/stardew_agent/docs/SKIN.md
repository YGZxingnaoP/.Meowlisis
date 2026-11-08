# 发型 / 配饰（皮肤系统已删除）

整套农夫皮肤（身体、衣服、裤子、帽子、鞋子、自定义 sprite sheet）**已经删除**，
不再接管 `Characters/Farmer/*` 资产，也没有 `skin_export` / `skin_upload` 接口。

现在只保留两个游戏内编号配置：

```yaml
appearance:
  hair_style: 0   # 0 = 不改；对应游戏 hairstyles 表
  accessory: 0    # 0 = 不改；对应游戏 accessories 表
```

- 只改角色自己的发型/配饰编号，不动任何贴图文件；
- 想换外观就在插件配置里改编号，或在游戏里用衣柜/镜子；
- 旧文档里的 `Mods/StardewAgent/appearance/*.png` 不再读取。
