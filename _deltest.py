# -*- coding: utf-8 -*-
"""行内图标（闹铃 + 垃圾桶）+ 图表页左侧扫盘栏。

注意：**删除已经改成单击生效**（用户明确说不要防误触了），
所以这里不再测"点两下确认"，只验证：
  1. 图标命中区（垃圾桶在最右、闹铃在它左边）
  2. 单击垃圾桶 → 直接删掉
  3. 单击闹铃   → 打开提醒弹窗
  4. 跨线程加/删自选不崩（HTTP 线程碰 Tk 会 RuntimeError）
  5. 图表页侧栏接口 /api/rankings、/api/pick
  6. 子线程安全

GUI 部分一律直接调 app 的方法，不模拟鼠标
（模拟输入受焦点/激活影响，极不可靠——见交接文档 §9）。
"""
import json
import threading
import time
import urllib.error
import urllib.request

import ticker

ORIG = ticker.load_config()
ORIG_SYMBOLS = list(ORIG.get("symbols", []))

cfg = dict(ORIG)
cfg["symbols"] = ["BTC", "ETH", "SOL", "XRP"]
cfg["show_del"] = True
cfg["show_alert"] = True
app = ticker.TickerApp(cfg)


def pump(ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


pump(900)
results = []


def check(label, cond, extra=""):
    results.append((label, bool(cond)))
    print(f"  {'✔' if cond else '✗'} {label}" + (f"   {extra}" if extra else ""))


print("\n── 行内图标：命中区 ────────────────────────────────")

app.render()
pump(200)
geom = app._icon_geom
bells = [g for g in geom if g[6] == "bell"]
dels = [g for g in geom if g[6] == "del"]
check("每行一个闹铃", len(bells) == 4, f"{len(bells)} 个")
check("每行一个垃圾桶", len(dels) == 4, f"{len(dels)} 个")
check("图标宽度合理",
      all(8 <= (g[5] - g[4]) <= 24 for g in geom),
      f"宽 {geom[0][5] - geom[0][4]:.0f}px" if geom else "")

row = [g for g in geom if g[2] == "ETH"]
bell = next(g for g in row if g[6] == "bell")
trash = next(g for g in row if g[6] == "del")
check("垃圾桶在最右", trash[4] > bell[4],
      f"闹铃 x={bell[4]:.0f}  垃圾桶 x={trash[4]:.0f}")
cy = (bell[0] + bell[1]) // 2
check("点闹铃 → bell",
      app._row_trash_at(int((bell[4] + bell[5]) / 2), cy) == ("ETH", "USDT", "bell"))
check("点垃圾桶 → del",
      app._row_trash_at(int((trash[4] + trash[5]) / 2), cy) == ("ETH", "USDT", "del"))
check("图标左边不是图标区",
      app._row_trash_at(int(bell[4]) - 14, cy) is None)
check("按 y 分行正确",
      app._row_trash_at(int((bell[4] + bell[5]) / 2), geom[-1][0] + 2) ==
      (geom[-1][2], geom[-1][3], geom[-1][6]))

print("\n── 开关：显隐图标 ──────────────────────────────────")
app.var_del.set(False)
app._toggle_del()
check("关掉垃圾桶后只剩闹铃",
      not any(g[6] == "del" for g in app._icon_geom))
app.var_del.set(True)
app._toggle_del()
check("重开后垃圾桶回来", any(g[6] == "del" for g in app._icon_geom))

print("\n── 单击垃圾桶：一下删掉（不再要点两下）────────────")
app.render()
pump(150)
n0 = len(app.cfg["symbols"])
app._on_icon_click("ETH", "USDT", "del")
pump(250)
check("一下就把 ETH 删掉了", "ETH" not in app.cfg["symbols"], f"{app.cfg['symbols']}")
check("自选少了一个", len(app.cfg["symbols"]) == n0 - 1)
check("配置已落盘", "ETH" not in ticker.load_config().get("symbols", []))
check("删掉的币行情也清了", ("ETH", "USDT") not in app.rows)
check("删不存在的品种返回 False", app.remove_symbol("NOTACOIN") is False)
check("删不存在的不改自选", len(app.cfg["symbols"]) == n0 - 1)
check("删完行数跟着变", len(app._icon_geom) == (n0 - 1) * 2,
      f"{len(app._icon_geom)} 个图标")

print("\n── 单击闹铃：打开提醒弹窗 ──────────────────────────")
app._on_icon_click("BTC", "USDT", "bell")
pump(300)
win = getattr(app, "_alert_win", None)
check("弹窗开出来了", win is not None and win.winfo_exists())
check("标题带品种", "BTC" in (win.title() if win else ""),
      win.title() if win else "")
check("有提醒列表控件", getattr(app, "_alert_list", None) is not None)
check("目标品种正确", app._alert_target == ("BTC", "USDT"), str(app._alert_target))
check("有邮箱设置入口（方法存在）", callable(getattr(app, "open_mail_settings", None)))
check("有菜单入口（方法存在）", callable(getattr(app, "open_alert_settings", None)))

# 再点另一个品种：应该切换而不是叠窗口
w1 = app._alert_win
app._on_icon_click("SOL", "USDT", "bell")
pump(250)
check("已开着时切品种而不是叠窗口",
      app._alert_win is w1 and app._alert_target == ("SOL", "USDT"),
      str(app._alert_target))
try:
    app._alert_win.destroy()
except Exception:
    pass
app._alert_win = None

print("\n── 回归：原有功能没被弄坏 ──────────────────────────")

# ★ 跨线程加自选不能崩（HTTP 线程碰 Tk 会 RuntimeError）
print("   （从子线程加/删自选——跨线程回归）")
app.cfg["symbols"] = ["BTC", "ETH", "SOL"]
app.pairs = ticker.build_pairs(app.cfg["symbols"], "USDT")
app.render()
pump(200)

err = []
n0 = len(app.cfg["symbols"])


def _bg_add():
    try:
        app.add_symbol("DOGE")
    except Exception as exc:                      # noqa: BLE001
        err.append(repr(exc))


t = threading.Thread(target=_bg_add)
t.start()
t.join(timeout=10)
pump(500)
check("子线程加自选不抛异常", not err, str(err))
check("子线程加自选真的写进去了", len(app.cfg["symbols"]) == n0 + 1,
      f"{app.cfg['symbols']}")


def _bg_del():
    try:
        app.remove_symbol("DOGE")
    except Exception as exc:                      # noqa: BLE001
        err.append(repr(exc))


t2 = threading.Thread(target=_bg_del)
t2.start()
t2.join(timeout=10)
pump(500)
check("子线程删自选不抛异常", not err, str(err))
check("子线程删自选生效", "DOGE" not in app.cfg["symbols"])

print("\n── 图表页侧栏接口 ──────────────────────────────────")
port = app._chart_server.start()
check("图表页服务已启动", port > 0, f"端口 {port}")
base_url = app._chart_server.url

with urllib.request.urlopen(base_url, timeout=5) as r:
    html = r.read().decode("utf-8")
check("页面有侧边栏", 'id="side"' in html and 'id="groups"' in html)
check("侧栏有刷新入口", 'id="rf"' in html)
check("只有单击切图，双击也不加自选",
      "pick(b)" in html and "'add'" not in html and "ctrlKey" not in html)
check("榜单轮询", "setInterval(loadSide" in html and "/api/rankings" in html)

WATCHED = app.cfg["symbols"][0].upper()
app._market_overview = {
    "topGainers": [{"base": "AAA", "change": 12.5}, {"base": "BBB", "change": 9.1}],
    "topLosers": [{"base": "CCC", "change": -8.3}],
    "topVolume": [{"base": WATCHED, "change": -1.2}],
    "topOI": [{"base": "DDD", "change": 28.7}],
}
with urllib.request.urlopen(base_url + "api/rankings", timeout=5) as r:
    rk = json.loads(r.read().decode("utf-8"))
labels = [g["label"] for g in rk["groups"]]
check("返回 4 组榜单", len(rk["groups"]) == 4, str(labels))
check("组名正确",
      labels == ["涨幅前十", "跌幅前十", "成交量前十", "增仓前十"], str(labels))
check("条目含 base/change/inWatch",
      set(rk["groups"][0]["items"][0].keys()) == {"base", "change", "inWatch"})
vol = [g for g in rk["groups"] if g["key"] == "topVolume"][0]
check("自选里的币标了 inWatch", vol["items"][0]["inWatch"] is True)
check("不在自选的没标", rk["groups"][0]["items"][0]["inWatch"] is False)

app.cfg["show_oi"] = False
with urllib.request.urlopen(base_url + "api/rankings", timeout=5) as r:
    rk2 = json.loads(r.read().decode("utf-8"))
check("关掉持仓榜后剩 3 组", len(rk2["groups"]) == 3)
app.cfg["show_oi"] = True

t0 = time.time()
for _ in range(10):
    urllib.request.urlopen(base_url + "api/rankings", timeout=5).read()
dt = (time.time() - t0) / 10 * 1000
check("榜单接口不阻塞（内存直读）", dt < 60, f"平均 {dt:.0f}ms")

app._chart_target = ("BTC", "USDT")
app._chart_poll_at = time.time()          # 假装页面开着，别去开浏览器
with urllib.request.urlopen(base_url + "api/pick?base=SOL&mode=chart", timeout=5) as r:
    pk = json.loads(r.read().decode("utf-8"))
check("pick 切图表成功", pk.get("ok") is True and pk.get("mode") == "chart")
check("图表品种真的切了", app._chart_target[0] == "SOL", str(app._chart_target))

# ★ 侧栏的"加自选"能力已经**从接口上删掉**了（用户要求双击不动观察列表）
#   直接打这个接口也必须加不进去
n_before = len(app.cfg["symbols"])
with urllib.request.urlopen(base_url + "api/pick?base=DOGE&mode=add", timeout=5) as r:
    pk2 = json.loads(r.read().decode("utf-8"))
check("已经不支持 mode=add 加自选", pk2.get("ok") is False, str(pk2))
check("自选没有被改动", len(app.cfg["symbols"]) == n_before,
      f"{app.cfg['symbols']}")

with urllib.request.urlopen(base_url + "api/pick?base=&mode=chart", timeout=5) as r:
    pk3 = json.loads(r.read().decode("utf-8"))
check("空 base 安全返回", pk3.get("ok") is False)

try:
    urllib.request.urlopen(base_url + "nope", timeout=5)
    check("未知路径返回 404", False)
except urllib.error.HTTPError as exc:
    check("未知路径返回 404", exc.code == 404)

# 只剩一个币时删掉不能崩
app.cfg["symbols"] = ["BTC"]
app.pairs = ticker.build_pairs(app.cfg["symbols"], "USDT")
app.render()
app._chart_target = ("BTC", "USDT")
app.remove_symbol("BTC")
check("删到空自选不崩", app.cfg["symbols"] == [])
check("空自选后 _chart_target 没被改坏",
      isinstance(app._chart_target, tuple) and len(app._chart_target) == 2)

app._chart_server.stop()

# ── 收尾：还原配置 ──
restore = ticker.load_config()
restore["symbols"] = ORIG_SYMBOLS
restore["show_del"] = ORIG.get("show_del", False)
restore["show_alert"] = ORIG.get("show_alert", True)
ticker.save_config(restore)
app.quit()

print()
passed = sum(1 for _l, ok in results if ok)
print(f"{passed}/{len(results)} 项通过")
if passed != len(results):
    for label, ok in results:
        if not ok:
            print(f"  未通过: {label}")
    raise SystemExit(1)
