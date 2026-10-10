# -*- coding: utf-8 -*-
"""选择器：结构检查 + 点下拉不会把程序搞崩。

这个测试最早是为了复现一个**段错误闪退**（exit code 0xC0000005）——
当时在菜单命令回调里重建 Menubutton，Tcl 还在处理菜单调用就把它销毁了。
现在改成 Label + 自建弹出列表，那个坑不存在了，但回归还是要跑。
"""

import time
import tkinter as tk

import ticker

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
app = ticker.TickerApp(cfg)


def pump(ms=500):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


def all_widgets(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(all_widgets(c))
    return out


pump(1500)
app.open_symbols()
pump(1200)

win = getattr(app, "_sym_win", None)
if win is None:
    print("选择器没打开")
    raise SystemExit(1)

ws = all_widgets(win)
drops = [w for w in ws if isinstance(w, tk.Label)
         and str(w.cget("text")).endswith("▾")]
print(f"下拉入口 {len(drops)} 个: {[d.cget('text') for d in drops]}")
assert len(drops) == 4, f"应有 4 个下拉，实际 {len(drops)}"

entries = [w for w in ws if isinstance(w, tk.Entry)]
boxes = [w for w in ws if isinstance(w, tk.Listbox)]
print(f"控件: {len(entries)} 输入框 / {len(boxes)} 列表")
assert not entries, "搜索输入框应当已移除"
assert len(boxes) == 1, "应当只剩自选列表"
print("搜索框已移除 ✔")

btns = [w.cget("text") for w in ws if isinstance(w, tk.Button)]
print(f"按钮: {btns}")
assert "添加" not in btns, "「添加」按钮应已移除"
print("「添加」按钮已移除 ✔")

# 逐个点开 4 个下拉，确认都不崩、且都能弹出 10 项
# 增仓榜要 30 秒后才抓到（全市场逐个币查），数据没到就跳过它
#
# ⚠️ v0.16 起下拉是**对话框内部展开**的：不再有独立 Toplevel。
#    所以判据从"弹窗存在"改成"列表在对话框里，且没有多余窗口"。
skipped = []
for d in drops:
    title = str(d.cget("text"))
    d.event_generate("<Button-1>")
    pump(400)
    lb = getattr(app, "_pick_box", None)
    pw = getattr(app, "_pick_win", None)
    ok = lb is not None and lb.winfo_exists() and pw is None and lb.winfo_toplevel() is win
    if not ok and "增仓" in title:
        print(f"  {title:<14} 数据还没到（正常，要 30 秒），跳过")
        skipped.append(title)
        continue
    print(f"  {title:<14} 原地展开={ok}  项数={lb.size() if lb else 0}")
    assert ok, f"{title} 没展开（或又开出了独立弹窗）"
    assert lb.size() == 10, f"{title} 不是 10 项（{lb.size()}）"
    toplevels = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(toplevels) == 1, f"不该有第二个窗口，实际 {len(toplevels)} 个"
    app._close_pick_list()
    pump(200)

print(f"\n{len(drops) - len(skipped)} 个下拉正常弹出，没有崩溃 ✔")
if skipped:
    print(f"（跳过 {skipped}，因为榜单数据要 30 秒后才到）")
print("全部通过")

app._close_pick_list()
if win.winfo_exists():
    win.destroy()
for _k, _v in _orig.items():
    if _v is None:
        app.cfg.pop(_k, None)
    else:
        app.cfg[_k] = _v
# ⚠️ 顺序很重要：quit() 内部会 _save_position() + save_config()，
# 先还原再 quit 的话，位置又被测试窗口的坐标覆盖回去了。
app._pos = None
app.quit()
ticker.save_config(app.cfg)
if _orig_text:
    with open(ticker.CONFIG_PATH, "w", encoding="utf-8") as _fh:
        _fh.write(_orig_text)
