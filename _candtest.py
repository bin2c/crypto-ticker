# -*- coding: utf-8 -*-
"""确定性验证候选弹窗逻辑：直接调 app 的方法，不依赖模拟键盘输入。

模拟输入受焦点/激活/结构体对齐等一堆因素影响，太不可靠；
这里只验证"我写的逻辑对不对"。
"""

import time
import tkinter as tk

import ticker

cfg = ticker.load_config()
cfg["symbols"] = ["BTC", "ETH", "SOL"]
cfg["position"] = [1400, 700]        # 摆到屏幕中间，上方才有空间放候选窗
app = ticker.TickerApp(cfg)

results = []


def step(label, fn):
    try:
        ok = fn()
        results.append((label, bool(ok), ""))
    except Exception as exc:
        results.append((label, False, f"{type(exc).__name__}: {exc}"))


def pump(ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


pump(1200)          # 等合约清单/榜单就绪

# 1) 没输入时不应有候选
step("空输入 -> 无候选", lambda: app._candidate_hits() == [])

# 2) 输入 E -> 9 个候选，且第一个是 ETH
def input_e():
    app.entry.delete(0, "end")
    app.entry.insert(0, "E")
    pump(400)
    hits = app._cand_hits
    print(f"   输入 E 得到 {len(hits)} 个候选: {hits[:5]}")
    return len(hits) == 9 and hits[0] == "ETH"


step("输入 E -> 9 个候选且首选 ETH", input_e)

# 3) 候选窗真的显示了
def popup_visible():
    win = app._cand_win
    vis = bool(win and win.winfo_exists() and win.winfo_viewable())
    if win:
        print(f"   候选窗 {win.winfo_width()}x{win.winfo_height()} "
              f"@ {win.winfo_x()},{win.winfo_y()}  可见={vis}")
    return vis


step("候选弹窗已显示", popup_visible)

# 4) 候选窗在输入框正上方
def above_input():
    pump(300)                     # 等窗口管理器把 geometry 落实，否则 winfo 是陈旧值
    win = app._cand_win
    win_bottom = win.winfo_y() + win.winfo_height()
    input_top = app.root.winfo_y() + app.root.winfo_height() - app._inbar_h
    print(f"   候选窗 @{win.winfo_x()},{win.winfo_y()} {win.winfo_width()}x{win.winfo_height()}")
    print(f"   候选窗底边={win_bottom}  输入框顶边={input_top}")
    return abs(win_bottom - input_top) <= 4


step("候选窗贴在输入框上方", above_input)

# 5) 列表内容带编号
def numbered():
    items = [app._cand.get(i) for i in range(app._cand.size())]
    print(f"   列表首项: {items[0]!r}")
    return items and items[0].strip().startswith("1")


step("候选带 1/2/3 编号", numbered)

# 6) 数字键选候选 -> 加入自选
def pick_second():
    before = list(app.cfg["symbols"])
    second = app._cand_hits[1]
    app._accept_candidate(1)
    pump(500)
    after = list(app.cfg["symbols"])
    print(f"   选第 2 项 {second}: {before} -> {after}")
    return second in after


step("选中候选会加入自选", pick_second)

# 7) 选完候选窗收起、输入框清空
step("选完候选窗收起", lambda: not app._cand_win.winfo_viewable())
step("选完输入框清空", lambda: app.entry.get().strip() == "")

# 8) 上下键移动高亮
def move_highlight():
    app.entry.delete(0, "end")
    app.entry.insert(0, "E")
    pump(400)
    app._cand_index = 0
    app._move_candidate(1)
    return app._cand_index == 1


step("上下键切换高亮", move_highlight)

# 9) 纯数字查询时数字照常输入（不该被当成选候选）
def digit_query():
    app.entry.delete(0, "end")
    app.entry.insert(0, "1000")
    pump(400)
    hits = app._cand_hits
    print(f"   输入 1000 得到: {hits[:3]}")
    return hits and all(h.startswith("1000") or "1000" in h for h in hits)


step("数字查询正常匹配", digit_query)

# 10) 恢复原始配置
app.cfg["symbols"] = ["BTC", "ETH", "SOL"]
ticker.save_config(app.cfg)
app.quit()

print()
print("=" * 56)
passed = sum(1 for _l, ok, _e in results if ok)
for label, ok, err in results:
    print(f"  {'✔' if ok else '✗'} {label}" + (f"   [{err}]" if err else ""))
print(f"\n{passed}/{len(results)} 项通过")
if passed != len(results):
    raise SystemExit(1)
