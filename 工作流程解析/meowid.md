# MeowID 词表（v1 · 待你审）

> 全项目身份系统的**唯一用语标准**。
> 代码里的变量名、JSON 键、函数参数、日志、注释，**只能使用本表列出的词**；
> 表外新词一律不许造，旧词按 §3 映射表改掉。

---

## 0. 唯一前提

**全项目只有一个「平台」= 本数字人服务端（Meowlisis）本身。**

QQ、B站、手机、麦克风、Postman —— **都不是平台**，它们是「通道 / 外部账号」。

---

## 1. 四个实体

### 1.1 `meowid` —— 服务端唯一身份键（唯一"统一"的东西）

- 形态：`000001`（正式） / `temp-000012`（临时 = 离线账号）
- 铁律：**任何人说过一句话，就必须有一个 meowid**；没有就现建 temp。
  - 不许拒绝建档，不许把 temp 当垃圾清理，不许因为"没昵称"就不给 id。
- 一切存储路径、记忆、档案、文件名、跨模块传参，**只用它**。
- 禁用旧名：`id` `uid` `user_id` `identity_id` `identity` `uid_or_temp`

### 1.2 `nickname` —— 项目内昵称（只用于展示）

- 归属：**绑定在 meowid 上，属于"人"，与任何外部软件无关**。
- **不**来自 QQ 名片，**不**来自 B站昵称，**不**自动从外部显示名填充。
- 外部软件里的名字一律叫 `ext_name`（见 1.4），别混。
- 禁用旧名：任何把 `username` / `name` 当昵称用的写法。

### 1.3 外部账号 ExternalAccount —— 用来"认人"的凭据

- 由二元组唯一确定：**`(channel, ext_account)` —— 只用于 `qq` / `bili` 两条通道**
  - `channel`：`qq` | `bili`（**只有这两个会反查**；`msg` 类不反查，见 §5）
  - `ext_account`：该通道上这个人的账号值：QQ号 / B站uid
- 作用：把外部账号**挂到某个 meowid 上** → 下次从该通道来，就能认出是同一个人。
- 熟人统一：**同一个真人的 QQ 与 B站 外部账号，必须挂在同一个 meowid 上**（合并，不新建）。
- 禁用旧名：`account`（歧义）、`platform`（此词保留给服务端本身）、`open_id`（只是某一种 ext_account）

### 1.4 `ext_name` —— 外部显示名

- 例：QQ群名片「想找哥哥打游戏」、B站昵称、备注名。
- 地位：**认人线索 + 念出来的临时称呼**，**它不是 nickname**。
- 硬规则：**绝不允许写进 `nickname` 字段**。

---

## 2. 新键值表（代码里只许出现这些名字）

| 用途 | 新键名 | 值示例 | 说明 |
|---|---|---|---|
| 身份键 | `meowid` | `000001` / `temp-000012` | 全项目唯一身份 |
| 项目昵称 | `nickname` | `YGZ醒脑片` | 展示用，项目绑定 |
| 通道 | `channel` | `qq` / `bili` / `msg` | `msg` 再分 `voice` / `api` / `phone`（见 §5） |
| 外部账号值 | `ext_account` | `1149942002` | 认人用 |
| 外部显示名 | `ext_name` | `想找哥哥打游戏` | 只做线索 |
| 群号 | `group_id` | `174127179` | 群记忆归属 |
| 是否临时 | 函数 `is_temp(meowid)` | `True/False` | 判断 temp |

---

## 3. 禁用词映射表（旧 → 新）

| 禁用旧名 | 换成 | 原因 |
|---|---|---|
| `id` `uid` `user_id` `identity_id` `identity` `uid_or_temp` | **`meowid`** | 都指身份键，名字不同容易漏改 |
| `username` | 按语义拆：身份 → `meowid`；项目昵称 → `nickname`；外部显示名 → `ext_name` | 一词四义，必须拆掉 |
| `name` | `nickname`（项目昵称）或 `ext_name`（外部显示名） | 歧义 |
| `account` | `meowid`（当它其实是编号）/ `ext_account`（当它是外部账号） | **今天翻车的词** |
| `platform` | `channel`；中文"平台"二字只指服务端 | 一词两义 |
| `source` | `channel` | 一词两义 |
| `nickname_of` `display_name` `disp_name` `_disp` `nick_name` `user_name` `username`（函数名） | 归一到 `nickname` / `ext_name` 两个词 | 我之前造的词，全部作废 |

