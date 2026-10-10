# -*- coding: utf-8 -*-
"""验证本地图表页：一个常驻页面，切换品种时原地换图。"""
import json
import time
import urllib.request

import ticker

cfg = ticker.load_config()
cfg["symbols"] = ["BTC", "ETH", "SOL"]
app = ticker.TickerApp(cfg)


def pump(ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


pump(1200)
results = []


def check(label, cond, extra=""):
    results.append((label, bool(cond)))
    print(f"  {'✔' if cond else '✗'} {label}" + (f"   {extra}" if extra else ""))


port = app._chart_server.start()
check("图表页服务已启动", port > 0, f"端口 {port}")
base = app._chart_server.url
print(f"     {base}")

# 1) 首页是本地的 lightweight-charts 页面（不再依赖 TradingView 渲染）
with urllib.request.urlopen(base, timeout=5) as r:
    html = r.read().decode("utf-8")
    ctype = r.headers.get("Content-Type", "")
check("首页返回 HTML", "text/html" in ctype and "lightweight-charts" in html)
check("页面引用本地图表库", 'src="/lib/lightweight-charts.js"' in html)
check("页面每秒轮询", "setInterval(tick, 1000)" in html)

# 1b) 本地库能取到，而且是真库
with urllib.request.urlopen(base + "lib/lightweight-charts.js", timeout=10) as r:
    lib = r.read()
check("本地图表库可取", len(lib) > 100000, f"{len(lib)/1024:.0f} KB")
check("是 lightweight-charts",
      b"Lightweight Charts" in lib[:200], lib[:60].decode("utf-8", "replace"))

# 1c) K 线接口
with urllib.request.urlopen(base + "api/klines?interval=1h&limit=50", timeout=25) as r:
    kl = json.loads(r.read().decode("utf-8"))
check("K 线接口返回数据", isinstance(kl, list) and len(kl) == 50,
      f"{len(kl)} 根，首根 {kl[0][:5] if kl else '空'}")

# 1d) 周期切换：4h 和 1h 必须给出不同的K线时间间隔
with urllib.request.urlopen(base + "api/klines?interval=4h&limit=20", timeout=25) as r:
    k4 = json.loads(r.read().decode("utf-8"))
with urllib.request.urlopen(base + "api/klines?interval=1h&limit=20", timeout=25) as r:
    k1 = json.loads(r.read().decode("utf-8"))
gap4 = (k4[1][0] - k4[0][0]) / 3600000 if len(k4) > 1 else 0
gap1 = (k1[1][0] - k1[0][0]) / 3600000 if len(k1) > 1 else 0
check("4h 周期间隔正确", gap4 == 4, f"相邻K线间隔 {gap4:.0f} 小时")
check("1h 周期间隔正确", gap1 == 1, f"相邻K线间隔 {gap1:.0f} 小时")

# 周线 / 月线（注意币安 1m=分钟、1M=月，大小写语义不同）
with urllib.request.urlopen(base + "api/klines?interval=1w&limit=10", timeout=25) as r:
    kw = json.loads(r.read().decode("utf-8"))
with urllib.request.urlopen(base + "api/klines?interval=1M&limit=10", timeout=25) as r:
    km = json.loads(r.read().decode("utf-8"))
with urllib.request.urlopen(base + "api/klines?interval=1m&limit=10", timeout=25) as r:
    kmin = json.loads(r.read().decode("utf-8"))
gapw = (kw[1][0] - kw[0][0]) / 3600000 if len(kw) > 1 else 0
gapM = (km[1][0] - km[0][0]) / 3600000 if len(km) > 1 else 0
gapm = (kmin[1][0] - kmin[0][0]) / 60000 if len(kmin) > 1 else 0
check("周线 1w 间隔 168 小时", gapw == 168, f"{gapw:.0f} 小时")
check("月线 1M 是 30 天左右", 670 <= gapM <= 750, f"{gapM:.0f} 小时")
check("1m 是一分钟（大小写没搞混）", gapm == 1, f"{gapm:.0f} 分钟")
check("页面有周线月线按钮", "'1w'" in html and "'1M'" in html)

# 1e) 非法周期要被拒掉（不能把任意字符串透传给币安）
with urllib.request.urlopen(base + "api/klines?interval=../etc&limit=5", timeout=25) as r:
    bad = json.loads(r.read().decode("utf-8"))
check("非法周期回退到 1h", isinstance(bad, list) and len(bad) > 0
      and (bad[1][0] - bad[0][0]) / 3600000 == 1, f"{len(bad)} 根")

# 1f) 页面要有周期按钮
check("页面含周期切换", 'INTERVALS' in html and "chartInterval" in html)

# 2) 接口返回当前品种（新版不做网络请求，必须很快）
t0 = time.time()
with urllib.request.urlopen(base + "api/symbol", timeout=15) as r:
    data = json.loads(r.read().decode("utf-8"))
dt = (time.time() - t0) * 1000
check("接口返回当前品种", data.get("base") == "BTC" and "key" in data, str(data))
check("symbol 接口不再走网络（应 <300ms）", dt < 300, f"{dt:.0f}ms")

# 3) 切换品种后接口立刻变
app._chart_target = ("SOL", "USDT")
with urllib.request.urlopen(base + "api/symbol", timeout=15) as r:
    data2 = json.loads(r.read().decode("utf-8"))
check("切品种后接口变了", data2.get("base") == "SOL", f"{data} -> {data2}")

# 4) 中文币的 K 线也能取到（图表现已不依赖 TradingView 拼音）
app._chart_target = ("龙虾", "USDT")
with urllib.request.urlopen(base + "api/klines?interval=1h&limit=20", timeout=25) as r:
    cnkl = json.loads(r.read().decode("utf-8"))
check("中文币 K 线可取", isinstance(cnkl, list) and len(cnkl) == 20,
      f"{len(cnkl)} 根，收盘 {cnkl[0][4] if cnkl else '空'}")

# 5) TradingView 链接按需解析（中文币要反查拼音）
with urllib.request.urlopen(base + "api/tvurl", timeout=25) as r:
    tv = json.loads(r.read().decode("utf-8"))
print(f"     龙虾 TradingView 链接: {tv.get('url')}")
check("中文币 TradingView 链接解析成拼音",
      "LONGXIAUSDT.P" in (tv.get("url") or ""), str(tv))

# 5b) 英文币不该被改写
app._chart_target = ("1000PEPE", "USDT")
app._tv_symbols.clear()
with urllib.request.urlopen(base + "api/tvurl", timeout=25) as r:
    tv2 = json.loads(r.read().decode("utf-8"))
check("英文币链接不变",
      "1000PEPEUSDT.P" in (tv2.get("url") or ""), str(tv2))

# 6) 轮询时间被记录（用来判断页面是否还开着）
before = app._chart_poll_at
time.sleep(0.05)
urllib.request.urlopen(base + "api/symbol", timeout=15).read()
check("记录了页面轮询时间", app._chart_poll_at > before)

# 7) 不存在的路径返回 404
try:
    urllib.request.urlopen(base + "nope", timeout=5)
    check("未知路径返回 404", False)
except urllib.error.HTTPError as exc:
    check("未知路径返回 404", exc.code == 404)

# 8) 只监听本机回环，不对外
check("只绑定回环地址",
      app._chart_server._httpd.server_address[0] == "127.0.0.1",
      str(app._chart_server._httpd.server_address))

app._chart_server.stop()
app.cfg["symbols"] = ["BTC", "ETH", "SOL"]
ticker.save_config(app.cfg)
app.quit()

print()
passed = sum(1 for _l, ok in results if ok)
print(f"{passed}/{len(results)} 项通过")
if passed != len(results):
    raise SystemExit(1)
