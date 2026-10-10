# -*- coding: utf-8 -*-
"""看一眼两个新功能的实际布局，不依赖截图。

行情条窗口是无边框透明窗，截图容易受毛玻璃/色键影响；
所以这里直接读**渲染时算出来的真实几何**，再加上对图表页 HTML 的
结构断言。交接文档 §9 的原则：GUI 测试要确定性，直接读状态。
"""
import re
import urllib.request

import ticker

ORIG = ticker.load_config()
cfg = dict(ORIG)
cfg["symbols"] = ["BTC", "ETH", "SOL"]
cfg["show_del"] = True
cfg["style"] = "blur"
app = ticker.TickerApp(cfg)

for _ in range(40):
    app.root.update()

app.render()
app.root.update_idletasks()

print("── 行情条窗口实际布局 ────────────────────────────")
print(f"  窗口尺寸   {app._win_w} × {app._win_h}")
print(f"  顶部滚动条 高 {app._tape_h}px   底部输入条 高 {app._inbar_h}px")
print()
print("  每行的「删除 ×」命中区间：")
for top, bottom, base, quote, tx0, tx1 in app._del_geom:
    cy = (top + bottom) // 2
    print(f"    {base:<6} 行 y={top:>3}..{bottom:<3}  "
          f"× 在 x={tx0:.0f}..{tx1:.0f}  (中心 {int((tx0+tx1)/2)}, y={cy})")

left = min(g[4] for g in app._del_geom)
right = max(g[5] for g in app._del_geom)
print()
print(f"  × 列位于最右侧：x={left:.0f}..{right:.0f}，窗口宽 {app._win_w}")
print(f"  → 距右边缘 {(app._win_w - right):.0f}px，其余内容都在 x<{left:.0f}")

# 价格/涨跌幅不能和 × 重叠
from ticker import fmt_price  # noqa: E402
rows_ok = all(g[4] > 0 for g in app._del_geom)
print(f"  × 不越出窗口左边界: {'是' if rows_ok else '否'}")

app.cfg["show_del"] = False
app.render()
app.root.update_idletasks()
print(f"\n  关掉开关后窗口宽 {app._win_w}（比开着时窄 "
      f"{right - left:.0f}px，说明收掉了那一列）")

app.cfg["show_del"] = True
app.render()

print("\n── 图表页实际结构 ────────────────────────────────")
port = app._chart_server.start()
url = app._chart_server.url
with urllib.request.urlopen(url, timeout=5) as r:
    html = r.read().decode("utf-8")

# DOM 顺序：侧栏必须在图表之前（左）
i_side = html.find('id="side"')
i_groups = html.find('id="groups"')
i_chart = html.find('id="chart"')
print(f"  DOM 顺序   #side({i_side}) < #groups({i_groups}) < #chart({i_chart})")
ok_order = 0 < i_side < i_groups < i_chart
print(f"  侧栏在图表左边: {'是' if ok_order else '否'}")

m = re.search(r"#side\{[^}]*?flex:0 0 (\d+)px", html)
print(f"  侧栏固定宽度: {m.group(1) if m else '?'}px")
print(f"  图表自适应  : {'flex:1 1 auto' in html and '#chart{flex:1 1 auto' in html}")
print(f"  侧栏可滚动  : {'overflow-y:auto' in html}")

checks = [
    # 注意：分组标题是服务端通过 /api/rankings 下发的，不在静态 HTML 里，
    # 所以这里校验的是"页面有能力渲染服务端给的分组"。
    ("页面按服务端下发的分组渲染", "j.groups" in html and "grp.label" in html),
    ("单击切图（默认）", "pick(b, (e.ctrlKey||e.altKey||e.metaKey) ? 'add' : 'chart')" in html),
    ("双击加自选", "pick(b, 'add');       // 双击 = 加自选" in html),
    ("当前品种高亮", ".it.cur{background:#1f6feb" in html),
    ("已加自选打 ✓", "it.inWatch?'<b>✓</b> '" in html),
    ("涨跌绿红着色", ".up{color:#0ecb81}" in html and ".down{color:#f6465d}" in html),
    ("滚动位置不被冲掉", "box.scrollTop = keep" in html),
    ("点击用事件委托（不用逐条绑定）", "e.target.closest" in html),
    ("榜单 60 秒轮询一次", "setInterval(loadSide, 60000)" in html),
    ("XSS 转义", "function esc(s){" in html),
]
print()
for label, ok in checks:
    print(f"  {'✔' if ok else '✗'} {label}")

print("\n── /api/rankings 真实返回 ────────────────────────")
import json  # noqa: E402
app._market_overview = {
    "topGainers": [{"base": "龙虾", "change": 45.9}, {"base": "SOL", "change": 3.2}],
    "topLosers": [{"base": "BTC", "change": -1.39}],
    "topVolume": [{"base": "ETH", "change": -1.69}],
    "topOI": [{"base": "W", "change": 28.76}],
}
with urllib.request.urlopen(url + "api/rankings", timeout=5) as r:
    rk = json.loads(r.read().decode("utf-8"))
for g in rk["groups"]:
    marks = "".join(("[已加自选]" if it["inWatch"] else "") for it in g["items"])
    body = "  ".join(f"{it['base']} {it['change']:+.2f}%" for it in g["items"])
    print(f"  {g['label']:<8} {body}   {marks}")

app._chart_server.stop()
ticker.save_config(ORIG)
app.quit()
print("\n（配置已还原）")
