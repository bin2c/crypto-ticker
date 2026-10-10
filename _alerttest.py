# -*- coding: utf-8 -*-
"""价格提醒：引擎逻辑 + 行内图标（闹铃/垃圾桶单击）。

不联网、不发真通知（把 _deliver 换掉），只验证**判定逻辑**：
  1. 上破 / 下破 的方向判定
  2. 一次性提醒触发后自动停用
  3. 反复提醒：触发后不重复轰炸，价格回到另一侧才重新武装
  4. 改价格/方向要重新武装
  5. 删除、按品种查询
  6. 行尾图标命中区（闹铃在左、垃圾桶在右），两个都是**单击**生效
"""
import time

import ticker

cfg = ticker.load_config()
cfg["symbols"] = ["BTC", "ETH", "SOL"]
cfg["show_del"] = True
cfg["show_alert"] = True
app = ticker.TickerApp(cfg)

results = []


def check(label, cond, extra=""):
    results.append((label, bool(cond)))
    print(f"  {'✔' if cond else '✗'} {label}" + (f"   {extra}" if extra else ""))


def pump(ms=250):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


pump(700)

# 把"发送"这一步替换掉，避免测试时真的弹窗/发邮件
sent = []
app._alerts._deliver = lambda a: sent.append(dict(a))

eng = app._alerts

print("\n── 提醒引擎：方向判定 ──────────────────────────")
a1 = eng.add("BTC", "USDT", 90000, "above", repeat=False)
a2 = eng.add("ETH", "USDT", 2000, "below", repeat=False)

fired = eng.check({("BTC", "USDT"): {"price": 89000}, ("ETH", "USDT"): {"price": 2100}})
check("都没到价 → 不触发", len(fired) == 0, f"触发 {len(fired)} 条")

fired = eng.check({("BTC", "USDT"): {"price": 90000}, ("ETH", "USDT"): {"price": 2100}})
check("BTC 恰好等于目标价也算上破", len(fired) == 1 and fired[0]["base"] == "BTC",
      f"{[f['base'] for f in fired]}")

fired = eng.check({("BTC", "USDT"): {"price": 91000}, ("ETH", "USDT"): {"price": 1950}})
check("ETH 下破触发", len(fired) == 1 and fired[0]["base"] == "ETH",
      f"{[f['base'] for f in fired]}")

check("一次性提醒触发后自动停用",
      not next(a for a in eng.all() if a["id"] == a1["id"])["enabled"])

print("\n── 提醒引擎：反复提醒的重新武装 ──────────────────")
b1 = eng.add("SOL", "USDT", 200, "above", repeat=True)
fired = eng.check({("SOL", "USDT"): {"price": 205}})
check("第一次上破触发", len(fired) == 1 and fired[0]["fire_count"] == 1)

fired = eng.check({("SOL", "USDT"): {"price": 210}})
check("还在目标价上方 → 不重复触发", len(fired) == 0)

fired = eng.check({("SOL", "USDT"): {"price": 199}})
check("回到下方 → 不触发（只是重新武装）", len(fired) == 0)
check("重新武装后 triggered 归位",
      next(a for a in eng.all() if a["id"] == b1["id"])["triggered"] is False)

fired = eng.check({("SOL", "USDT"): {"price": 201}})
check("再次上破 → 第二次触发", len(fired) == 1 and fired[0]["fire_count"] == 2,
      f"fire_count={fired[0]['fire_count'] if fired else '-'}")

print("\n── 提醒引擎：修改与删除 ────────────────────────")
eng.update(b1["id"], price=300)
check("改价格后重新武装",
      next(a for a in eng.all() if a["id"] == b1["id"])["triggered"] is False)
fired = eng.check({("SOL", "USDT"): {"price": 250}})
check("改成 300 后 250 不触发", len(fired) == 0)
fired = eng.check({("SOL", "USDT"): {"price": 305}})
check("到 305 才触发", len(fired) == 1)

before = len(eng.all())
eng.remove(b1["id"])
check("删除生效", len(eng.all()) == before - 1)