---

## 4. 五条铁律（这就是验收标准）

1. **说话即有 `meowid`**（临时也要有）；永不拒绝建档、永不清理 temp。
2. **`meowid` 是唯一统一的东西**；nickname、外部账号、ext_name 都是挂它上面的附属信息。
3. **`nickname` 与外部软件无关**（禁止从 `ext_name` 推导/填充 nickname）。
4. **同一个人的多个外部账号 → 同一个 `meowid`**（QQ + B站 统一）。
5. **要记住所有人、所有人的聊天**（多用户是主体，不是边缘场景）。

---

## 5. 两条通道族的入口规则（**你已确认**）

| channel | 必须提供 | 处理 | 查不到时 |
|---|---|---|---|
| `qq` | 外部账号 = QQ号 | 反查 meowid | 建档 |
| `bili` | 外部账号 = B站uid | 反查 meowid | 建档 |
| `msg` + `voice` | **meowid** | 不反查 | 校验 meowid |
| `msg` + `api` | **meowid** | 不反查 | 校验 meowid |
| `msg` + `phone` | **meowid** | 不反查 | 校验 meowid |

**铁律一**：说话即有 meowid。qq / bili 建档时用该通道的外部显示名填一次 `nickname`。

## 5.1 nickname 的原逻辑（**沿用，不重造**）

| 来源 | 机制 | 优先级 / 规则 |
|---|---|---|
| QQ | `func/toolbox/napcat/groupchat/user_nickname.py` | `profile_name(档案昵称) > card(群名片) > nickname(QQ昵称) > QQ号` |
| B站 | `func/catbrain/UserMemory/identity/bili_lookup.py` | 昵称 ↔ uid 互查 |
| 仓库 | `store._fill_nickname` | **只在空时填一次 + 去重**，绝不覆盖已有的 |
| 项目内改名 | `store.set_nickname` / `TBUserNicknameMap.bind` | 显式覆盖 |

---

## 6. 记忆分层（归属键不同，禁止混用）

| 层 | 归属键 | 存什么 |
|---|---|---|
| 短期池 `public_short_mem.json` | **无归属键**（事情维度，全池共享） | 刚刚发生了什么 |
| 人档案 / 长期记忆 / 待办 / 游戏存档 | `meowid` | 这个人 |
| 群记录 | `group_id` | 这个群 |

---

## 7. 展示名唯一来源（**沿用原逻辑**）

```
display_name(value) = nickname_of(value) or str(value)      # 只读映射，不创建身份、不改数据
```

- 建档时 `nickname` 已用外部显示名填过 → 正常情况下显示昵称；
- 查不到 → **原样返回入参**（不猜、不改数据、不编造 "UIDxxxx"）。

---

## 8. 剩下要你定的一个问题

- `msg` 通道给了一个**格式合法、但身份表里没有**的 meowid：建档（我当前实现）还是拒绝？

---

## 9. 执行计划（**不回滚，向前修**）

| 步 | 做什么 | 验收 |
|---|---|---|
| 1 | 本词表定稿（你划改） | 你点头 |
| 2 | 按 §3 映射表，逐文件把旧键改成新键 | 每改完一个文件，`grep` 旧名必须为 0 |
| 3 | 修建档/转正/记忆归属，使其符合 §4 §5 §6 | 每个通道打印真报文 |
| 4 | 五通道验收：语音 / 手机 / QQ私聊 / QQ群 / 弹幕 | 打印 `meowid + nickname + ext_account + ext_name + 记忆落点` |

**规则**：一次只改一个通道；改完先给你看真报文，再动下一个。
