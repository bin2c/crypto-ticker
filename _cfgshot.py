# -*- coding: utf-8 -*-
"""摆出「设置中心」停一会儿，方便抓图（先夜间，再白天）。

时间线：
    t=2.5s  打开设置（夜间）
    t≈18s   切到白天（设置窗原地重建）
    t≈34s   退出
把 pid / hwnd 写进 _cfgshot.txt。
"""

import ctypes
import ctypes.wintypes as w
import time
import tkinter as tk

import ticker

u = ctypes.windll.user32
try:
    with open(ticker.CONFIG_PATH, encoding="utf-8-sig") as fh:
        ORIG = fh.read()
except Exception:
    ORIG = None

cfg = ticker.load_config()
cfg["hotkeys"] = False
cfg["theme"] = "night"
cfg["position"] = [520, 260]
cfg["symbols"] = ["BTC", "ETH", "SOL", "XAU", "TSLA"]
cfg["levels"] = {"BTC": {"side": "long", "price": 82500},
                 "ETH": {"side": "short", "price": 2490}}
app = ticker.TickerApp(cfg)
pid = ctypes.windll.kernel32.GetCurrentProcessId()


def pump(ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


def dump(tag):
    win = app._cfg_win or app.root          # ★ 要的是设置窗，不是行情条主窗
    wid = win.winfo_id()
    hwnd = u.GetAncestor(wid, 2) or wid
    r = w.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    with open("_cfgshot.txt", "w", encoding="utf-8") as fh:
        fh.write(f"{tag} {pid} {hwnd} {r.left} {r.top} {r.right} {r.bottom}")
    print(f"SHOT {tag} pid={pid} hwnd={hwnd} rect=({r.left},{r.top},{r.right},{r.bottom})",
          flush=True)


pump(2000)
app.open_settings("display")
pump(900)
dump("night")
pump(26000)
app.set_theme("day")          # 设置窗会原地重建
pump(1500)
dump("day")
pump(26000)

try:
    app._pos = None
    app.root.destroy()
except Exception:
    pass
if ORIG:
    with open(ticker.CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write(ORIG)
print("DONE", flush=True)
