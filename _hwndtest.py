# -*- coding: utf-8 -*-
"""诊断：窗口分层样式到底加在哪个 HWND 上，Tk 的 alpha 又是谁在管。

现象：一开游戏模式（=开鼠标穿透），整个窗口变成一块不透明深色方块，内容全没。
"""

import ctypes
import ctypes.wintypes as w
import time
import tkinter as tk

import ticker

u = ctypes.windll.user32
GWL_EXSTYLE, GWL_STYLE = -20, -16
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

try:
    with open(ticker.CONFIG_PATH, encoding="utf-8-sig") as fh:
        ORIG = fh.read()
except Exception:
    ORIG = None


def desc(hwnd, tag=""):
    cls = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, cls, 256)
    t = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd, t, 256)
    ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
    st = u.GetWindowLongW(hwnd, GWL_STYLE)
    key = w.DWORD(0)
    a = ctypes.c_ubyte(0)
    fl = w.DWORD(0)
    ok = u.GetLayeredWindowAttributes(hwnd, ctypes.byref(key),
                                      ctypes.byref(a), ctypes.byref(fl))
    r = w.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    print(f"  {tag:<10} hwnd={hwnd:<10} parent={u.GetParent(hwnd):<10} "
          f"class={cls.value:<18} title={t.value!r:<18} "
          f"EX=0x{ex:08x} STYLE=0x{st:08x} LAYERED={bool(ex & 0x80000)} "
          f"TRANSPARENT={bool(ex & 0x20)} "
          f"layeredAttr(ok={bool(ok)} alpha={a.value} flags=0x{fl.value:x}) "
          f"rect=({r.left},{r.top},{r.right},{r.bottom})", flush=True)


cfg = ticker.load_config()
cfg["hotkeys"] = False
cfg["position"] = [120, 200]
app = ticker.TickerApp(cfg)
pid = ctypes.windll.kernel32.GetCurrentProcessId()


def pump(ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


def all_windows():
    out = []

    def cb(hwnd, _l):
        p = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            out.append(hwnd)
            kids = []

            def cb2(h2, _l2):
                pp = w.DWORD()
                u.GetWindowThreadProcessId(h2, ctypes.byref(pp))
                if pp.value == pid:
                    kids.append(h2)
                return True

            u.EnumChildWindows(hwnd, WNDENUMPROC(cb2), 0)
            out.extend(kids)
        return True

    u.EnumWindows(WNDENUMPROC(cb), 0)
    return out


pump(2500)
root_id = app.root.winfo_id()
print(f"本进程 PID={pid}")
print(f"root.winfo_id()   = {root_id}")
print(f"app._hwnd()       = {app._hwnd()}   ← apply_click_through() 改的是这个")
print(f"Tk alpha 属性     = {app.root.attributes('-alpha')}  "
      f"colorkey={app.root.attributes('-transparentcolor')!r}")
print(f"style={app.cfg.get('style')} alpha配置={app.cfg.get('alpha')}")
print("\n=== 开游戏模式【之前】===")
for h in all_windows():
    desc(h)
chain = root_id
for i in range(4):
    chain = u.GetParent(chain)
    if not chain:
        break
    print(f"  root 的第 {i+1} 层父窗口:")
    desc(chain)

print("\n=== 开游戏模式【之后】===")
app.toggle_game_mode()
pump(800)
for h in all_windows():
    desc(h)

print("\n=== 手工补一次分层属性（验证这就是解药）===")
app._restore_layered_attrs()
pump(600)
h = app._hwnd()
desc(h, "hwnd()")
print(f"  Tk alpha 现在 = {app.root.attributes('-alpha')}")

print("\n=== 验证：开穿透时就补属性，内容还在不在（看截图）===")
pump(4000)

try:
    app._pos = None
    app.root.destroy()
except Exception:
    pass
if ORIG:
    with open(ticker.CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write(ORIG)
print("DONE", flush=True)
