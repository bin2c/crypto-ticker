# -*- coding: utf-8 -*-
"""复现：开「游戏模式（锁鼠标）」之后窗口变成一块黑的。

用时间线跑，方便外面在固定时刻抓桌面截图：
    t=2.5s  就绪（正常状态）
    t=8s    开游戏模式   ← 重点看这里之后
    t=14s   关游戏模式
    t=19s   退出

同时把分层窗口属性（alpha / 透明色键）打出来 —— 如果 SetWindowLongW
把 Tk 设过的 alpha/色键清掉了，alpha 会变、flags 会变，
而毛玻璃(acrylic)在分层属性失效时会整块渲染成黑色。
"""

import ctypes
import ctypes.wintypes as w
import time
import tkinter as tk

import ticker

HERE = ticker.APP_DIR
CONFIG = ticker.CONFIG_PATH
try:
    with open(CONFIG, encoding="utf-8-sig") as fh:
        ORIG = fh.read()
except Exception:
    ORIG = None

cfg = ticker.load_config()
cfg["hotkeys"] = False
cfg["position"] = [120, 200]
app = ticker.TickerApp(cfg)

u = ctypes.windll.user32
GWL_EXSTYLE = -20
LWA_ALPHA = 0x2
LWA_COLORKEY = 0x1


def pump(ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


def probe(tag):
    hwnd = app._hwnd()
    ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
    key = w.DWORD(0)
    alpha = ctypes.c_ubyte(0)
    flags = w.DWORD(0)
    ok = u.GetLayeredWindowAttributes(hwnd, ctypes.byref(key),
                                      ctypes.byref(alpha), ctypes.byref(flags))
    try:
        tk_alpha = app.root.attributes("-alpha")
        tk_key = repr(app.root.attributes("-transparentcolor"))
    except Exception as exc:
        tk_alpha, tk_key = f"读取失败 {exc}", "-"
    print(f"[{tag}] EX=0x{ex:08x}  穿透={bool(ex & 0x20)}  "
          f"GetLayered ok={bool(ok)} alpha={alpha.value} flags=0x{flags.value:x} key=0x{key.value:06x}"
          f"  |  Tk: alpha={tk_alpha} colorkey={tk_key}", flush=True)


pump(2500)
print("READY1", flush=True)
probe("正常")

print("...等 5.5 秒（外面抓图）", flush=True)
pump(5500)

print("TOGGLE_ON", flush=True)
app.toggle_game_mode()
pump(800)
probe("开了游戏模式")

print("...等 5 秒（外面抓图）", flush=True)
pump(5000)

print("TOGGLE_OFF", flush=True)
app.toggle_game_mode()
pump(800)
probe("关了游戏模式")

print("...等 4 秒（外面抓图）", flush=True)
pump(4000)

# 照着"测试不许改用户配置"的老规矩：原样写回
try:
    app._pos = None
    app.cfg["hotkeys"] = True
    app.root.destroy()
except Exception:
    pass
if ORIG:
    with open(CONFIG, "w", encoding="utf-8") as fh:
        fh.write(ORIG)
print("DONE", flush=True)
