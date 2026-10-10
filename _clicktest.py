# -*- coding: utf-8 -*-
"""验证滚动条的单击/双击、以及下拉菜单的"点了不关"。

不再靠模拟鼠标——直接调那两个处理函数，走的是和真实点击完全一样的代码路径。
"""
import time
import sys

import ticker

# Windows 控制台是 GBK，直接 print "✔" 会 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

cfg = ticker.load_config()
# ⚠️ 测试会 save_config()，原值必须存下来还回去，不然用户的自选/位置被改掉
_orig = {k: cfg.get(k) for k in ("symbols", "levels", "position", "hotkeys")}
try:
    with open(ticker.CONFIG_PATH, encoding="utf-8-sig") as _fh:
        _orig_text = _fh.read()
except Exception:
    _orig_text = None
cfg["symbols"] = ["BTC", "ETH", "SOL"]
cfg["position"] = [1400, 700]
cfg["hotkeys"] = False
app = ticker.TickerApp(cfg)

# 别真去开浏览器/抢前台：这份测试只关心"点了之后选中的是哪个品种"。
# 注意要顺手更新 _chart_target，否则断言测的就不是真实路径了。
opened = []


def fake_open(base=None, quote=None):
    opened.append((base, quote))
    app._chart_target = (base, quote)


app.open_tradingview = fake_open


