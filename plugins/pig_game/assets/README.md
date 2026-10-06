# 养猪游戏 · assets（图片占位）

本目录存放**占位图**，可直接用你自己的美术图覆盖（文件名保持一致即可）。

## 命名规则

| 类型 | 文件名 | 尺寸建议 |
|---|---|---|
| 猪种图 | `pig_<species_id>.png` | 240×240 |
| 猪圈场景图 | `scene_<scene_id>.png` | 360×200 |

## 当前猪种 id（对应 `../data/species.json`）

- `pig_super_fat.png` —— 超级肥猪
- `pig_flying.png` —— 神奇飞猪
- `pig_fish.png` —— 鱼猪
- `pig_gudu.png` —— 咕嘟猪

## 当前场景 id（对应配置项 `scenes`）

- `scene_grass.png` —— 草地
- `scene_farm.png` —— 农场
- `scene_night.png` —— 夜晚

## 说明

- 首次启动时插件会用 Pillow 自动生成缺失的占位图（灰底＋名字），**已存在的文件绝不覆盖**。
- 图片缺失时插件会**自动跳过图片段**，只发文字，不会报错。
- 新增猪种/场景时，同步补一张同名图片即可。
