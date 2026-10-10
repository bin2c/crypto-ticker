# -*- coding: utf-8 -*-
"""可靠地重启行情条：按窗口枚举找 PID，而不是靠 MainWindowTitle。

教训：行情条是 overrideredirect 无边框窗口，Tk 会把它私有的 Toplevel
（比如"选择品种"对话框）报成 MainWindowTitle，
所以 `Get-Process | Where MainWindowTitle -eq 'Crypto Ticker'` 会漏掉真正的实例。
"""

import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import time

u = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
TITLES = {"Crypto Ticker", "选择品种", "行情条设置"}


def visible_windows():
    """返回 [(pid, title), …]，只看行情条相关窗口。"""
    out = []

    def cb(hwnd, _l):
        if not u.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, buf, 512)
        core = buf.value.rsplit(" · ", 1)[0]
        if core in TITLES:
            pid = w.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((pid.value, buf.value))
        return True

    u.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def main():
    procs = {}
    for pid, title in visible_windows():
        procs.setdefault(pid, []).append(title)

    if procs:
        for pid, titles in procs.items():
            print(f"结束行情条 PID={pid}  窗口={titles}")
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, text=True)
        time.sleep(1.5)
    else:
        print("没有正在运行的行情条")

    if "--kill-only" in sys.argv:
        return

    here = os.path.dirname(os.path.abspath(__file__))
    DETACHED = 0x00000008 | 0x00000200
    subprocess.Popen(
        [r"G:\python3.13\pythonw.exe", "ticker.py"],
        cwd=here, creationflags=DETACHED,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print("已启动新实例，等待就绪…")
    time.sleep(9)

    live = visible_windows()
    if live:
        for pid, title in live:
            if title == "Crypto Ticker":
                print(f"就绪: PID={pid}  '{title}'")
                break
        else:
            print(f"启动异常，可见窗口: {live}")
    else:
        print("启动失败：没有可见窗口")


if __name__ == "__main__":
    main()
