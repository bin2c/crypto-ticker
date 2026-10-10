# -*- coding: utf-8 -*-
"""端到端验证防误触：快速「拖动窗口 + 紧接着双击」，看双击是否被忽略。

工具调用之间有几秒延迟，抓不住真实时序；这里在一个进程里直接发 SendInput，
保证拖动和双击之间的间隔就是真实用户操作的量级。
"""

import ctypes
import ctypes.wintypes as w
import os
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


def rect(hwnd):
    r = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


hwnd = user32.FindWindowW(None, "Crypto Ticker")
if not hwnd:
    raise SystemExit("找不到行情条窗口")

r = rect(hwnd)
print(f"窗口: {r.left},{r.top}  {r.right-r.left}x{r.bottom-r.top}")

log_path = r"G:\mydeepseek\crypto-ticker\ticker.log"
before = len(open(log_path, encoding="utf-8", errors="ignore").readlines())
print(f"日志起始行数: {before}")

user32.SetForegroundWindow(hwnd)
time.sleep(0.3)

r = rect(hwnd)
# 在标题区（滚动条下方、第一行上方）拖窗口，避免落在某一行上
drag_y = r.top + 48
x1 = r.left + 60
x2 = r.left + 110

print("\n[1] 拖动窗口 …")
send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, x1, drag_y)
time.sleep(0.05)
send(MOUSEEVENTF_LEFTDOWN)
time.sleep(0.05)
for step in range(1, 11):
    send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
         x1 + (x2 - x1) * step // 10, drag_y)
    time.sleep(0.02)
send(MOUSEEVENTF_LEFTUP)
print("    拖动完成")

# 关键：紧接着（远小于双击间隔）做一次双击
time.sleep(0.12)
r2 = rect(hwnd)
row_y = r2.top + 62          # BTC 行
cx = r2.left + 60
print(f"[2] 紧接着双击坐标 ({cx},{row_y})  —— 间隔 0.12s")

for _ in range(2):
    send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, cx, row_y)
    send(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.03)
    send(MOUSEEVENTF_LEFTUP)
    time.sleep(0.06)

time.sleep(1.2)
after_lines = open(log_path, encoding="utf-8", errors="ignore").readlines()
new = after_lines[before:]
print(f"\n新增日志 {len(new)} 行:")
for line in new:
    print("   " + line.rstrip())

ignored = any("忽略双击" in l for l in new)
opened = any("打开 TradingView" in l for l in new)
print()
if ignored and not opened:
    print("结果: 双击被正确忽略 ✔  防误触生效")
elif opened:
    print("结果: 仍然打开了图表 �’  防误触没生效")
else:
    print("结果: 既没忽略也没打开（可能双击没落在行上）")
