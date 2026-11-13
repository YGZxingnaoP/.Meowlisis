# 蔚蓝色图插件（image_factory）

只做一件事：**蔚蓝档案角色出图**，走 MOSS-Image 8 步 DMD，打包成一条 QQ 聊天记录发回。

## 用法

```
Meowlisis蔚蓝色图 未花 2      ← 指定角色
Meowlisis蔚蓝色图 3           ← 随机挑 3 个角色
Meowlisis蔚蓝色图             ← 默认 1 张随机角色
```

- 触发词可在配置里改（`trigger`）；
- 张数上限 9；点了不存在的角色名会提示；
- 60 秒冷却，同一时间只跑一批。

## 特点

| 项 | 说明 |
|---|---|
| 主题 | 只有蔚蓝档案，角色名单在 `core/theme.py`（含别名，如「咪卡」→ 未花） |
| 出图 | MOSS-Image，8 步 + DMD LoRA 0.7 + cfg 1（与官方工作流开关开启档一致） |
| 画布 | 默认 832×1216 竖版 |
| 角色 tag | 先查 danbooru（`shiroko (blue archive)`）→ 缓存 → 查不到就跳过，不阻塞 |
| 外观 | `data/appearance.json` 人工表优先，避免模型编错配色 |
| 提示词 | MOSS 官方写法：质量词 + 逗号 + 一段英文长描述（可选 Layout JSON） |
| 法典 | 检索 ANIMA3 法典的姿态/服装/光照素材，不写死任何固定词表 |
| 归档 | `character/plugin_data/image_factory/YYYY-MM-DD/<时分秒>/`，`keep_images: 0` = 永久保留 |
| 交付 | 一条合并转发（聊天记录）；失败退回逐张发送；默认不额外说话 |

## 文件

```
plugin.py           插件入口（触发词拦截、setup/teardown）
core/theme.py       蔚蓝档案角色表（中文名 ↔ danbooru 名 ↔ 别名）
core/settings.py    配置读取
core/app.py         主流程：解析 → tag → 提示词 → 出图 → 归档 → 发送
core/comfy.py       内核自启 + MOSS 8 步织图 + 提交/等待/下载
core/prompt.py      提示词撰写（官方散文/Layout 二选一）
core/danbooru.py    角色 tag 查询与缓存
core/law.py         ANIMA3 法典检索
core/layout.py      官方 Layout JSON 校验
core/pack.py        合并转发凑包
data/appearance.json  人工外观表
data/danbooru_tags.json  tag 缓存
```

不写钩子：内核自启、织图、取 tag、凑包全部在本插件内自包含。
