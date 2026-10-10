# -*- coding: utf-8 -*-
"""把「选择品种」对话框摆出来停一会儿，方便抓图看新 UI。"""

import ctypes
import time
import tkinter as tk

import ticker

try:
    with open(ticker.CONFIG_PATH, encoding="utf-8-sig") as fh:
        ORIG = fh.read()
except Exception:
    ORIG = None

cfg = ticker.load_config()
cfg["hotkeys"] = False
cfg["position"] = [420, 240]
app = ticker.TickerApp(cfg)
pid = ctypes.windll.kernel32.GetCurrentProcessId()


def pump(ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


# 榜单数据用假的，别等网络
app._market_overview = {
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "topVolume": [{"base": b, "change": c} for b, c in
                  (("BTC", 0.17), ("ETH", -0.34), ("SOL", -0.52), ("XAU", -0.17),
                   ("ZEC", 0.23), ("SOXL", -6.86), ("SPCX", -1.91), ("CL", 1.2),
                   ("BNB", 0.4), ("DOGE", -1.1))],
    "topGainers": [{"base": f"GAI{i}", "change": i * 2.0} for i in range(1, 11)],
    "topLosers": [{"base": f"LOS{i}", "change": -i * 2.0} for i in range(1, 11)],
    "topOI": [{"base": f"OI{i}", "change": i * 3.0} for i in range(1, 11)],
}
pump(1500)
app.open_symbols()
pump(900)
win = app._sym_win
if win is not None:
    win.geometry("+380+200")
    try:
        row = app._board_panels["topVolume"]["row"]
        row.event_generate("<Button-1>")        # 展开成交量前 10
    except Exception as exc:
        print("展开失败:", exc)
pump(600)
print(f"HOLD pid={pid} win={win}", flush=True)
pump(30000)
try:
    app._pos = None
    app.root.destroy()
except Exception:
    pass
if ORIG:
    with open(ticker.CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write(ORIG)
print("DONE", flush=True)
