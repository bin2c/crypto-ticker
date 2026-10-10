# -*- coding: utf-8 -*-
"""列出桌面上所有「置顶」的可见窗口，找出谁在挡路。"""
import ctypes
import ctypes.wintypes as w

u = ctypes.windll.user32
GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000

rows = []


def cb(hwnd, _l):
    if not u.IsWindowVisible(hwnd):
        return True
    ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if not (ex & WS_EX_TOPMOST):
        return True
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, buf, 512)
    cls = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, cls, 256)
    p = w.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    r = w.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    flags = []
    if ex & WS_EX_TOOLWINDOW:
        flags.append("TOOL")
    if ex & WS_EX_LAYERED:
        flags.append("LAYERED")
    if ex & WS_EX_TRANSPARENT:
        flags.append("穿透")
    if ex & WS_EX_NOACTIVATE:
        flags.append("不激活")
    rows.append((hwnd, p.value, buf.value, cls.value,
                 r.left, r.top, r.right - r.left, r.bottom - r.top,
                 "|".join(flags) or "-"))


WND = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
u.EnumWindows(WND(cb), 0)

print(f"=== 置顶且可见的窗口：{len(rows)} 个 ===\n")
for hwnd, pid, title, cls, x, y, ww, hh, flags in rows:
    print(f"  HWND={hwnd:<10} PID={pid:<7} [{flags}]")
    print(f"     '{title[:60]}'  ({cls})")
    print(f"     {x},{y} {ww}x{hh}")
    print()

print("=== DSH 主窗口的样式 ===")
h = u.FindWindowW(None, "BTC 等加密货币实时价格窗口 — DeepSeek Harness")
if not h:
    # 标题会变，按进程名找
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq DSH NEXT.exe", "/FO", "CSV"],
                         capture_output=True, text=True).stdout
    print("  DSH 进程:", [l.split(",")[1] for l in out.splitlines()[1:] if "," in l])
states = []
if h:
    print(f"  HWND={h}")
    print(f"  扩展样式 0x{u.GetWindowLongW(h, GWL_EXSTYLE) & 0xFFFFFFFF:08X}"
          f"  置顶={bool(u.GetWindowLongW(h, GWL_EXSTYLE) & WS_EX_TOPMOST)}")
else:
    print("  没找到（标题可能变了），下面按进程列：")
    for hwnd, pid, title, cls, x, y, ww, hh, flags in rows:
        if ww > 1500:
            print(f"    大窗口: HWND={hwnd} PID={pid} '{title[:50]}' {ww}x{hh}")

print("\n=== 前台窗口 ===")
fg = u.GetForegroundWindow()
b = ctypes.create_unicode_buffer(512)
u.GetWindowTextW(fg, b, 512)
p = w.DWORD()
u.GetWindowThreadProcessId(fg, ctypes.byref(p))
print(f"  HWND={fg} PID={p.value}")
print(f"  '{b.value}'")
print(f"  置顶={bool(u.GetWindowLongW(fg, GWL_EXSTYLE) & WS_EX_TOPMOST)}")
