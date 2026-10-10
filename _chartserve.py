# -*- coding: utf-8 -*-
"""只为浏览器端测试起一个图表服务：跑的是**当前** ticker.py 的代码。

用法：python _chartserve.py     → 把图表页 URL 写进 _charturl.txt，然后常驻。
测完直接 kill 掉进程即可（不改配置、不写盘）。
"""

import time
import tkinter as tk

import ticker

cfg = ticker.load_config()
app = ticker.TickerApp(cfg)


def pump():
    """让主循环跑起来，同时保证窗口不抢焦点（测试期间别打扰用户）。"""
    app.root.after(200, pump)


pump()
url = app._chart_server.url
with open("_charturl.txt", "w", encoding="utf-8") as fh:
    fh.write(url or "")
print("CHART_URL", url, flush=True)
app.root.mainloop()
