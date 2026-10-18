# 直接联动 TradingView（不再用本地小图表）

扫盘页点一行、或者按一下 ↑↓，**你自己那个 TradingView 标签页**就原地换成对应品种。
不新开窗口、不重载布局、你画的趋势线/指标/周期全都还在——只是换成另一个币。

```
ticker（本地 127.0.0.1:1765x）  ──广播当前品种──▶  浏览器扩展  ──▶  你的 TradingView 标签页
```

- 点品种 → TV 换品种
- 扫盘页 ↑ / ↓（或 j / k）逐行 → TV 跟着逐个换
- PageUp / PageDown 翻 10 行、Home / End 到头、`/` 搜索，同样会带着 TV 一起走
- **悬浮扫盘条**：TV 在前台时按 `Ctrl+Alt+F` 叫出左边那条小面板，按住 ↓ 一路扫，TV 在右边自己换

实测一次切换 ~0.3 秒（扩展 1 秒轮询 + 立刻注入），URL 不变、页面不刷新。

---

## 一、安装扩展（只做一次，3 步）

1. 打开 Chrome（或 Edge），地址栏输入 `chrome://extensions`（Edge 是 `edge://extensions`）
2. 右上角打开 **开发者模式**
3. 点 **加载已解压的扩展程序**，选中这个文件夹：

   ```
   G:\mydeepseek\crypto-ticker\tv-ext
   ```

装好后工具栏会出现一个图标，点开就能看到「已连接 / 未连接、接口端口、最近一次切换的品种和结果」。

> 顺带说一句：Chrome 155 起**命令行**不允许 `--load-extension` 了（所以自动化测试里用 Edge 验证），
> 但像上面这样手动安装完全不受影响。

## 二、用起来

1. 正常启动 ticker（`python ticker.py` 或双击）。
   日志里会多一行：

   ```
   TradingView 联动接口已就绪: http://127.0.0.1:17653/（装上 tv-ext 扩展后，点品种/扫盘 ↑↓ 就会直接切 TV）
   ```

2. 浏览器里留一个 TradingView 图表标签页（`tradingview.com/chart/...`，登录不登录都行）。
3. 在 ticker 里点品种，或进扫盘页按 ↑↓ —— TV 就跟着切了。

**没有 TV 标签页时会自动开一个**（后台标签，带着当前品种），之后就一直复用它。

## 三、悬浮扫盘条（一边看 TV，一边按着 ↓ 连着切）

扫盘页毕竟是个浏览器标签页：焦点在 TV 上时箭头键归 TV，焦点回到网页上又看不见 K 线。
所以另做了一个**贴屏幕左边的置顶小条**，它自己拿着键盘焦点：

| 操作 | 效果 |
| --- | --- |
| `Ctrl+Alt+F`（或右键菜单「悬浮扫盘条」） | 叫出 / 收起（候选键 `Ctrl+Alt+D`、`Ctrl+Shift+Alt+F`） |
| ↓ / ↑ 或 j / k | 下一行 / 上一行，**按住不放会连续切**，TV 跟着连换 |
| PageDown / PageUp | 一次 10 行 |
| Home / End | 跳到第一个 / 最后一个 |
| 鼠标点某一行 / 滚轮 | 直接选到那个品种 / 滚 3 行 |
| 拖标题栏 | 挪位置（自动记住，下次还在原地） |
| Esc / `✕` | 关掉 |

几个细节：

- **宽度只有 236px**，贴在最左边，右边整块屏幕还是你的 TV，不挡图表。
- **它会把键盘焦点抢过来**（Windows 前台锁用 `AttachThreadInput` 绕过）——但不会把 TV 窗口最小化，
  扫完按回 TV 就继续画线。
- 再看一行：`TV 已连接` 绿点表示扩展在线；黄点说明没装扩展或浏览器没开。
- 位置和最后停在哪个品种记在 `config.json` 的 `"float_pos"` / `"float_sel"`。

## 四、开关

- 菜单：**联动 TradingView**（勾上/去掉）
- 配置文件 `config.json`：

  ```jsonc
  "tv_link": true    // false = 恢复成原来的本地小图表
  ```

关掉之后行为回到改造前：双击/点品种打开本地那个轻量图表页。

## 五、原理（想改代码时看）

- **ticker 侧**：`TVBridge`（`ticker.py` 里）在候选端口 `17653–17662` 里挑一个没被占的绑定，
  只暴露三个接口：
  - `/ping`：状态（端口、当前品种、序号）
  - `/next`：扩展轮询用，`seq` 变了才返回新符号（长轮询前的短轮询，1 秒一次）
  - `/state`：调试用
  端口用 `_BridgeServer`（`allow_reuse_address=False`）绑定——Windows 上默认的
  `SO_REUSEADDR` 是"抢占"而不是"复用"，两个实例会抢同一个口。
- **入口**：`set_chart_symbol()`（点扫盘/侧栏/悬浮条、双击）、`open_tradingview()`（双击/菜单打开图表）
  都先调 `tv_push(base, quote)` 广播，命中就直接返回，不再开本地图表页。
- **浮动条**：`ScanFloat`（`ticker.py` 里）是一个 `overrideredirect` + `-topmost` 的 Toplevel，
  自己 `bind("<Down>")` 等按键；每换一行调 `app.set_chart_symbol(base, quote, activate=False)`
  走同一条广播链路。`bring_front()` 负责抢焦点。
- **扩展侧**：`tv-ext/bg.js` 每秒轮询，拿到新符号后
  1. 优先 `chrome.scripting.executeScript(world:"MAIN")` 调 TV 页面里的
     `window._exposed_chartWidgetCollection.setSymbol("BINANCE:XXXUSDT.P")` —— **原地换品种**；
  2. 找不到注入点就兜底 `chrome.tabs.update(tabId, {url: ".../chart/?symbol=..."})` 整页重载。
- 符号格式与 ticker 内部一致：永续合约 `BINANCE:BTCUSDT.P`，现货 `BINANCE:BTCUSDT`
  （交易所由 `tv_exchange` 决定）。

## 六、排错

| 现象 | 处理 |
| --- | --- |
| 扩展显示「未连接」 | ticker 没启动；或 17653–17662 全被占用（看 ticker 日志里的实际端口） |
| 切了但 TV 不动 | 确认那个标签页是 `tradingview.com/chart/...`；刚打开的 TV 要等 1–2 秒加载完；扩展图标里看「最近一次」的错误 |
| 悬浮条按 ↓ 没反应 | 焦点在小条上吗（标题栏点一下）；看左下角小字是「TV 已连接」还是「未连接」 |
| 悬浮条不见了 | 可能被拖出屏幕了：删掉 `config.json` 里的 `"float_pos"`，或按 `Ctrl+Alt+F` 重新叫 |
| 想切别的交易所 | `config.json` 里 `"tv_exchange": "OKX"` 等，TV 符号会变成 `OKX:BTCUSDT.P` |
| 不想联动 | 菜单取消勾选「联动 TradingView」，或 `"tv_link": false` |

## 七、已知限制

- 秒级延迟：扩展 1 秒轮询一次（实测 0.3~0.4 秒内完成切换）。
- 只认 `/chart/` 页面，TV 首页/筛选器等页面不处理。
- 一个 ticker 实例对应浏览器里**一个** TV 标签页（优先上次切过的那个，其次当前激活的）。
- 只换品种，不改周期、不换布局；这些留在 TV 里由你自己管。
- 悬浮条一次只显示 8~30 行（按屏幕高度算），品种全靠按键扫，不做搜索框。