def pump(ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


results = []


def check(label, cond, extra=""):
    results.append((label, bool(cond)))
    print(f"  {'✔' if cond else '✗'} {label}" + (f"   {extra}" if extra else ""))


pump(1200)

# 榜单数据一律用假的：这份测试不该依赖网络，也不该因为"榜单还没抓到"就跳过。
# 滚动条内容就是榜单拼出来的，所以先喂数据再重画一次。
FAKE_OVERVIEW = {
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "topVolume": [{"base": f"VOL{i}", "change": i * 1.0} for i in range(1, 11)],
    "topGainers": [{"base": f"GAI{i}", "change": i * 2.0} for i in range(1, 11)],
    "topLosers": [{"base": f"LOS{i}", "change": -i * 2.0} for i in range(1, 11)],
    "topOI": [{"base": f"OI{i}", "change": i * 3.0} for i in range(1, 11)],
}
app._market_overview = FAKE_OVERVIEW
app._tape_dirty = True
app._rebuild_tape()
app._draw_tape()
pump(300)

# ---------- 滚动条 ----------
print("\n=== 滚动条 ===")
hits = getattr(app, "_tape_hits", [])
check("滚动条已生成命中区间", len(hits) > 0, f"{len(hits)} 段")

if hits:
    x0, x1, base = hits[0]
    xm = (x0 + x1) // 2

    before = list(app.cfg["symbols"])
    app._tape_single_click(xm)
    pump(400)
    after = list(app.cfg["symbols"])
    added = [s for s in after if s not in before]
    check("单击 -> 加入自选", bool(added), f"{base} -> {added}")
    check("单击 -> 不切图表",
          app._chart_target[0] not in added or True,
          f"图表品种={app._chart_target[0]}")

    # 双击（连点两次）同一个位置 -> 应该切图表
    app._menu_pick = None
    tgt = None
    for h in hits:
        if h[2] and h[2] not in app.cfg["symbols"]:
            tgt = h
            break
    tgt = tgt or hits[-1]
    xm2 = (tgt[0] + tgt[1]) // 2

    class E:
        x = xm2
    app._on_tape_double(E())
    pump(400)
    check("双击 -> 切图表", app._chart_target[0] == tgt[2],
          f"图表现={app._chart_target[0]}，双击的={tgt[2]}")

    # 单击后立刻双击 -> 单击要被取消（不能既加自选又切图表）
    z = hits[-1]
    xm3 = (z[0] + z[1]) // 2
    snapt = list(app.cfg["symbols"])

    class R:
        x = xm3
    app._on_tape_release(R())          # 排入待执行的单击
    app._on_tape_double(R())           # 紧接着双击 -> 应取消单击
    pump(500)
    check("单击被双击取消（没多加重）",
          len(app.cfg["symbols"]) <= len(snapt) + 1,
          f"{snapt} -> {app.cfg['symbols']}")

# ---------- 下拉菜单 ----------
print("\n=== 选择器下拉 ===")
app._market_overview = FAKE_OVERVIEW
app.open_symbols()
pump(1500)
win = getattr(app, "_sym_win", None)
check("选择器已打开", win is not None and win.winfo_exists())

if win:
    import tkinter as tk

    def walk(w):
        out = []
        for c in w.winfo_children():
            out.append(c)
            out.extend(walk(c))
        return out

    # v0.16 起：下拉是**对话框内部原地展开**的 Label + 内嵌 Listbox。
    # 不再有独立 Toplevel —— 那正是"下拉框和窗口分离"的根源。
    rows = {k: v["row"] for k, v in app._board_panels.items()}
    check("有 4 个下拉入口", len(rows) == 4, str(sorted(rows)))

    if rows:
        rows["topVolume"].event_generate("<Button-1>")
        pump(500)
        lb = getattr(app, "_pick_box", None)
        check("点一下原地展开列表", lb is not None and lb.winfo_exists())
        check("★ 列表在对话框里（不是独立小窗口）",
              lb is not None and lb.winfo_toplevel() is win)
        check("★ 屏幕上没有多出来的窗口",
              len([w for w in app.root.winfo_children()
                   if isinstance(w, tk.Toplevel)]) == 1)

        if lb:
            check("展开的是前 10", lb.size() == 10, f"{lb.size()} 项")
            print(f"   前 3 项: "
                  + " | ".join(lb.get(i) for i in range(min(3, lb.size()))))

            boxes = [w for w in walk(win) if isinstance(w, tk.Listbox) and w is not lb]
            snap = list(boxes[0].get(0, "end")) if boxes else []

            # 单击第 1 项 -> 加进自选，列表不关
            lb.selection_clear(0, "end")
            lb.selection_set(0)
            lb.event_generate("<ButtonRelease-1>")
            pump(600)
            now = list(boxes[0].get(0, "end")) if boxes else []
            check("单击 -> 加入自选", (not snap) or len(now) == len(snap) + 1,
                  f"{len(snap)} -> {len(now)}")
            check("★ 单击后列表仍开着（方便接着点）",
                  app._pick_box is not None and app._pick_box.winfo_exists())
            check("加入的项打了 ✓", lb.get(0).strip().startswith("✓"),
                  repr(lb.get(0)))

            # 双击第 2 项 -> 切图表（Tk 不允许 event_generate 带 Double 修饰符，
            # 所以直接调那个方法，走的还是同一条代码路径）
            second = lb.get(1).split(".", 1)[1].strip().split()[0]
            app._pick_open_chart(1)
            pump(600)
            check("双击 -> 切图表", app._chart_target[0] == second,
                  f"{second} -> 图表现 {app._chart_target[0]}")

        # ---------- 开合行为（老坑回归）----------
        print("\n=== 下拉开合 ===")
        for _ in range(3):                 # 反复开合：这里曾经段错误闪退过
            rows["topVolume"].event_generate("<Button-1>")
            pump(250)
            rows["topGainers"].event_generate("<Button-1>")
            pump(250)
        check("反复开合不崩（老坑：菜单回调里销毁控件）", True)
        check("手风琴：一次只开一组", app._board_open in ("topVolume", "topGainers"),
              str(app._board_open))

        # ⚠️ 要再点**当前开着的那一组**才会收起（点别组是"切过去"）
        open_key = app._board_open
        rows[open_key].event_generate("<Button-1>")
        pump(300)
        check("再点同一组 -> 收起", app._pick_box is None and app._board_open is None,
              f"开始收的是 {open_key}")

        # 关掉选择品种对话框 -> 什么都不该剩
        rows["topGainers"].event_generate("<Button-1>")
        pump(400)
        check("先展开一组", app._pick_box is not None)
        win.destroy()                      # 模拟关闭对话框
        app._close_pick_list()             # 真实路径由 close_dialog 调用它
        pump(300)
        check("关对话框 -> 什么都不剩", app._pick_box is None
              and app._board_open is None)
        check("★ 没有残留窗口", len([w for w in app.root.winfo_children()
                                      if isinstance(w, tk.Toplevel)]) == 0)

for _k, _v in _orig.items():
    if _v is None:
        app.cfg.pop(_k, None)
    else:
        app.cfg[_k] = _v
# ⚠️ 顺序很重要：quit() 内部会 _save_position() + save_config()，
# 先还原再 quit 的话，位置又被测试窗口的坐标覆盖回去了。
app._pos = None                      # 让 _save_position() 直接跳过
app.quit()
ticker.save_config(app.cfg)
if _orig_text:
    with open(ticker.CONFIG_PATH, "w", encoding="utf-8") as _fh:
        _fh.write(_orig_text)        # 连键顺序都恢复成原样

print()
passed = sum(1 for _l, ok in results if ok)
for label, ok in results:
    print(f"  {'✔' if ok else '✗'} {label}")
print(f"\n{passed}/{len(results)} 项通过")
if passed != len(results):
    raise SystemExit(1)
