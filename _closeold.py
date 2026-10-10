# -*- coding: utf-8 -*-
"""关掉历史上攒下来的旧「行情图表」窗口。

只按**标题**筛（`行情图表…` / `undefined`），不碰 `127.0.0.1` 那种
（可能是用户别的本地页面）。先 PostMessage(WM_CLOSE) 温柔地关，
关不掉的（渲染进程已经死了的占位窗口）再报告出来。
"""

import ctypes
import ctypes.wintypes as w
import time

u = ctypes.windll.user32
WM_CLOSE = 0x0010
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


def scan(visible_only=False):
    out = []

    def cb(hwnd, _l):
        if visible_only and not u.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if title.startswith("行情图表") or title == "undefined" or title == "127.0.0.1":
            pid = w.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((hwnd, title, pid.value, bool(u.IsWindowVisible(hwnd))))
        return True

    u.EnumWindows(WNDENUMPROC(cb), 0)
    return out


targets = scan(visible_only=False)
vis = [t for t in targets if t[3]]
print(f"按标题匹配到 {len(targets)} 个窗口（其中可见 {len(vis)} 个）")
by_title = {}
for hwnd, title, pid, v in targets:
    key = "行情图表…" if title.startswith("行情图表") else title
    by_title[key] = by_title.get(key, 0) + 1
print("  按标题:", by_title)
by_pid = {}
for hwnd, title, pid, v in targets:
    by_pid[pid] = by_pid.get(pid, 0) + 1
print("  按进程:", by_pid)

for hwnd, title, pid, v in targets:
    u.PostMessageW(hwnd, WM_CLOSE, 0, 0)

time.sleep(3.0)
left = scan(visible_only=False)
print(f"3 秒后还剩 {len(left)} 个")
for hwnd, title, pid, v in left[:12]:
    print(f"   还剩: pid={pid} title={title!r} 可见={v}")

