# -*- coding: utf-8 -*-
"""验证滚动条区域：拖动只移窗口，单击才跳图表。"""

import ctypes
import ctypes.wintypes as w
import time

user32 = ctypes.windll.user32
LD, LU, MV, ABS = 0x0002, 0x0004, 0x0001, 0x8000


class MI(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MI)]
    _anonymous_ = ("i",)
    _fields_ = [("type", w.DWORD), ("i", _I)]


def send(flags, x=None, y=None):
    i = INPUT()
    i.type = 0
    i.mi = MI(0, 0, 0, flags, 0, None)
    if x is not None:
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        i.mi.dx = int(x * 65535 / (sw - 1))
        i.mi.dy = int(y * 65535 / (sh - 1))
        i.mi.dwFlags |= ABS
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def rct():
    r = w.RECT()
    user32.GetWindowRect(user32.FindWindowW(None, "Crypto Ticker"), ctypes.byref(r))
    return r


LOG = r"G:\mydeepseek\crypto-ticker\ticker.log"


def count():
    return len(open(LOG, encoding="utf-8", errors="ignore").readlines())


def newlines(n):
    return open(LOG, encoding="utf-8", errors="ignore").readlines()[n:]


hwnd = user32.FindWindowW(None, "Crypto Ticker")
user32.SetForegroundWindow(hwnd)
time.sleep(0.4)

# 滚动条在窗口最顶部（约前 21px）
r = rct()
ty = r.top + 10
print(f"窗口 {r.left},{r.top}   滚动条 y={ty}")

n0 = count()
print("\n[1] 在滚动条上拖动窗口 …")
send(MV | ABS, r.left + 50, ty)
time.sleep(0.05)
send(LD)
time.sleep(0.05)
for s in range(1, 11):
    send(MV | ABS, r.left + 50 + s * 4, ty)
    time.sleep(0.02)
send(LU)
time.sleep(1.0)
r2 = rct()
print(f"    拖动后位置 {r2.left},{r2.top}  (原 {r.left},{r.top})")
lines = newlines(n0)
for l in lines:
    print("    " + l.rstrip())
if any("打开 TradingView" in l for l in lines):
    print("    ✗ 拖动滚动条竟然打开了图表")
else:
    print("    ✔ 拖动滚动条没有打开图表")

n1 = count()
print("\n[2] 等 1 秒后，在同一位置单击 …")
time.sleep(1.0)
r3 = rct()
ty3 = r3.top + 10
send(MV | ABS, r3.left + 50, ty3)
time.sleep(0.05)
send(LD)
time.sleep(0.04)
send(LU)
time.sleep(1.2)
lines = newlines(n1)
for l in lines:
    print("    " + l.rstrip())
if any("打开 TradingView" in l for l in lines):
    print("    ✔ 单击滚动条正常打开图表")
else:
    print("    – 单击没命中任何币种（滚动位置不同）")
