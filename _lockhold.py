# -*- coding: utf-8 -*-
"""开着游戏模式停一会儿，方便外面抓窗口图。把 pid/hwnd/rect 写进 _lockhold.txt。"""

import ctypes
import ctypes.wintypes as w
import os
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
cfg["position"] = [700, 300]
app = ticker.TickerApp(cfg)
pid = ctypes.windll.kernel32.GetCurrentProcessId()


def pump(ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


pump(2500)
r = w.RECT()
u.GetWindowRect(app._hwnd(), ctypes.byref(r))
with open("_lockhold.txt", "w", encoding="utf-8") as fh:
    fh.write(f"{pid} {app._hwnd()} {r.left} {r.top} {r.right} {r.bottom}")
print(f"HOLD pid={pid} hwnd={app._hwnd()} rect=({r.left},{r.top},{r.right},{r.bottom})", flush=True)
pump(3000)
app.toggle_game_mode()
print("GAME_MODE_ON", flush=True)
pump(14000)
app.toggle_game_mode()
pump(1500)
try:
    app._pos = None
    app.root.destroy()
except Exception:
    pass
if ORIG:
    with open(ticker.CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write(ORIG)
print("DONE", flush=True)
