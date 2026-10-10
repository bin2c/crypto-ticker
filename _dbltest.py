# -*- coding: utf-8 -*-
"""反向验证：没有拖动时，正常双击应该照常打开图表。"""

import ctypes
import ctypes.wintypes as w
import time

user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
INPUT_MOUSE = 0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("i",)
    _fields_ = [("type", w.DWORD), ("i", _I)]


def send(flags, x=None, y=None):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(0, 0, 0, flags, 0, None)
    if x is not None:
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        inp.mi.dx = int(x * 65535 / (sw - 1))
        inp.mi.dy = int(y * 65535 / (sh - 1))
        inp.mi.dwFlags |= MOUSEEVENTF_ABSOLUTE
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


hwnd = user32.FindWindowW(None, "Crypto Ticker")
r = w.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
print(f"窗口: {r.left},{r.top}")

log_path = r"G:\mydeepseek\crypto-ticker\ticker.log"
before = len(open(log_path, encoding="utf-8", errors="ignore").readlines())

user32.SetForegroundWindow(hwnd)
print("等待 2 秒（远超 0.6 秒防护窗口，模拟纯粹的双击）…")
time.sleep(2.0)

r = w.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
cx, cy = r.left + 60, r.top + 62          # BTC 行
print(f"双击 ({cx},{cy})")

for _ in range(2):
    send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, cx, cy)
    send(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.03)
    send(MOUSEEVENTF_LEFTUP)
    time.sleep(0.07)

time.sleep(1.5)
new = open(log_path, encoding="utf-8", errors="ignore").readlines()[before:]
print("\n新增日志:")
for line in new:
    print("   " + line.rstrip())

if any("打开 TradingView" in l for l in new):
    print("\n结果: 正常双击 → 打开图表 ✔")
elif any("忽略双击" in l for l in new):
    print("\n结果: 正常双击被误拦 �’  防护过度了")
else:
    print("\n结果: 没反应（双击可能没落在行上）")
