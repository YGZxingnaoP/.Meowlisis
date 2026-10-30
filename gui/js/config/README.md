# 配置面板约定

## 入口

所有面板在 `registry.js` 注册，在 `panels.js` 声明；`App.onPlanetClick` / `App.onToolboxPlanetClick` / 高级设置都只调用 `ConfigPanels.open(id)`。

新增面板：

```js
panel('my_panel', '我的面板', '工具箱', {
    fields: [
        { type: 'section', label: '基础' },
        { type: 'number', path: 'my.key', label: '数值', default: 1, min: 0, max: 10, step: 1,
          help: '这个数值影响什么。' },
        { type: 'check', path: 'my.enabled', label: '启用', default: true, help: '关闭后……' },
    ],
});
```

复杂面板（异步加载、独立保存接口、自定义控件）用 `open`：

```js
panel('my_async_panel', '我的异步面板', '工具箱', {
    open: () => App.openMyAsyncPanel(),
});
```

普通面板用 `render` 挂现有函数：

```js
panel('my_legacy', '旧面板', '工具箱', { render: () => Config.myLegacy() });
```

需要异步数据或额外保存步骤时：

```js
panel('my_panel', '我的面板', '工具箱', {
    load: () => API.getMyData(),          // 结果放进 panel.data，供 custom 字段使用
    fields: [...],
    save: async () => {
        const updates = Config.collectValues();
        Config.applyUpdates(updates, App.config);
        await API.saveConfig(App.config);
        await API.saveMyData();
        App.showToast('已保存');
    },
});
```

`fields` 面板默认走 `_openConfigPanel` 的标准保存；有 `save` 时优先用 `save`。

## 字段类型

| type | 说明 |
|---|---|
| `text` | 文本 |
| `password` | 密码；`.api_key` / `.base_url` 会自动隐藏，统一到 API 平台 |
| `number` / `num` | 数字；声明 `min/max/step` |
| `check` / `checkbox` | 布尔 |
| `select` | `options: [{value,label}]` |
| `area` | 多行文本 |
| `list` | 逗号分隔列表 |
| `section` | 分区标题 |
| `fold` | 折叠块；`fields` 递归 |
| `tabs` | 页签；`tabs: [{id,label,fields}]` |
| `custom` | 自定义 widget；`render()` 返回 HTML |

字段必须有 `path`、`label`、`default`；建议所有说明写 `help`。中文 label/help 需要补 `locales/en.js`。

## 凭据

不要在普通面板里声明 `.api_key` / `.base_url`。所有凭据节点登记在 `credentials.js`，由「基本设置 → API」统一渲染；`Config._text/_password` 会自动隐藏普通面板里的凭据字段。

## 复杂控件

参考音频、VTS 表情、数据库来源、CatPaws 等无法通用化的控件，保留为 `open`/`custom`，但不要再新增一套面板 ID/路由；路由统一走 `ConfigPanels`。

## 检查

- `node --check` 所有改动的 JS；
- 面板 ID 与 `advanced.js` / `orbit/data.js` 对齐；
- `gui/tools/check_i18n.py` 无新增缺失、无重复 key；
- 保存后 `config.yml` 路径不变。