eng.add("BTC", "USDT", 1, "above")
eng.add("BTC", "USDT", 2, "above")
# 注意：前面那条一次性 BTC 提醒触发后只是**停用**（enabled=False），并没有被删掉，
# 所以这里 BTC 一共有 3 条 —— 别把它漏算成 2。
n = eng.clear_symbol("BTC")
check("按品种批量清掉", n == 3 and len(eng.for_symbol("BTC")) == 0, f"清掉 {n} 条")

print("\n── 提醒引擎：停用的不触发 ──────────────────────")
c1 = eng.add("ETH", "USDT", 1, "above")
eng.update(c1["id"], enabled=False)
fired = eng.check({("ETH", "USDT"): {"price": 99999}})
check("停用后不触发", all(f["id"] != c1["id"] for f in fired))

print("\n── 行内图标：命中区与单击语义 ──────────────────")
app.render()
pump(200)
geom = app._icon_geom
bells = [g for g in geom if g[6] == "bell"]
dels = [g for g in geom if g[6] == "del"]
check("每行都有一个闹铃", len(bells) == 3, f"{len(bells)} 个")
check("每行都有一个垃圾桶", len(dels) == 3, f"{len(dels)} 个")

row0 = [g for g in geom if g[2] == "BTC"]
bell0 = next(g for g in row0 if g[6] == "bell")
del0 = next(g for g in row0 if g[6] == "del")
check("垃圾桶在最右、闹铃在它左边", del0[4] > bell0[4],
      f"闹铃 x={bell0[4]:.0f}  垃圾桶 x={del0[4]:.0f}")

cy = (bell0[0] + bell0[1]) // 2
hit = app._row_trash_at(int((bell0[4] + bell0[5]) / 2), cy)
check("点闹铃命中 bell", hit == ("BTC", "USDT", "bell"), f"{hit}")
hit = app._row_trash_at(int((del0[4] + del0[5]) / 2), cy)
check("点垃圾桶命中 del", hit == ("BTC", "USDT", "del"), f"{hit}")

print("\n── 单击语义：垃圾桶一下删掉（不再要点两下）──")
n_before = len(app.cfg["symbols"])
app._on_icon_click("BTC", "USDT", "del")
pump(250)
check("一下就把 BTC 删了", "BTC" not in app.cfg["symbols"],
      f"{app.cfg['symbols']}")
check("自选少了一个", len(app.cfg["symbols"]) == n_before - 1)

print("\n── 单击语义：闹铃一下打开设置弹窗 ──────────────")
app._on_icon_click("ETH", "USDT", "bell")
pump(300)
win = getattr(app, "_alert_win", None)
check("弹窗开出来了", win is not None and win.winfo_exists())
check("弹窗标题带上了品种", "ETH" in win.title(), win.title())
check("弹窗里有提醒列表", getattr(app, "_alert_list", None) is not None)
check("目标品种正确", app._alert_target == ("ETH", "USDT"), str(app._alert_target))

print("\n── 闹铃点亮：有提醒的品种铃铛变色 ──────────────")
eng.add("ETH", "USDT", 12345, "above")
app.render()
pump(200)
check("symbol_set 里有 ETH", "ETH|USDT" in eng.symbol_set(), str(eng.symbol_set()))

# 关掉弹窗，别影响后面
try:
    app._alert_win.destroy()
except Exception:
    pass
app._alert_win = None

print("\n── 关闭开关后不再画图标 ────────────────────────")
app.var_alert.set(False)
app._toggle_alert()
check("关掉闹铃后只剩垃圾桶", not any(g[6] == "bell" for g in app._icon_geom))
app.var_alert.set(True)
app._toggle_alert()
check("重新打开后闹铃回来", any(g[6] == "bell" for g in app._icon_geom))

# 还原
app.cfg["symbols"] = ["BTC", "ETH", "SOL"]
ticker.save_config(app.cfg)
app.quit()

print()
passed = sum(1 for _l, ok in results if ok)
print(f"{passed}/{len(results)} 项通过")
if passed != len(results):
    for label, ok in results:
        if not ok:
            print(f"  未通过: {label}")
    raise SystemExit(1)
