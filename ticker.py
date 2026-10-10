#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
透明悬浮行情小窗 —— 实时显示 BTC / ETH / SOL 等自选币种价格。

纯 Python 标准库实现（tkinter + urllib），无需 pip 安装任何东西。

常用操作
    左键拖动     移动窗口
    右键         打开菜单（刷新 / 置顶 / 不透明度 / 样式 / 币种 / 退出）
    滚轮         调整不透明度
    Ctrl + 滚轮  调整字号

命令示例
    python ticker.py
    python ticker.py --symbols BTC,ETH,SOL,DOGE --interval 2
    python ticker.py --symbols BTC --style float --alpha 1.0 --scheme cn

配置保存在同目录 config.json（首次运行自动生成，右键菜单"重新加载配置"可热更新）。
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import smtplib
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tkinter as tk
import tkinter.font as tkfont

try:                                   # Windows 专有：鼠标穿透 + 全局热键
    import ctypes
    from ctypes import wintypes
except ImportError:                    # 非 Windows 平台自动降级
    ctypes = None
    wintypes = None

def _frozen() -> bool:
    """是不是 PyInstaller 打出来的 exe（打包后 sys.frozen 会被设上）。"""
    return bool(getattr(sys, "frozen", False))


def _resolve_dirs():
    """返回 (可写目录, 只读资源目录)。

    ⚠️ 打包成 exe 之后这两个**不是同一个地方**：
      * `sys._MEIPASS` 是 PyInstaller 解压出来的临时目录（退出就删）——
        lightweight-charts.js 这类只读资源在里面；
      * exe 自己所在的目录才是能长期保存东西的地方 ——
        config.json / ticker.log / symbols.json 必须放这儿，
        不然用户改了配置、下次启动全没了。
    没打包时两个都是脚本所在目录。
    """
    if _frozen():
        res = getattr(sys, "_MEIPASS", None) or os.path.dirname(
            os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(sys.executable)), res
    here = os.path.dirname(os.path.abspath(__file__))
    return here, here


APP_DIR, RES_DIR = _resolve_dirs()   # APP_DIR=可写（配置/日志/缓存）  RES_DIR=只读资源
APP_VERSION = "0.19"           # 和 CHANGELOG 对齐；设置 →「关于」里显示
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

# ---------------------------------------------------------------- 默认配置 --

DEFAULT_CONFIG = {
    "symbols": ["BTC", "ETH", "SOL"],   # 可写 "BTC" 或 "BTCUSDT" 或 "BTC-USDT"
    "quote": "USDT",                    # 省略计价单位时默认用它
    "market": "perp",                   # perp=U 本位永续合约  spot=现货
    "tv_exchange": "BINANCE",           # 双击打开 TradingView 时用的交易所前缀
    "interval": 3,                      # 刷新间隔（秒）
    "alpha": 1.0,                       # 整窗不透明度 0.2 ~ 1.0
    "style": "float",                   # float=纯文字全透明（默认）  card=半透明卡片
    "scheme": "west",                   # west=绿涨红跌  cn=红涨绿跌
    "font_size": 9,                     # 小字号，不明显挡视线
    "font_family": "Bahnschrift SemiLight",   # 简洁的 DIN 风无衬线，专为数字设计
    "text_effect": "none",              # none=无（最干净）outline=细描边 shadow=投影 outline_full=粗描边
    "text_color": "black",              # black=纯黑文字  white=白色文字（深色画面用）
    "change_colored": False,            # False=涨跌幅也用同色（黑）True=红绿着色
    "show_change": True,                # 是否显示 24h 涨跌幅
    "show_header": False,               # 是否显示表头（标题 + 时间）
    "show_tape": True,                  # 顶部横向滚动条（涨幅/跌幅/成交量）
    "show_input": True,                 # 底部内联输入框（模糊匹配加币）
    "dblclick_chart": True,             # 双击行情行打开 TradingView（拖动窗口不会误触）
    "market_cap_filter": 20,            # 成交量榜剔除市值前 N 名（0=不剔除）
    "rank_refresh": 60,                 # 榜单与滚动条刷新间隔（秒）
    "show_oi": True,                    # 是否显示增仓榜（只看持仓增加的）
    "oi_refresh": 600,                  # 增仓榜刷新间隔（秒，逐个币查所以慢）
    "click_through": False,             # True=整个窗口鼠标穿透，完全不挡点击
    "hotkeys": True,                    # 全局热键 Ctrl+Alt+H/M/P
    "always_on_top": True,
    "title": "行情",
    "position": None,                   # [x, y]，退出时自动保存
    "show_levels": True,                # 品种名后的「仓位/关注价位」小按钮 + 标记
    "levels": {},                       # {"BTC": {"side":"long|short|watch","price":0.0}}
    "theme": "night",                   # night=夜间（默认） day=白天 auto=跟随系统
    "scan_favs": [],                    # 全品种扫盘里收藏的品种（♥），方便同步去 TradingView
}

# 配色
BG_DARK = "#0b0e11"
BG_BORDER = "#2b3139"
UP_WEST, DOWN_WEST = "#0ecb81", "#f6465d"
UP_CN, DOWN_CN = "#f6465d", "#0ecb81"
TRANSPARENT_KEY = "#ff00fe"          # 透明色键（正常画面里不会出现的洋红）
LIGHT_TINT = "#f2f4f7"               # 白天主题：毛玻璃底色（浅灰白，比纯白柔和）
LIGHT_CARD = "#ffffff"               # 白天主题：纯色卡片底

# 调节面板配色
PANEL_BG = "#1c1c1e"
PANEL_FG = "#e8e8ea"
PANEL_DIM = "#8e8e93"
PANEL_TROUGH = "#3a3a3c"
PANEL_ACCENT = "#5ac8fa"
PANEL_ACCENT_DIM = "#3b7f9e"

# ---- 对话框 UI（v0.17）：深色扁平风，和图表页同一套色 ----------------
# 用户原话：「更多里面的那个 UI 太丑了，能不能搞点科技感简洁的，比较现代的那种风格」。
# Tk 原生 Button/Scrollbar 在 Windows 上是灰色 3D 块，放在深色面板上很脏，
# 所以按钮/胶囊/滚动条都自己画（Label + 悬浮变色 + ttk clam 主题）。
UI_BG = "#0d1117"            # 窗口底
UI_PANEL = "#161b22"         # 面板/列表底
UI_PANEL2 = "#1c2128"        # 输入框/次级控件底
UI_HOVER = "#262c36"         # 悬浮
UI_BORDER = "#21262d"        # 分隔线
UI_FG = "#c9d1d9"
UI_DIM = "#8b949e"
UI_FAINT = "#6e7681"
UI_ACCENT = "#58a6ff"        # 主色（和图表页同一个蓝）
UI_ACCENT_HI = "#79b8ff"
UI_ACCENT_BG = "#1f6feb"
UI_OK = "#0ecb81"
UI_DANGER = "#f6465d"
UI_WARN = "#f0b90b"

# ---- 主题皮肤 ----------------------------------------------------------
# 用户要求：「全是深色看的不好，给个白天/亮色，晚上选夜间模式」。
# 上面那组 UI_* 就是**夜间**（默认），下面这份是**白天**。
# 所有对话框都直接按名字引用 UI_*，所以切换主题只要把对应的一份
# 灌回这些全局名字（apply_theme_palette），再把开着的窗口重画一遍即可。
UI_DAY = {
    "UI_BG": "#f6f8fa",          # 窗口底（浅灰白，比纯白柔和）
    "UI_PANEL": "#ffffff",       # 面板/列表底
    "UI_PANEL2": "#eef1f4",      # 输入框/次级控件底
    "UI_HOVER": "#e3e8ee",
    "UI_BORDER": "#d0d7de",
    "UI_FG": "#1f2328",
    "UI_DIM": "#59636e",
    "UI_FAINT": "#8c959f",
    "UI_ACCENT": "#0969da",      # 主色（白天用深一点的蓝，对比够）
    "UI_ACCENT_HI": "#218bff",
    "UI_ACCENT_BG": "#0969da",
    "UI_OK": "#1a7f37",
    "UI_DANGER": "#cf222e",
    "UI_WARN": "#9a6700",
}
UI_NIGHT = {k: v for k, v in (
    ("UI_BG", UI_BG), ("UI_PANEL", UI_PANEL), ("UI_PANEL2", UI_PANEL2),
    ("UI_HOVER", UI_HOVER), ("UI_BORDER", UI_BORDER), ("UI_FG", UI_FG),
    ("UI_DIM", UI_DIM), ("UI_FAINT", UI_FAINT), ("UI_ACCENT", UI_ACCENT),
    ("UI_ACCENT_HI", UI_ACCENT_HI), ("UI_ACCENT_BG", UI_ACCENT_BG),
    ("UI_OK", UI_OK), ("UI_DANGER", UI_DANGER), ("UI_WARN", UI_WARN))}

THEME_NAMES = (("night", "夜间"), ("day", "白天"), ("auto", "跟随系统"))


def detect_system_theme() -> str:
    """读 Windows 的 AppsUseLightTheme（0=深色，1=浅色）。读不到就当深色。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        try:
            val, _t = winreg.QueryValueEx(key, "AppsUseLightTheme")
        finally:
            winreg.CloseKey(key)
        return "day" if int(val) == 1 else "night"
    except Exception:
        return "night"


def resolve_theme(cfg: dict) -> str:
    """把配置里的 theme（night/day/auto）解析成实际生效的 night 或 day。"""
    want = str(cfg.get("theme", "night")).lower()
    if want == "auto":
        return detect_system_theme()
    return "day" if want == "day" else "night"


def apply_theme_palette(name: str) -> str:
    """把主题颜色灌回 UI_* 全局名（对话框都按名字取色）。"""
    real = "day" if name == "day" else "night"
    globals().update(UI_DAY if real == "day" else UI_NIGHT)
    return real


def ui_font_family(root) -> str:
    """对话框统一用一个干净的 UI 字体。"""
    try:
        return pick_ui_font(root)
    except Exception:
        return "Microsoft YaHei UI"


def ui_button(parent, text, command, kind="ghost", font=None, width=None,
              padx=12, pady=4):
    """扁平按钮（Label 手做）。

    kind: primary=主色实心 / ghost=深色底 / danger=红字危险操作
    Tk 原生 Button 在 Windows 上带 3D 边框和系统灰，和这套深色 UI 完全不搭。
    """
    styles = {
        "primary": ("#000000", UI_ACCENT_BG, UI_ACCENT_HI),
        "ghost": (UI_FG, UI_PANEL2, UI_HOVER),
        "danger": (UI_DANGER, UI_PANEL2, "#3a1d22"),
        "quiet": (UI_DIM, UI_BG, UI_PANEL2),
    }
    fg, bg, hover = styles.get(kind, styles["ghost"])
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg, padx=padx, pady=pady,
                   font=font, cursor="hand2", bd=0)
    if width:
        lbl.configure(width=width)

    def _enter(_e):
        lbl.configure(bg=hover)

    def _leave(_e):
        lbl.configure(bg=bg)

    lbl.bind("<Enter>", _enter)
    lbl.bind("<Leave>", _leave)
    lbl.bind("<Button-1>", lambda _e: command())
    return lbl


def ui_chip(parent, text, command, on=False, font=None):
    """筛选小胶囊（分类筛选用）。"""
    lbl = tk.Label(parent, text=text, padx=9, pady=1, bd=0, cursor="hand2",
                   font=font, bg=UI_ACCENT_BG if on else UI_PANEL2,
                   fg="#ffffff" if on else UI_DIM)
    lbl.bind("<Enter>", lambda _e: lbl.configure(
        bg=UI_ACCENT_BG if lbl._on else UI_HOVER))
    lbl.bind("<Leave>", lambda _e: lbl.configure(
        bg=UI_ACCENT_BG if lbl._on else UI_PANEL2), add="+")
    lbl._on = on

    def _set(state):
        lbl._on = state
        lbl.configure(bg=UI_ACCENT_BG if state else UI_PANEL2,
                      fg="#ffffff" if state else UI_DIM)

    lbl.ui_set = _set
    lbl.bind("<Button-1>", lambda _e: command())
    return lbl


def ui_header(parent, text, note=""):
    """段落标题：左侧一条主色竖条 + 灰字 +（可选）右侧浅色说明。"""
    row = tk.Frame(parent, bg=UI_BG)
    bar = tk.Frame(row, bg=UI_ACCENT, width=3, height=13)
    bar.pack(side="left", padx=(0, 7))
    bar.pack_propagate(False)
    tk.Label(row, text=text, bg=UI_BG, fg=UI_FG,
             font=(ui_font_family(parent), 10)).pack(side="left")
    if note:
        tk.Label(row, text=note, bg=UI_BG, fg=UI_FAINT,
                 font=(ui_font_family(parent), 8)).pack(side="left", padx=(8, 0))
    return row


def ui_sep(parent, pady=8):
    f = tk.Frame(parent, bg=UI_BORDER, height=1)
    f.pack(fill="x", pady=pady)
    return f


def ui_toggle(parent, text, var, command, font=None, width=44, pad=7):
    """一行开关：左边说明，右边一个"药丸"开关。

    为什么不用原生 Checkbutton：它在深色/浅色下都是系统样式，方框 + 对勾
    和这套扁平 UI 完全不搭。
    """
    row = tk.Frame(parent, bg=UI_BG)
    tk.Label(row, text=text, bg=UI_BG, fg=UI_FG, font=font,
             anchor="w").pack(side="left")
    cv = tk.Canvas(row, width=width, height=18, bg=UI_BG,
                   highlightthickness=0, bd=0, cursor="hand2")
    cv.pack(side="right")
    state = {"on": bool(var.get())}

    def paint(hover=False):
        cv.delete("all")
        on = state["on"]
        track = (UI_ACCENT_BG if on else (UI_HOVER if hover else UI_PANEL2))
        edge = UI_ACCENT_BG if on else UI_BORDER
        cv.create_oval(1, 3, 15, 17, fill=track, outline=edge)
        cv.create_oval(width - 15, 3, width - 1, 17, fill=track, outline=edge)
        cv.create_rectangle(8, 3, width - 8, 17, fill=track, outline=edge)
        cx = (width - 9) if on else 9
        cv.create_oval(cx - 5, 4, cx + 5, 14, fill="#ffffff", outline="")

    def toggle(_e=None):
        state["on"] = not state["on"]
        try:
            var.set(state["on"])
        except Exception:
            pass
        paint()
        command()

    cv.bind("<Button-1>", toggle)
    cv.bind("<Enter>", lambda _e: paint(True))
    cv.bind("<Leave>", lambda _e: paint(False))
    row.bind("<Button-1>", toggle)
    paint()
    row.pack(fill="x", pady=(0, pad))
    return row


def ui_choice(parent, text, options, var, command, font=None, pad=7):
    """一行单选：左边说明，右边一排胶囊。options = [(显示名, 值), …]"""
    row = tk.Frame(parent, bg=UI_BG)
    tk.Label(row, text=text, bg=UI_BG, fg=UI_FG, font=font,
             anchor="w").pack(side="left")
    holder = tk.Frame(row, bg=UI_BG)
    holder.pack(side="right")
    chips = {}

    def pick(value):
        try:
            var.set(value)
        except Exception:
            pass
        for key, chip in chips.items():
            chip.ui_set(key == value)
        command()

    for label, value in options:
        chip = ui_chip(holder, label, lambda v=value: pick(v),
                       on=(str(var.get()) == str(value)), font=font)
        chip.pack(side="left", padx=(4, 0))
        chips[value] = chip
    row.pack(fill="x", pady=(0, pad))
    return row


def ui_gear(parent, command, size=19, bg=None, font=None):
    """齿轮（设置）图标：自己画，不吃字体 —— emoji 齿轮在不同机器上差别很大。"""
    import math
    bg = bg or UI_BG
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0,
                   bd=0, bg=bg, cursor="hand2")
    c = size / 2.0
    r_out, r_in = size * 0.34, size * 0.15

    def paint(color):
        cv.delete("all")
        for i in range(8):
            ang = i * math.pi / 4
            cv.create_line(c + math.cos(ang) * (r_out - 1.5),
                           c + math.sin(ang) * (r_out - 1.5),
                           c + math.cos(ang) * (r_out + 2.2),
                           c + math.sin(ang) * (r_out + 2.2),
                           fill=color, width=2)
        cv.create_oval(c - r_out, c - r_out, c + r_out, c + r_out,
                       outline=color, width=2)
        cv.create_oval(c - r_in, c - r_in, c + r_in, c + r_in,
                       outline=color, width=1)

    paint(UI_DIM)
    cv.bind("<Enter>", lambda _e: paint(UI_ACCENT))
    cv.bind("<Leave>", lambda _e: paint(UI_DIM))
    cv.bind("<Button-1>", lambda _e: command())
    cv.paint = paint
    return cv


def ui_style_listbox(lb, font=None):
    """统一的深色列表样式。"""
    lb.configure(bg=UI_PANEL, fg=UI_FG, bd=0, highlightthickness=0,
                 activestyle="none", exportselection=False,
                 selectbackground=UI_ACCENT_BG, selectforeground="#ffffff")
    if font:
        lb.configure(font=font)
    return lb


def ui_style_scrollbar(widget):
    """ttk 滚动条默认是系统灰，切成 clam 主题再染成深色。"""
    try:
        style = ttk.Style(widget)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("UI.Vertical.TScrollbar", background=UI_PANEL2,
                        troughcolor=UI_BG, bordercolor=UI_BG,
                        arrowcolor=UI_DIM, relief="flat")
        style.map("UI.Vertical.TScrollbar",
                  background=[("active", UI_HOVER)])
        return ttk.Scrollbar(widget, orient="vertical", style="UI.Vertical.TScrollbar")
    except Exception:
        return None

# 价格跳动时的闪烁过渡
FLASH_UP = "#00e676"                 # 上涨：亮绿
FLASH_DOWN = "#ff5252"               # 下跌：亮红
FLASH_MS = 800                       # 一次闪烁持续多久
OVERLAY_ON = "#f0b90b"               # 提醒点亮色（和趋势线同色，醒目）
FLASH_FRAME_MS = 80                  # 动画帧间隔

# 仓位 / 关注价位标记的配色。
# ⚠️ 这三个色**不跟随「涨跌配色」(scheme) 翻转** —— 用户明确要求：
# 做多=红、做空=绿。这是"我站在哪一边"，不是"行情涨还是跌"，两回事。
LEVEL_LONG = "#f6465d"               # 做多（红）
LEVEL_SHORT = "#0ecb81"              # 做空（绿）
LEVEL_WATCH = "#f0b90b"              # 仅关注（琥珀，和提醒点亮同色）

# 菜单里的不透明度 / 字号档位（原来还有个浮动面板，已经并进菜单了）
OPACITY_STEPS = (100, 95, 90, 85, 80, 75, 70, 60, 50, 40, 30)
FONT_SIZE_STEPS = (7, 8, 9, 10, 11, 12, 14, 16)

# ---- Windows 扩展样式：让整窗鼠标穿透（打游戏时完全不挡点击）----
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

# ---- Windows 毛玻璃（未公开 API SetWindowCompositionAttribute）----
WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
BLUR_TINT = "#1c1c1e"                # 毛玻璃底色
BLUR_ABGR = 0x991E1C1C               # AABBGGRR 格式，给系统叠的着色

if ctypes:
    class ACCENT_POLICY(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_uint),
                    ("AccentFlags", ctypes.c_uint),
                    ("GradientColor", ctypes.c_uint),
                    ("AnimationId", ctypes.c_uint)]

    class WINCOMPATTRDATA(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_uint),
                    ("Data", ctypes.POINTER(ACCENT_POLICY)),
                    ("SizeOfData", ctypes.c_size_t)]
else:                                # 非 Windows
    ACCENT_POLICY = WINCOMPATTRDATA = None

# ---- 全局热键（即使窗口被游戏挡住、或已开启鼠标穿透也有效）----
# 每个功能给一组候选组合键，逐个尝试注册，避开已被别的软件占用的键。
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000
WM_HOTKEY = 0x0312
_C, _A, _S = MOD_CONTROL, MOD_ALT, MOD_SHIFT
HOTKEY_DEFS = {
    "toggle": [("Ctrl+Alt+H", _C | _A, 0x48),
               ("Ctrl+Shift+Alt+H", _C | _A | _S, 0x48)],
    "menu": [("Ctrl+Alt+M", _C | _A, 0x4D),
             ("Ctrl+Alt+O", _C | _A, 0x4F),
             ("Ctrl+Alt+J", _C | _A, 0x4A),
             ("Ctrl+Shift+Alt+M", _C | _A | _S, 0x4D)],
    "click": [("Ctrl+Alt+P", _C | _A, 0x50),
              ("Ctrl+Shift+Alt+P", _C | _A | _S, 0x50)],
    "symbols": [("Ctrl+Alt+K", _C | _A, 0x4B),
                ("Ctrl+Alt+Y", _C | _A, 0x59),
                ("Ctrl+Shift+Alt+K", _C | _A | _S, 0x4B)],
    # 游戏模式：按一下锁住鼠标（防误触），再按一下解锁
    "game": [("Ctrl+Alt+G", _C | _A, 0x47),
             ("Ctrl+Alt+B", _C | _A, 0x42),
             ("Ctrl+Shift+Alt+G", _C | _A | _S, 0x47)],
    # 全品种扫盘页
    "scan": [("Ctrl+Alt+S", _C | _A, 0x53),
             ("Ctrl+Shift+Alt+S", _C | _A | _S, 0x53)],
}
HOTKEY_NAMES = {"toggle": "显隐", "menu": "菜单", "click": "穿透",
                "symbols": "选品种", "game": "游戏模式", "scan": "全品种扫盘"}
DEFAULT_HOTKEY_HINT = ("热键：Ctrl+Alt+H 显隐 · Ctrl+Alt+M 菜单 · "
                       "Ctrl+Alt+P 穿透 · Ctrl+Alt+G 游戏模式 · Ctrl+Alt+S 全品种扫盘")


def log(msg: str) -> None:
    """永远写日志文件，同时（有 stdout 时）也打印。

    以前是"有 stdout 就不写文件"，结果控制台模式下日志全跑到终端里去了，
    排查问题时看错地方。文件始终是最可靠的。
    """
    line = time.strftime("[%H:%M:%S] ") + msg
    try:
        with open(os.path.join(APP_DIR, "ticker.log"), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    if sys.stdout:
        try:
            print(line, flush=True)
        except Exception:
            pass


# ---------------------------------------------------------------- 配置读写 --

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            # utf-8-sig：兼容记事本 / PowerShell 写出的带 BOM 文件
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as fh:
                cfg.update(json.load(fh) or {})
        except Exception as exc:
            log(f"读取配置失败，使用默认值: {exc}")
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"保存配置失败: {exc}")


# ---------------------------------------------------------------- 币种解析 --

def normalize_symbol(raw: str, default_quote: str):
    """把 BTC / btc-usdt / BTCUSDT 统一成 (基础币, 计价币)。"""
    text = str(raw).strip().upper().replace("/", "-").replace("_", "-")
    if not text:
        return None
    quote = default_quote.strip().upper() or "USDT"
    if "-" in text:
        base, _, q = text.partition("-")
        return (base, q or quote) if base else None
    if len(text) > len(quote) and text.endswith(quote):
        return (text[: -len(quote)], quote)
    return (text, quote)


def build_pairs(symbols, default_quote):
    pairs, seen = [], set()
    for raw in symbols:
        item = normalize_symbol(raw, default_quote)
        if item and item not in seen:
            seen.add(item)
            pairs.append(item)
    return pairs or [("BTC", "USDT")]


def tradingview_symbol(base: str, quote: str, market: str = "perp",
                       exchange: str = "BINANCE") -> str:
    """TradingView 的完整符号，如 BINANCE:BTCUSDT.P。"""
    symbol = f"{base}{quote}"
    if str(market).lower() == "perp":
        symbol += ".P"
    return f"{exchange}:{symbol}"


def tradingview_url(base: str, quote: str, market: str = "perp",
                    exchange: str = "BINANCE") -> str:
    """拼 TradingView 图表地址。永续合约用 .P 后缀（如 BINANCE:BTCUSDT.P）。"""
    return ("https://www.tradingview.com/chart/?symbol="
            + tradingview_symbol(base, quote, market, exchange))


def tradingview_search(text: str, quote: str = "USDT", market: str = "perp",
                       exchange: str = "BINANCE", timeout=15.0):
    """用 TradingView 的搜索接口按名称找符号。

    给汉字名用的：TradingView 上「龙虾」登记成 LONGXIAUSDT.P、
    「我踏马来了」登记成 WOTAMALAILIAOUSDT.P —— 拼音代码，汉字查不到。
    这个接口会返回描述里带汉字的条目，正好用来反查。

    注意必须带 Referer，否则 403。
    """
    url = ("https://symbol-search.tradingview.com/symbol_search/v3/"
           f"?text={urllib.parse.quote(text)}&exchange={exchange}&lang=zh_CN"
           "&search_type=undefined&domain=production")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.tradingview.com/",
            # Referer 和 Origin 缺一不可，少了任何一个都 403
            "Origin": "https://www.tradingview.com",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        log(f"TradingView 搜索失败 ({text}): {exc}")
        return None

    want = f"{quote}.P".upper() if str(market).lower() == "perp" else str(quote).upper()
    for item in data.get("symbols") or []:
        sym = str(item.get("symbol") or "").strip()
        if not sym or str(item.get("exchange", "")).upper() != exchange.upper():
            continue
        # 只要正好是指定计价币的永续，别把 USD1/USDC 那些也抓进来
        if sym.upper().endswith(want):
            return f"{exchange}:{sym}"
    return None


def tradingview_resolve(base: str, quote: str = "USDT", market: str = "perp",
                        exchange: str = "BINANCE", timeout=15.0):
    """返回 TradingView 上真正能用的符号，找不到返回 None。

    先试直接拼的（BINANCE:BTCUSDT.P）；不存在就去搜——中文名合约在
    TradingView 上是用拼音登记的，只有搜才知道对应关系。
    """
    direct = tradingview_symbol(base, quote, market, exchange)
    if tradingview_has_symbol(direct, timeout):
        return direct
    found = tradingview_search(base, quote, market, exchange, timeout)
    if found:
        log(f"TradingView 符号映射: {base} -> {found}")
    return found


def tradingview_has_symbol(symbol: str, timeout=10.0):
    """问 TradingView 有没有这个品种。

    用它的 scanner 接口：存在返回 200 + {"close":...}，不存在返回 404。
    中文名合约在 TradingView 上是拼音代码（龙虾=LONGXIA），用汉字直接查必然
    404，所以要靠 tradingview_search 反查。

    返回 True / False；网络问题返回 None（表示"不知道"，按有处理）。
    """
    url = ("https://scanner.tradingview.com/symbol?symbol="
           + urllib.parse.quote(symbol) + "&fields=close")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (crypto-ticker)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 200
    except Exception:
        return None


def binance_chart_url(base: str, quote: str = "USDT") -> str:
    """币安自己的合约页。

    中文符号**必须百分号编码**，直接拼中文会 UnicodeEncodeError。
    实测这个页面没有 X-Frame-Options / CSP，可以 iframe 嵌入。
    """
    symbol = urllib.parse.quote(f"{base}{quote}")
    return f"https://www.binance.com/zh-CN/futures/{symbol}"


# ------------------------------------------------- 合约清单与模糊匹配 --

SYMBOLS_CACHE = os.path.join(APP_DIR, "symbols.json")
SYMBOLS_CACHE_TTL = 86400            # 清单缓存 24 小时
OI_PERIOD = "4h"                     # 持仓变化统计窗口
OI_SCAN_LIMIT = 0                    # 0 = 扫全部合约（币安才 525 个，全扫约 50 秒）
OI_MIN_VALUE = 0.0                   # 名义持仓下限，0 = 不设下限
                                     # 曾经设过 5000 万，结果把 W($10.6m)、
                                     # AIA($10m) 这些真正的大户全滤掉了——
                                     # 增仓榜上排前面的恰恰是小盘子，不能按规模筛。

FALLBACK_SYMBOLS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TON",
    "TRX", "DOT", "LTC", "BCH", "SUI", "APT", "ARB", "OP", "NEAR", "FIL",
    "ATOM", "ETC", "UNI", "AAVE", "ENA", "PEPE", "1000PEPE", "WIF", "ORDI",
    "TIA", "SEI", "INJ", "STX", "IMX", "RUNE", "LDO", "BLUR", "JTO", "PYTH",
    "WLD", "BONK", "1000BONK", "1000SHIB", "SHIB", "FLOKI", "1000FLOKI",
    "PENDLE", "ETHFI", "STRK", "AEVO", "BOME", "NOT", "ZK", "ZRO", "BLAST",
    "RENDER", "EIGEN", "SCR", "NEIRO", "TURBO", "GOAT", "MOODENG", "PNUT",
    "ACT", "USUAL", "MOVE", "THE", "PENGU", "TRUMP", "ANIME", "BERA", "KAITO",
    "IP", "RED", "SHELL", "PLUME", "TST", "BABY", "WAL", "NIL", "MUBARAK",
]


# 抓不到市值榜时的兜底名单（用于把大市值币从成交量榜里剔除）
FALLBACK_BIG_CAPS = [
    "BTC", "ETH", "USDT", "XRP", "BNB", "SOL", "USDC", "DOGE", "TRX", "ADA",
    "HYPE", "LINK", "XLM", "BCH", "AVAX", "SUI", "LTC", "TON", "SHIB", "DOT",
    "UNI", "AAVE", "PEPE", "NEAR", "APT", "ICP", "ETC", "POL", "ARB", "VET",
]


def _finish_overview(rows, big_caps=()):
    """把 (base, volume, change) 列表整理成清单 + 三组榜单。

    * 榜单只在成交额前 120 名里取——不然涨幅榜全是没人交易的妖币。
    * **成交量榜剔除大市值币**：BTC/ETH 永远霸榜，占着位置却看不出信息量，
      真正想看的是哪些小币/山寨币有行情。
    """
    rows = sorted(rows, key=lambda r: -r["volume"])
    liquid = rows[:120]
    excluded = {str(s).upper() for s in big_caps}
    small = [r for r in rows if r["base"] not in excluded]
    if not small:                     # 过滤太狠就退回不筛
        small = rows
    return {
        "symbols": [r["base"] for r in rows],
        "topVolume": small[:10],
        "topGainers": sorted(liquid, key=lambda r: -r["change"])[:10],
        "topLosers": sorted(liquid, key=lambda r: r["change"])[:10],
    }


def fetch_big_caps(limit=20, timeout=15.0):
    """抓市值前 limit 名的币种符号（CoinGecko 公开接口，不需要 key）。"""
    if limit <= 0:
        return []
    url = ("https://api.coingecko.com/api/v3/coins/markets"
           f"?vs_currency=usd&order=market_cap_desc&per_page={max(limit, 10)}&page=1")
    raw = _http_json(url, timeout)
    out = []
    for item in raw if isinstance(raw, list) else []:
        sym = str(item.get("symbol") or "").strip().upper()
        if sym and sym not in out:
            out.append(sym)
    return out[:limit]


def _overview_binance(timeout=20.0, big_caps=()):
    """币安 U 本位永续：exchangeInfo 定名单，24h 行情给成交额与涨跌幅。"""
    info = _http_json("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout)
    base_of = {}
    for item in info.get("symbols", []):
        if str(item.get("contractType", "")).upper() != "PERPETUAL":
            continue
        # 股票/商品/外汇永续（币安的 TradFi 合约）不算加密币，直接排除。
        # 平时 contractType 就是 TRADIFI_PERPETUAL，但币安改过一次分类，
        # 老缓存里混进过 SNDK/MU/CL 这类，所以这里再按 underlyingType 兜一道。
        if str(item.get("underlyingType", "")).upper() in (
                "EQUITY", "COMMODITY", "FOREX", "BOND", "STOCK"):
            continue
        if str(item.get("status", "")).upper() != "TRADING":
            continue
        if str(item.get("quoteAsset", "")).upper() != "USDT":
            continue
        symbol = str(item.get("symbol") or "")
        base = str(item.get("baseAsset") or "").strip().upper()
        if symbol and base:
            base_of[symbol] = base

    tickers = _http_json("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout)
    best = {}
    for item in tickers:
        base = base_of.get(item.get("symbol"))
        if not base:
            continue
        try:
            volume = float(item.get("quoteVolume") or 0.0)
            change = float(item.get("priceChangePercent") or 0.0)
        except (TypeError, ValueError):
            continue
        current = best.get(base)
        if current is None or volume > current["volume"]:
            best[base] = {"base": base, "volume": volume, "change": change}
    return _finish_overview(list(best.values()), big_caps)


def _overview_okx(timeout=20.0, big_caps=()):
    """OKX 永续备用源；成交额用 volCcy24h × 最新价折算成计价币口径。"""
    raw = _http_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout)
    rows = []
    for item in raw.get("data", []):
        inst = str(item.get("instId") or "")
        if not inst.endswith("-USDT-SWAP"):
            continue
        base = inst.split("-")[0].upper()
        try:
            last = float(item.get("last") or 0.0)
            open24 = float(item.get("open24h") or 0.0)
            vol_ccy = float(item.get("volCcy24h") or 0.0)
        except (TypeError, ValueError):
            continue
        if last <= 0 or open24 <= 0:
            continue
        rows.append({
            "base": base,
            "volume": vol_ccy * last,
            "change": (last - open24) / open24 * 100.0,
        })
    return _finish_overview(rows, big_caps)


def fetch_rankings(valid_bases, big_caps=(), timeout=15.0):
    """只抓 24h 行情来重算榜单——比 exchangeInfo 轻得多，可以几分钟刷一次。

    合约清单（哪些币有永续）一天才变，但涨幅榜几分钟就换一批，
    所以必须分开刷新，否则顶部滚动条会显示一整天的旧榜单。
    """
    tickers = _http_json("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout)
    valid = {str(b).upper() for b in valid_bases}
    best = {}
    for item in tickers:
        symbol = str(item.get("symbol") or "")
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        if base not in valid:
            continue
        try:
            volume = float(item.get("quoteVolume") or 0.0)
            change = float(item.get("priceChangePercent") or 0.0)
        except (TypeError, ValueError):
            continue
        current = best.get(base)
        if current is None or volume > current["volume"]:
            best[base] = {"base": base, "volume": volume, "change": change}
    return _finish_overview(list(best.values()), big_caps)


def fetch_oi_changes(bases, quote="USDT", workers=16, timeout=8.0):
    """并发抓各币的 4 小时持仓量变化百分比。

    用币安自己的 openInterestHist：period=4h & limit=2 正好给出
    「4 小时前」和「现在」两个点，相除就是变化率。
    coinalyze 的同类数据要付费 API key，扒不了；币安这个是免 key 的。
    """
    period = OI_PERIOD

    def one(base):
        symbol = f"{base}{quote}"
        url = ("https://fapi.binance.com/futures/data/openInterestHist"
               f"?symbol={symbol}&period={period}&limit=2")
        try:
            data = _http_json(url, timeout, attempts=2)
        except Exception:
            return None
        if not isinstance(data, list) or len(data) < 2:
            return None
        try:
            old = float(data[0]["sumOpenInterest"])
            new = float(data[1]["sumOpenInterest"])
            value = float(data[1].get("sumOpenInterestValue") or 0.0)
        except (KeyError, TypeError, ValueError):
            return None
        if old <= 0:
            return None
        return {"base": base, "oi": new, "oiValue": value,
                "change": (new - old) / old * 100.0}

    out = []
    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for row in pool.map(one, bases):
                if row:
                    out.append(row)
    except Exception as exc:
        log(f"持仓量抓取失败: {exc}")
    return out


def rank_oi(rows, limit=10, min_value=None):
    """按 4 小时持仓**增加**百分比排序。

    只看增加：持仓减少说明在平仓离场，不是新资金进场，没有参考价值。
    这条是硬规则——候选不够时放宽名义持仓下限，但**绝不放宽"只保留正数"**。

    注意名义下限默认是 0（不筛）。之前设成 5000 万，把 W、AIA 这类
    真正排榜首的小盘子全滤掉了，榜单和 coinalyze 对不上。
    """
    if min_value is None:
        min_value = OI_MIN_VALUE
    gainers = [r for r in rows if float(r.get("change") or 0.0) > 0]
    keep = [r for r in gainers if float(r.get("oiValue") or 0.0) >= min_value]
    if len(keep) < limit:
        keep = gainers                      # 放宽名义下限，但仍然只看增仓
    return sorted(keep, key=lambda r: -float(r.get("change") or 0.0))[:limit]


# ------------------------------------------------- 全品种（含 TradFi）--
# 币安除了加密永续，还有一批 **TRADIFI_PERPETUAL**：黄金 XAU、白银 XAG、
# 股票 TSLA/NVDA/AAPL/MSFT/META/AMZN/COIN/MSTR/GOOGL、指数 US500……
#
# ⚠️ 这两份名单**故意分开**：
#   * 加密榜单（涨幅/跌幅/成交量/增仓）必须排除 TradFi，
#     不然涨幅榜全被股票占满，看加密行情就没意义了（老版本就是这么设计的）
#   * 「全品种扫盘」要全都看见，所以单独抓一份
TRADFI_CATS = {
    "EQUITY": "股票", "STOCK": "股票", "COMMODITY": "商品",
    "FOREX": "外汇", "BOND": "债券", "INDEX": "指数",
}
_ALL_CACHE = {"rows": [], "ts": 0.0}
_ALL_LOCK = threading.Lock()
ALL_SYMBOLS_TTL = 60.0                   # 秒；扫盘页每分钟拉一次，够新鲜也够省


def fetch_all_symbols(timeout=25.0):
    """全部 USDT 永续（加密 + 币安 TradFi），按成交额倒序。

    返回的每一行都带 `cat`（加密/股票/黄金/白银/商品/指数…），
    扫盘页靠它做分类筛选。
    """
    info = _http_json("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout)
    meta = {}
    for item in info.get("symbols", []):
        ctype = str(item.get("contractType", "")).upper()
        if ctype not in ("PERPETUAL", "TRADIFI_PERPETUAL"):
            continue
        if str(item.get("status", "")).upper() != "TRADING":
            continue
        if str(item.get("quoteAsset", "")).upper() != "USDT":
            continue
        symbol = str(item.get("symbol") or "")
        base = str(item.get("baseAsset") or "").strip().upper()
        if not symbol or not base:
            continue
        utype = str(item.get("underlyingType", "")).upper()
        tradfi = ctype == "TRADIFI_PERPETUAL" or utype in TRADFI_CATS
        if tradfi:
            cat = TRADFI_CATS.get(utype) or "TradFi"
            # 黄金/白银单独挑出来：用户明确点名了"黄金合约"
            if base in ("XAU", "XAUT"):
                cat = "黄金"
            elif base == "XAG":
                cat = "白银"
            kind = "tradfi"
        else:
            cat, kind = "加密", "crypto"
        meta[symbol] = {"base": base, "cat": cat, "kind": kind,
                        "ctype": ctype, "utype": utype}

    tickers = _http_json("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout)
    rows = []
    for item in tickers:
        m = meta.get(item.get("symbol"))
        if not m:
            continue
        try:
            rows.append({
                "base": m["base"],
                "sym": item["symbol"],
                "cat": m["cat"],
                "kind": m["kind"],
                "price": float(item.get("lastPrice") or 0.0),
                "change": float(item.get("priceChangePercent") or 0.0),
                "volume": float(item.get("quoteVolume") or 0.0),
                "high": float(item.get("highPrice") or 0.0),
                "low": float(item.get("lowPrice") or 0.0),
            })
        except (TypeError, ValueError, KeyError):
            continue
    # 同一个 base 可能既有 XAU 也有 XAUT：按成交额保留大的那个，避免列表重复
    best = {}
    for row in sorted(rows, key=lambda r: -r["volume"]):
        best.setdefault(row["base"], row)
    # ★ 按**名字 A→Z** 排（用户要求：扫盘时按名字顺着扫，好找）。
    #   成交额仍然留在每一行里显示，只是不再拿它排序。
    return sorted(best.values(), key=lambda r: r["base"].upper())


_ALL_OI = {}                            # {"BTCUSDT": 持仓名义价值(USDT), ...}
_ALL_OI_TS = {"t": 0.0, "running": False}


def _attach_oi(rows):
    for r in rows:
        r["oi"] = _ALL_OI.get(r.get("sym"))


def _fill_all_oi(rows):
    """后台补齐全品种的**持仓名义价值**（持仓量 × 现价）。

    为什么不同步做：币安**没有批量持仓接口**，741 个品种得一个一个查
    （16 线程约 40 秒）。所以丢后台慢慢补，页面先显示 `--`，
    补好之后下一次轮询（1 分钟）就有数了。

    持仓用**名义价值**才有横向可比性 —— 不同币"一张"的大小差很多。
    """
    from concurrent.futures import ThreadPoolExecutor

    def one(row):
        try:
            data = _http_json("https://fapi.binance.com/fapi/v1/openInterest"
                              f"?symbol={row['sym']}", 8.0)
            qty = float(data.get("openInterest") or 0.0)
            return row["sym"], qty * float(row.get("price") or 0.0)
        except Exception:
            return row["sym"], None

    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            for sym, val in pool.map(one, rows):
                if val:
                    _ALL_OI[sym] = val
        _ALL_OI_TS["t"] = time.time()
        log(f"全品种持仓量已补齐：{len(_ALL_OI)} 个")
    except Exception as exc:
        log(f"持仓量补齐失败: {exc}")
    finally:
        _ALL_OI_TS["running"] = False


def load_all_symbols(force=False):
    """带内存缓存的全量名单（60 秒）。扫盘页和"输入币种"的候选都用它。

    每一行都带 `volume`（24h 成交额）和 `oi`（持仓名义价值，后台补，
    没补到就是 None）—— 用户要求扫盘页里**每个品种**都显示这两个数。
    """
    with _ALL_LOCK:
        fresh = (time.time() - _ALL_CACHE["ts"]) < ALL_SYMBOLS_TTL
        if _ALL_CACHE["rows"] and fresh and not force:
            rows = list(_ALL_CACHE["rows"])
            _attach_oi(rows)
            _kick_oi_refresh(rows)
            return rows
    try:
        rows = fetch_all_symbols()
    except Exception as exc:
        log(f"全品种名单抓取失败: {exc}")
        with _ALL_LOCK:
            rows = list(_ALL_CACHE["rows"])
    if rows:
        with _ALL_LOCK:
            _ALL_CACHE["rows"] = rows
            _ALL_CACHE["ts"] = time.time()
        tradfi = [r["base"] for r in rows if r["kind"] == "tradfi"]
        log(f"全品种名单已更新：{len(rows)} 个（其中 TradFi {len(tradfi)} 个："
            f"{', '.join(tradfi[:8])}…）")
    out = list(rows)
    _attach_oi(out)
    _kick_oi_refresh(out)
    return out


def _kick_oi_refresh(rows):
    """持仓量超过 10 分钟没更新就后台补一次（不阻塞请求）。"""
    if (time.time() - _ALL_OI_TS["t"]) <= 600 or _ALL_OI_TS["running"] or not rows:
        return
    _ALL_OI_TS["running"] = True
    threading.Thread(target=_fill_all_oi, args=(list(rows),), daemon=True).start()


def match_universe(crypto_universe):
    """给"输入币种"用的匹配名单：加密 + TradFi（黄金/股票也能搜到）。

    榜单仍然只用加密那份（见 `_overview_binance` 里的排除逻辑）。
    """
    names = list(crypto_universe or [])
    seen = set(n.upper() for n in names)
    try:
        for row in load_all_symbols():
            base = row.get("base")
            if base and base.upper() not in seen:
                seen.add(base.upper())
                names.append(base)
    except Exception:
        pass
    return names


def fetch_market_overview(timeout=20.0, big_cap_limit=20):
    """先币安后 OKX，两个都挂才算失败。

    同时抓一份市值榜用于把大市值币从成交量榜剔除；抓不到就用内置兜底名单。
    """
    big_caps = []
    if big_cap_limit > 0:
        try:
            big_caps = fetch_big_caps(big_cap_limit, timeout)
            log(f"市值榜已获取：前 {len(big_caps)} 名 {big_caps[:6]}…")
        except Exception as exc:
            big_caps = FALLBACK_BIG_CAPS[:big_cap_limit]
            log(f"市值榜抓取失败，用兜底名单: {exc}")

    errors = []
    for fetcher in (_overview_binance, _overview_okx):
        try:
            data = fetcher(timeout, big_caps)
            if data.get("symbols"):
                data["bigCaps"] = list(big_caps)
                return data
            errors.append(f"{fetcher.__name__}: 空结果")
        except Exception as exc:
            errors.append(f"{fetcher.__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def load_market_overview(force=False):
    """带磁盘缓存的合约总览；缓存过期或强制时重新拉取，失败则退回缓存。"""
    cached = None
    stamp = 0.0
    try:
        with open(SYMBOLS_CACHE, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        stamp = float(cached.get("ts", 0))
    except Exception:
        cached = None

    if cached and cached.get("symbols") and not force \
            and (time.time() - stamp) < SYMBOLS_CACHE_TTL:
        return cached

    try:
        fresh = fetch_market_overview()
        if fresh.get("symbols"):
            fresh["ts"] = time.time()
            try:
                with open(SYMBOLS_CACHE, "w", encoding="utf-8") as fh:
                    json.dump(fresh, fh, ensure_ascii=False)
            except Exception:
                pass
            log(f"合约清单已更新：{len(fresh['symbols'])} 个")
            return fresh
    except Exception as exc:
        log(f"拉取合约清单失败: {exc}")

    if cached and cached.get("symbols"):
        return cached
    names = list(FALLBACK_SYMBOLS)
    return {"symbols": names, "topVolume": [], "topGainers": [], "topLosers": [], "ts": 0}


def load_symbol_universe(force=False):
    """只要清单（按成交额排序）。"""
    return load_market_overview(force).get("symbols") or list(FALLBACK_SYMBOLS)


def match_symbols(query, universe, limit=9):
    """模糊匹配：精确 > 前缀 > 子串。

    universe 已按成交额排序，所以各组内**保持原顺序**——这样输入 B 先出 BTC，
    而不是按字母或长度把冷门小币排到前面。
    """
    q = (query or "").strip().upper().rstrip(",")
    if not q:
        return []
    exact, prefix, contains = [], [], []
    for name in universe:
        if name == q:
            exact.append(name)
        elif name.startswith(q):
            prefix.append(name)
        elif q in name:
            contains.append(name)
    return (exact + prefix + contains)[:limit]


# ---------------------------------------------------------------- 数据抓取 --

def _http_json(url: str, timeout: float = 6.0, attempts: int = 3):
    """取 JSON。失败自动重试——代理环境下 SSL 偶发被重置很常见，一次失败不代表不通。"""
    last = None
    for attempt in range(max(1, attempts)):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (crypto-ticker)", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:            # noqa: BLE001 - 网络异常种类多，统一重试
            last = exc
            if attempt + 1 < attempts:
                time.sleep(0.35 * (attempt + 1))
    raise last


def _row(price, change, high=None, low=None):
    return {"price": float(price), "change": float(change), "high": high, "low": low}


def fetch_binance(pairs, market="perp", timeout=6.0):
    """币安 24hr ticker。market=perp 走 U 本位永续合约，否则走现货。"""
    base = ("https://fapi.binance.com/fapi/v1/ticker/24hr" if market == "perp"
            else "https://api.binance.com/api/v3/ticker/24hr")
    symbols = [b + q for b, q in pairs]
    # ensure_ascii=False 是必须的：默认 True 会把「龙虾」转义成字面文本
    # \u9f99\u867e，币安收到后当成无效符号，整个批量请求直接 400。
    query = urllib.parse.quote(
        json.dumps(symbols, separators=(",", ":"), ensure_ascii=False))
    try:
        raw = _http_json(base + "?symbols=" + query, timeout)
        if isinstance(raw, dict):                # 出错时返回 {"code":..,"msg":..}
            raise RuntimeError(raw.get("msg") or str(raw))
    except Exception as exc:
        # 批量整批失败（比如某个符号币安不认）不能让所有币都掉线，
        # 退化成逐个查，至少能保住能查到的那些。
        log(f"币安批量请求失败，改逐个查: {exc}")
        raw = []

    by_symbol = {}
    for item in raw:
        key = str(item.get("symbol", "")).upper()
        by_symbol[key] = item
        by_symbol.setdefault(str(item.get("symbol", "")), item)

    out = {}
    missing = []
    for base_coin, quote in pairs:
        item = by_symbol.get((base_coin + quote).upper()) or by_symbol.get(base_coin + quote)
        if item is None:
            missing.append((base_coin, quote))
            continue
        out[(base_coin, quote)] = _row(item["lastPrice"], item["priceChangePercent"],
                                       item.get("highPrice"), item.get("lowPrice"))

    for base_coin, quote in missing:             # 批量失败 -> 单币种重试
        try:
            sym = urllib.parse.quote(f"{base_coin}{quote}")
            one = _http_json(f"{base}?symbol={sym}", timeout)
            out[(base_coin, quote)] = _row(one["lastPrice"], one["priceChangePercent"],
                                           one.get("highPrice"), one.get("lowPrice"))
        except Exception as exc:
            log(f"跳过 {base_coin}{quote}: {exc}")
    return out, ("Binance 永续" if market == "perp" else "Binance 现货")


def fetch_okx(pairs, market="perp", timeout=6.0):
    """币安不通时的备用源。永续用 SWAP，现货用 SPOT。"""
    inst_type = "SWAP" if market == "perp" else "SPOT"
    raw = _http_json(f"https://www.okx.com/api/v5/market/tickers?instType={inst_type}", timeout)
    by_id = {str(item.get("instId", "")).upper(): item for item in raw.get("data", [])}
    out = {}
    for base, quote in pairs:
        inst = f"{base}-{quote}-SWAP" if market == "perp" else f"{base}-{quote}"
        item = by_id.get(inst)
        if not item:
            continue
        last = float(item.get("last") or 0)
        open24 = float(item.get("open24h") or 0)
        change = ((last - open24) / open24 * 100.0) if open24 else 0.0
        out[(base, quote)] = _row(last, change, item.get("high24h"), item.get("low24h"))
    if not out:
        raise RuntimeError("OKX 无匹配币种")
    return out, ("OKX 永续" if market == "perp" else "OKX 现货")


def fetch_all(pairs, market="perp", timeout=6.0):
    """先币安后 OKX，两个都挂才算失败。"""
    errors = []
    for fetcher in (fetch_binance, fetch_okx):
        try:
            rows, source = fetcher(pairs, market, timeout)
            if rows:
                return rows, source
            errors.append(f"{fetcher.__name__}: 空结果")
        except Exception as exc:
            errors.append(f"{fetcher.__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


# ---------------------------------------------------------------- 格式化 --

def fmt_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:,.2f}" if value >= 100 else f"{value:.3f}"
    if value >= 0.01:
        return f"{value:.4f}"
    return f"{value:.6f}"


def fmt_level(value: float) -> str:
    """仓位标记用的紧凑价位：82000 → `82,000`，2492.5 → `2,492.5`。

    规则：能省的小数一律省掉（不摆没用的 .00），但用户填了的精度要留住 ——
    小币种填 0.1407、109.8123 这种，砍成两位就没意义了。
    """
    if value >= 1:
        s = f"{value:,.2f}" if value >= 1000 else f"{value:,.4f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s
    return fmt_price(value)


# 精选字体预设：(显示名, 真实家族名)
FONT_PRESETS = [
    ("Bahnschrift SemiLight", "Bahnschrift SemiLight"),
    ("Bahnschrift Light", "Bahnschrift Light"),
    ("Segoe UI Variable Display Light", "Segoe UI Variable Display Light"),
    ("Segoe UI Semilight", "Segoe UI Semilight"),
    ("Segoe UI", "Segoe UI"),
    ("Cascadia Mono Light", "Cascadia Mono Light"),
    ("Cascadia Mono", "Cascadia Mono"),
    ("Consolas", "Consolas"),
    ("Noto Sans SC Light", "Noto Sans SC Light"),
    ("Microsoft YaHei UI", "Microsoft YaHei UI"),
]

TEXT_EFFECTS = [
    ("细描边（默认）", "outline"),
    ("投影", "shadow"),
    ("无（最干净）", "none"),
    ("粗描边（背景很花时用）", "outline_full"),
]

EFFECT_OFFSETS = {
    "outline": [(-1, 0), (1, 0), (0, -1), (0, 1)],
    "outline_full": [(-1, 0), (1, 0), (0, -1), (0, 1),
                     (-1, -1), (1, -1), (-1, 1), (1, 1)],
    "shadow": [(1, 1)],
    "none": [],
}


DARK_TEXT = {"sym": "#2b2b2b", "price": "#000000", "change": "#000000",
             "dim": "#9a9a9a", "outline": "#ffffff"}
LIGHT_TEXT = {"sym": "#c8d2dd", "price": "#eaecef", "change": "#eaecef",
              "dim": "#848e9c", "outline": "#04070a"}


def text_palette(cfg: dict) -> dict:
    """黑色文字配浅色描边，白色文字配深色描边。"""
    return DARK_TEXT if str(cfg.get("text_color", "black")).lower() == "black" else LIGHT_TEXT


def resolve_font(root: tk.Tk, wanted: str = None) -> str:
    """挑一个系统里真实存在的字体，找不到就按预设顺序回退。"""
    families = set(tkfont.families(root))
    want = wanted or DEFAULT_CONFIG["font_family"]
    if want in families:
        return want
    for _label, family in FONT_PRESETS:
        if family in families:
            return family
    for name in ("Segoe UI", "Arial"):
        if name in families:
            return name
    return "TkDefaultFont"


def pick_ui_font(root: tk.Tk) -> str:
    families = set(tkfont.families(root))
    for name in ("Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei"):
        if name in families:
            return name
    return "TkDefaultFont"


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def lerp_color(color_a: str, color_b: str, t: float) -> str:
    """在两个 #rrggbb 之间插值：t=0 取 a，t=1 取 b。用于闪烁淡出。"""
    t = max(0.0, min(1.0, t))
    try:
        ar, ag, ab = int(color_a[1:3], 16), int(color_a[3:5], 16), int(color_a[5:7], 16)
        br, bg, bb = int(color_b[1:3], 16), int(color_b[3:5], 16), int(color_b[5:7], 16)
    except Exception:
        return color_a
    return "#%02x%02x%02x" % (
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab + (bb - ab) * t),
    )


# ================================================================== 主程序 ==

# ------------------------------------------------------- 单页图表服务 --

CHART_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>行情图表</title>
<style>
  html,body{margin:0;height:100%;background:#0b0e11;overflow:hidden}
  #bar{height:30px;display:flex;align-items:center;gap:10px;padding:0 12px;
       background:#161b22;border-bottom:1px solid #21262d;
       color:#c9d1d9;font:13px "Microsoft YaHei UI","Segoe UI",sans-serif}
  #sym{color:#58a6ff;font-weight:600}
  #px{font-weight:600}
  #tip{color:#6e7681;font-size:12px;margin-left:auto}
  #tvlink{color:#58a6ff;font-size:12px;text-decoration:none;cursor:pointer}
  #tvlink:hover{text-decoration:underline}
  #periods{display:flex;gap:2px}
  #periods a{padding:2px 8px;border-radius:4px;cursor:pointer;
             color:#8b949e;font-size:12px;background:#21262d;text-decoration:none}
  #periods a:hover{background:#30363d;color:#c9d1d9}
  #periods a.on{background:#58a6ff;color:#0b0e11;font-weight:600}
  body{display:flex;flex-direction:column}
  #bar{flex:0 0 auto}
  #main{flex:1 1 auto;display:flex;min-height:0}
  /* 扫盘栏：点着一路往下看，不用回去动行情条 */
  #side{flex:0 0 236px;display:flex;flex-direction:column;
        background:#0e1116;border-right:1px solid #21262d;min-height:0}
  #sidehead{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;
            padding:5px 8px 5px 10px;border-bottom:1px solid #21262d;
            color:#8b949e;font:12px "Microsoft YaHei UI","Segoe UI",sans-serif}
  #rf{cursor:pointer;color:#58a6ff;padding:1px 6px;border-radius:4px;background:#1b222c}
  #rf:hover{background:#26303d}
  #groups{flex:1 1 auto;overflow-y:auto;overscroll-behavior:contain}
  .grp{padding:2px 0 6px}
  .grp h4{margin:0;padding:6px 10px 3px;color:#8b949e;font-weight:600;
          font:11px "Microsoft YaHei UI","Segoe UI",sans-serif;letter-spacing:.3px}
  .it{display:flex;align-items:center;gap:6px;padding:3px 10px;cursor:pointer;
      font:12px "Microsoft YaHei UI","Segoe UI",sans-serif;color:#c9d1d9}
  .it:hover{background:#1b222c}
  .it.cur{background:#1f6feb;color:#fff}
  .it.cur .pct{color:#fff}
  .rk{flex:0 0 16px;color:#6e7681;text-align:right;font-size:11px}
  .nm{flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .nm b{color:#58a6ff;font-weight:600}
  .it.cur .nm b{color:#fff}
  .pct{flex:0 0 auto;font-variant-numeric:tabular-nums;font-size:11.5px}
  .up{color:#0ecb81}
  .down{color:#f6465d}
  .vol{color:#c9d1d9}
  #groups::-webkit-scrollbar{width:8px}
  #groups::-webkit-scrollbar-thumb{background:#30363d;border-radius:4px}
  /* ── 全品种扫盘页：侧栏更宽，多一列价格和分类标签 ── */
  body.scan #side{flex:0 0 402px}
  #scantools{display:none;flex:0 0 auto;border-bottom:1px solid #21262d;padding-bottom:2px}
  #scanq{width:calc(100% - 16px);box-sizing:border-box;margin:7px 8px 5px;padding:4px 8px;
        border-radius:6px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9;
        font:12px "Microsoft YaHei UI","Segoe UI",sans-serif;outline:none}
  #scanq:focus{border-color:#58a6ff}
  #scancats{display:flex;flex-wrap:wrap;gap:4px;padding:0 8px 5px}
  #scanacts{display:flex;gap:6px;padding:0 8px 6px}
  .chip{padding:1px 8px;border-radius:10px;background:#21262d;color:#8b949e;
        font:11px "Microsoft YaHei UI","Segoe UI",sans-serif;cursor:pointer;user-select:none}
  .chip:hover{background:#30363d;color:#c9d1d9}
  .chip.on{background:#1f6feb;color:#fff}
  #scanhint{padding:0 9px 6px;color:#6e7681;
        font:11px "Microsoft YaHei UI","Segoe UI",sans-serif}
  #backchart{cursor:pointer;color:#58a6ff;font-size:11.5px}
  #backchart:hover{text-decoration:underline}
  body.scan .it{gap:5px}
  body.scan .rk{flex:0 0 24px}
  body.scan .nm{flex:0 1 auto;max-width:84px}
  .tag{flex:0 0 auto;font-size:10px;line-height:15px;color:#f0b90b;
       border:1px solid #4a3600;background:#2a1f00;border-radius:3px;padding:0 3px}
  .px{flex:0 0 auto;color:#8b949e;font-size:11px;
      font-variant-numeric:tabular-nums;min-width:56px;text-align:right}
  /* 24h 成交额 / 持仓名义价值（每个品种都显示，用币安数据） */
  .vol{flex:0 0 auto;color:#6e7681;font-size:10.5px;
       font-variant-numeric:tabular-nums;min-width:46px;text-align:right}
  .vol.oi{color:#7d8590}
  body.scan .it.cur .vol{color:#dbe4f0}
  /* 收藏 ♥（点一下就收藏，收藏的实心变红） */
  .fav{flex:0 0 14px;text-align:center;color:#484f58;cursor:pointer;font-size:12px}
  .fav:hover{color:#f6465d}
  .fav.on{color:#f6465d}
  body.scan .it.cur .fav{color:#fff}
  body.scan .it.cur .fav.on{color:#ffb3b3}
  body.day .fav{color:#b9c0c8}
  body.day .fav.on{color:#cf222e}
  body.scan .it.cur .px,body.scan .it.cur .tag{color:#fff;border-color:#8ab4f8}
  #chart{flex:1 1 auto;min-width:0;height:100%;position:relative}
  /* 趋势线画在图表上面的一层透明 canvas 上。
     pointer-events:none 是关键——否则它会把 K 线的拖动/缩放全挡住。 */
  #overlay{position:absolute;left:0;top:0;pointer-events:none;z-index:5}
  #draw,#undo,#clr,#clone{cursor:pointer;color:#8b949e;padding:2px 8px;border-radius:4px;
        background:#21262d;font-size:12px;user-select:none}
  #draw:hover,#undo:hover,#clr:hover,#clone:hover{background:#30363d;color:#c9d1d9}
  #draw.on{background:#f0b90b;color:#0b0e11;font-weight:600}
  #undo,#clr,#clone{display:none}
  #clr:hover{color:#f6465d}
  #tlcount{color:#6e7681;font-size:11.5px}
  #err{display:none;position:absolute;left:50%;top:14px;transform:translateX(-50%);
       padding:5px 12px;border-radius:5px;background:#3d1418;border:1px solid #f6465d;
       color:#ffb3b3;font:12px "Microsoft YaHei UI","Segoe UI",sans-serif;z-index:9}
  #diag{display:none;position:absolute;left:50%;top:44px;transform:translateX(-50%);
        padding:4px 10px;border-radius:5px;background:#1b222c;border:1px solid #30363d;
        color:#8b949e;font:11px Consolas,monospace;z-index:9;white-space:pre}

  /* ── 白天主题（v0.18）：只覆盖颜色，不动布局 ──────────────────
     行情条那边「设置 → 主题皮肤」切到白天时，页面会拿到 theme=day，
     JS 给 body 加上 .day 类，这一整块就生效（图表画布由 applyTheme() 重设）。 */
  body.day{background:#f6f8fa}
  body.day #bar{background:#ffffff;border-bottom-color:#d0d7de;color:#1f2328}
  body.day #sym{color:#0969da}
  body.day #tip{color:#8c959f}
  body.day #tvlink{color:#0969da}
  body.day #periods a{background:#eef1f4;color:#59636e}
  body.day #periods a:hover{background:#e3e8ee;color:#1f2328}
  body.day #periods a.on{background:#0969da;color:#ffffff}
  body.day #draw,body.day #undo,body.day #clr,body.day #clone{
        background:#eef1f4;color:#59636e}
  body.day #draw:hover,body.day #undo:hover,body.day #clr:hover,body.day #clone:hover{
        background:#e3e8ee;color:#1f2328}
  body.day #draw.on{background:#bf8700;color:#ffffff}
  body.day #tlcount{color:#8c959f}
  body.day #side{background:#f6f8fa;border-right-color:#d0d7de}
  body.day #sidehead{border-bottom-color:#d0d7de;color:#59636e}
  body.day #rf{background:#eef1f4;color:#0969da}
  body.day #rf:hover{background:#e3e8ee}
  body.day #backchart{color:#0969da}
  body.day .grp h4{color:#59636e}
  body.day .it{color:#1f2328}
  body.day .it:hover{background:#eef1f4}
  body.day .it.cur{background:#0969da;color:#ffffff}
  body.day .rk{color:#8c959f}
  body.day .nm b{color:#0969da}
  body.day .it.cur .nm b{color:#ffffff}
  body.day .px{color:#59636e}
  body.day .vol{color:#8c959f}
  body.day .vol.oi{color:#59636e}
  body.day .up{color:#1a7f37}
  body.day .down{color:#cf222e}
  body.day .tag{color:#9a6700;border-color:#d4a72c;background:#fff8c5}
  body.day #scanq{background:#ffffff;border-color:#d0d7de;color:#1f2328}
  body.day #scanq:focus{border-color:#0969da}
  body.day .chip{background:#eef1f4;color:#59636e}
  body.day .chip:hover{background:#e3e8ee;color:#1f2328}
  body.day .chip.on{background:#0969da;color:#ffffff}
  body.day #scanhint{color:#8c959f}
  body.day #diag{background:#ffffff;border-color:#d0d7de;color:#59636e}
</style></head>
<body>
<div id="bar">当前：<span id="sym">等待行情条…</span>
  <span id="px"></span>
  <span id="periods"></span>
  <span id="draw" title="点第一下放起点、第二下成线；可以接着画下一条，Esc 退出">✏ 画趋势线</span>
  <span id="undo" title="撤销最后一条趋势线（Ctrl+Z）">↶ 撤销</span>
  <span id="clone" title="克隆选中的那条线（快捷键 C），再拖到别处">⧉ 克隆</span>
  <span id="clr" title="清空本品种本周期画的所有趋势线">清空</span>
  <span id="tlcount"></span>
  <a id="tvlink" target="_blank" rel="noopener">在 TradingView 打开 ↗</a>
  <span id="tip">点左侧榜单逐个扫 · 单击=切图（双击也一样，不动自选）</span></div>
<div id="main">
  <div id="side">
    <div id="sidehead"><span id="sidetitle">榜单扫盘</span>
      <span><span id="backchart" style="display:none">← 行情图表</span>
      <span id="rf">刷新</span></span></div>
    <div id="scantools">
      <input id="scanq" placeholder="筛选：BTC / 黄金 / 股票…" autocomplete="off" spellcheck="false">
      <div id="scancats"></div>
      <div id="scanhint">↑↓ 快速切下一个 · 价 · 24h额 · 持仓 · 涨跌</div>
      <div id="scanacts">
        <span class="chip" id="favcopy" title="把收藏的品种按 TradingView 符号格式复制到剪贴板">⧉ 复制收藏</span>
        <span class="chip" id="favtv" title="用你自己的浏览器打开 TradingView（带你的登录/画线）">★ 我的 TradingView</span>
      </div>
    </div>
    <div id="groups"></div>
  </div>
  <div id="chart"><canvas id="overlay"></canvas></div>
</div>
<div id="err"></div>
<div id="diag">诊断启动中…</div>
<script src="/lib/lightweight-charts.js"></script>
<script>
var chart=null, candleSeries=null, volSeries=null, cur=null;
var dataKey=null;                        // 当前 K 线对应的 品种|周期
var SCAN = __SCAN_MODE__;                // true = 全品种扫盘页（同一份代码，两副面孔）
var pageLoadedAt = Date.now();           // 刚加载的 2 秒内不响应"切模式"指令（见 tick）
var INTERVALS=['5m','15m','1h','4h','1d','1w','1M'];
var iv = localStorage.getItem('chartInterval') || '1h';
if(INTERVALS.indexOf(iv) < 0) iv = '1h';

/* 出错了要看得见。
   以前 K 线拉不到是"静默失败"——页面一片黑，用户完全不知道是网络问题
   还是程序坏了。现在把错误写进 #err，一眼能看出来。 */
window.onerror = function(msg, src, line){
  var e=document.getElementById('err');
  if(e){ e.textContent = '脚本错误: ' + msg + ' @' + line; e.style.display='block'; }
};

function showErr(t){
  var e=document.getElementById('err');
  if(!e) return;
  e.textContent = t;
  e.style.display = 'block';
}
function clearErr(){
  var e=document.getElementById('err');
  if(e) e.style.display = 'none';
}

var THEME = '__THEME__';                 // 'day' / 'night'（由行情条那边下发）

/** 图表画布的颜色（lightweight-charts 是 JS 画的，CSS 管不到它） */
function themeColors(){
  return THEME === 'day'
    ? {bg:'#ffffff', fg:'#1f2328', grid:'#eaeef2', border:'#d0d7de',
       volUp:'rgba(26,127,55,0.35)', volDown:'rgba(207,34,46,0.35)'}
    : {bg:'#0b0e11', fg:'#c9d1d9', grid:'#1c2128', border:'#21262d',
       volUp:'rgba(14,203,129,0.45)', volDown:'rgba(246,70,93,0.45)'};
}

/** 切主题：body 上加 class（CSS 那边覆盖颜色）+ 重设图表配色 */
function applyTheme(){
  var c = themeColors();
  document.body.classList.toggle('day', THEME === 'day');
  if(chart){
    chart.applyOptions({
      layout:{background:{color:c.bg}, textColor:c.fg},
      grid:{vertLines:{color:c.grid}, horzLines:{color:c.grid}},
      rightPriceScale:{borderColor:c.border},
      timeScale:{borderColor:c.border}
    });
  }
  drawTrend();          // 叠加层跟着重画（底色变了）
}

function initChart(){
  var c = themeColors();
  chart = LightweightCharts.createChart(document.getElementById('chart'), {
    layout:{background:{color:c.bg}, textColor:c.fg, fontSize:11},
    grid:{vertLines:{color:c.grid}, horzLines:{color:c.grid}},
    rightPriceScale:{borderColor:c.border},
    timeScale:{borderColor:c.border, timeVisible:true, secondsVisible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    autoSize:true
  });
  candleSeries = chart.addCandlestickSeries({
    upColor:'#0ecb81', downColor:'#f6465d',
    borderUpColor:'#0ecb81', borderDownColor:'#f6465d',
    wickUpColor:'#0ecb81', wickDownColor:'#f6465d'
  });
  volSeries = chart.addHistogramSeries({
    priceFormat:{type:'volume'}, priceScaleId:'vol'
  });
  chart.priceScale('vol').applyOptions({scaleMargins:{top:0.82, bottom:0}});
}

/* 自检读数：K 线到底加载了多少根、图表容器多大。
   平时不显示，双击顶栏标题才弹出来（排查用，不打扰正常使用）。 */
var diag = {klines:0, err:'', w:0, h:0};
function updateDiag(){
  var el=document.getElementById('chart');
  diag.w = el ? el.clientWidth : -1;
  diag.h = el ? el.clientHeight : -1;
  var d=document.getElementById('diag');
  if(d && d.style.display!=='none'){
    d.textContent = '诊断  品种=' + cur
      + '  周期=' + iv
      + '  K线=' + diag.klines + ' 根'
      + '  容器=' + diag.w + '×' + diag.h
      + (diag.err ? '  错误=' + diag.err : '');
  }
}

function initPeriods(){
  var box = document.getElementById('periods');
  INTERVALS.forEach(function(v){
    var a = document.createElement('a');
    a.textContent = v;
    a.setAttribute('data-iv', v);
    a.onclick = function(){ setInterval_(v); return false; };
    box.appendChild(a);
  });
  paintPeriods();
}
function paintPeriods(){
  var as = document.querySelectorAll('#periods a');
  for(var i=0;i<as.length;i++){
    as[i].className = (as[i].getAttribute('data-iv') === iv) ? 'on' : '';
  }
}
function setInterval_(v){
  if(INTERVALS.indexOf(v) < 0 || v === iv) return;
  iv = v;
  localStorage.setItem('chartInterval', v);   // 记住选过的周期
  paintPeriods();
  loadKlines();
}

function loadKlines(){
  fetch('/api/klines?interval=' + encodeURIComponent(iv) + '&limit=500',
        {cache:'no-store'})
   .then(function(r){ return r.json(); })
   .then(function(rows){
      if(!rows || !rows.length || !rows.map){
        diag.err = 'K线为空';
        diag.klines = 0;
        updateDiag();
        showErr('K 线为空（' + iv + '）——可能是网络/代理抖动，30 秒后自动重试');
        return;
      }
      clearErr();
      var c=[], v=[], i, k, t;
      for(i=0;i<rows.length;i++){
        k=rows[i];
        t=Math.floor(k[0]/1000);
        c.push({time:t, open:+k[1], high:+k[2], low:+k[3], close:+k[4]});
        v.push({time:t, value:+k[5],
                color:(+k[4] >= +k[1]) ? themeColors().volUp : themeColors().volDown});
      }
      candleSeries.setData(c);
      volSeries.setData(v);
      // ★ 只在**品种/周期真的换了**的时候才 fitContent()。
      // 30 秒一次的后台刷新如果每次都 fitContent，用户刚缩放/平移到想看的位置、
      // 或者正在画趋势线，画面就会被硬拽回"全部 K 线"，线和视角一起乱跳。
      var dk = cur + '|' + iv;
      if(dk !== dataKey){ dataKey = dk; chart.timeScale().fitContent(); }
      // 换了品种/周期就换一份趋势线（每个品种+周期各记各的）
      loadTl();
      diag.klines = c.length;
      diag.err = '';
      updateDiag();
      var last=c[c.length-1], first=c[0];
      var el=document.getElementById('px');
      el.textContent = last.close;
      el.style.color = (last.close >= first.close) ? '#0ecb81' : '#f6465d';
   }).catch(function(err){
      diag.err = String(err && err.message ? err.message : err);
      updateDiag();
      showErr('K 线请求失败: ' + diag.err);
   });
}

/* ── 趋势线（照 TradingView 的手感重写过）─────────────────────
   点「✏ 画趋势线」进画线模式：
     * 第 1 下点起点（虚线跟着光标预览）
     * 第 2 下**成一条线**，并且**留在画线模式**，可以接着点两下画下一条
     * Esc 或者再点一次按钮退出画线模式
   画好之后（不在画线模式也能操作）：
     * 点一下线 = 选中它（出现白色端点手柄）
     * 拖端点调角度，拖线身整条平移
     * 按 Delete/Backspace 删掉选中（或光标下）的那一条；Ctrl+Z 撤销最后一条
     * 顶栏「↶ 撤销」「清空」，旁边显示当前有几条
   线是**按时间 + 价格存**的，不是屏幕坐标：平移、缩放、切周期都跟着 K 线走。
   每个品种 + 每个周期各存各的（localStorage）。
   ─────────────────────────────────────────────────────────── */
var tl = {
  lines: [],        // [{id, t1, p1, t2, p2}] —— 想画多少条都行
  mode: false,      // 画线模式
  pending: null,    // 画线时已落下的第一点
  preview: null,    // 按住拖拽画线时的 {a1, a2}
  cursor: null,     // 光标位置（橡皮筋预览）
  hover: -1,        // 光标下那条线的 id
  sel: -1,          // 选中的线 id
  drag: null,       // {id, part}  part: 0=起点 1=终点 2=线身
  dragGrab: null,
  _down: null,
  loadedKey: null,
  nextId: 1,
  lastSig: ''
};

var TL_COL_UP = '#f0b90b';       // 上升黄（和画线按钮同色）
var TL_COL_DOWN = '#5ac8fa';     // 下降青
var TL_HIT_PX = 7;               // 线身命中容差
var TL_HANDLE_R = 5;             // 端点手柄半径
var TL_HANDLE_HIT = 9;           // 端点命中半径

/* 进入画线模式时把图表的平移/缩放关掉，退出时还原。
   这是照 TradingView 的做法 —— 画线时图表必须"钉住"，
   否则你按下拖动，图表跟着一起移，线根本画不准。
   必须每次递一个**新对象**：lightweight-charts 的 options 是按对象引用合并的，
   反复用一个常量对象会污染后续调用。 */
var TL_HANDLE_ON  = {handleScroll:{mouseWheel:true, pressedMouseMove:true,
                                   horzTouchDrag:true, vertTouchDrag:true},
                     handleScale:{axisPressedMouseMove:{time:true, price:true},
                                  mouseWheel:true, pinch:true}};
var TL_HANDLE_OFF = {handleScroll:{mouseWheel:false, pressedMouseMove:false,
                                   horzTouchDrag:false, vertTouchDrag:false},
                     handleScale:{axisPressedMouseMove:{time:false, price:false},
                                  mouseWheel:false, pinch:false}};
function lockChart(on){
  if(!chart) return;
  try{ chart.applyOptions(on ? TL_HANDLE_OFF : TL_HANDLE_ON); }
  catch(e){ /* 库版本差异别把画线搞崩 */ }
}

function chartEl(){ return document.getElementById('chart'); }
function overlayEl(){ return document.getElementById('overlay'); }
function tlKey(){ return 'trendlines|' + cur + '|' + iv; }
function tlColor(l){ return (l.p2 >= l.p1) ? TL_COL_UP : TL_COL_DOWN; }

function lineById(id){
  for(var i=0;i<tl.lines.length;i++) if(tl.lines[i].id === id) return tl.lines[i];
  return null;
}

function saveTl(){
  try{
    var out = tl.lines.map(function(l){
      return {t1:l.t1, p1:l.p1, t2:l.t2, p2:l.p2};
    });
    if(out.length) localStorage.setItem(tlKey(), JSON.stringify(out));
    else localStorage.removeItem(tlKey());
  }catch(e){}
  paintTl();
}

/* 老版本只存一条线，格式是 [{time,price},{time,price}]。
   直接换格式会让用户已经画好的线凭空消失，所以这里做一次兼容转换。 */
function parseTl(raw){
  if(!raw) return [];
  var arr = null;
  try{ arr = JSON.parse(raw); }catch(e){ return []; }
  if(!arr || !arr.length) return [];
  if(arr.length === 2 && arr[0] && arr[0].time !== undefined && arr[0].t1 === undefined){
    return [{t1:arr[0].time, p1:arr[0].price, t2:arr[1].time, p2:arr[1].price}];
  }
  var out = [];
  for(var i=0;i<arr.length;i++){
    var o = arr[i];
    if(o && o.t1 !== undefined && o.t2 !== undefined &&
       o.p1 !== undefined && o.p2 !== undefined){
      out.push({t1:o.t1, p1:o.p1, t2:o.t2, p2:o.p2});
    }
  }
  return out;
}

function loadTl(){
  // ⚠️ 只在**品种或周期真的变了**的时候重新加载。
  // 这个函数会被 loadKlines() 调（每 30 秒自动刷新一次），
  // 每次都无条件清一遍状态的话，"点了第一下、还没点第二下"时
  // 赶上一次自动刷新，第一点就被清掉了 —— 表现为"点了两下画不出线"。
  var k = tlKey();
  if(tl.loadedKey === k) return;
  tl.loadedKey = k;
  tl.lines = []; tl.pending = null; tl.cursor = null; tl.preview = null;
  tl.hover = -1; tl.sel = -1; tl.drag = null; tl.dragGrab = null; tl._down = null;
  tl.nextId = 1;
  tl.mode = false;                   // 切品种/周期时退出画线模式，别糊里糊涂还锁着图表
  lockChart(false);
  var arr = [];
  try{ arr = parseTl(localStorage.getItem(k)); }catch(e){ arr = []; }
  for(var i=0;i<arr.length;i++){
    tl.lines.push({id: tl.nextId++, t1:arr[i].t1, p1:arr[i].p1,
                   t2:arr[i].t2, p2:arr[i].p2});
  }
  paintMode(); paintTl(); drawTrend();
}

function paintTl(){
  var n = tl.lines.length;
  var u = document.getElementById('undo'), c = document.getElementById('clr'),
      cl = document.getElementById('clone'), cnt = document.getElementById('tlcount');
  if(u) u.style.display = n ? 'inline-block' : 'none';
  if(c) c.style.display = n ? 'inline-block' : 'none';
  if(cl) cl.style.display = n ? 'inline-block' : 'none';
  if(cnt) cnt.textContent = n ? (n + ' 条') : '';
}

function paintMode(){
  var d = document.getElementById('draw');
  if(!d) return;
  d.className = tl.mode ? 'on' : '';
  d.textContent = tl.mode
    ? (tl.pending ? '点第二下成线 · Esc 退出' : '✏ 画线中：点第一个点')
    : '✏ 画趋势线';
  lockChart(tl.mode);               // 画线时锁住图表的平移/缩放
}

function setCursor(style){
  // 只改鼠标样式。**不要**在这里调 setCrosshairPosition ——
  // 往图表里塞一个假十字光标会干扰点击/命中判定（试过，会坏事）。
  var el = chartEl();
  if(el) el.style.cursor = style;
}

/** 锚点 → 像素。任何一步算不出来就返回 null（不要瞎画） */
function tlPixOf(l){
  if(!l || !chart || !candleSeries) return null;
  var ts = chart.timeScale();
  var x1 = ts.timeToCoordinate(l.t1), x2 = ts.timeToCoordinate(l.t2);
  var y1 = candleSeries.priceToCoordinate(l.p1), y2 = candleSeries.priceToCoordinate(l.p2);
  if(x1 === null || x2 === null || y1 === null || y2 === null) return null;
  return {x1:x1, y1:y1, x2:x2, y2:y2};
}

/** 点到线段的距离，用来判断"有没有抓到这条线" */
function distToSeg(px, py, x1, y1, x2, y2){
  var dx = x2-x1, dy = y2-y1;
  var L2 = dx*dx + dy*dy;
  if(L2 === 0) return Math.hypot(px-x1, py-y1);
  var t = Math.max(0, Math.min(1, ((px-x1)*dx + (py-y1)*dy) / L2));
  return Math.hypot(px - (x1 + t*dx), py - (y1 + t*dy));
}

/** 把线段裁到画布矩形内（Liang-Barsky）。
 *  为什么需要：锚点算出来的坐标可能在画布外面很远（价格轴一变就是几千像素），
 *  直接 moveTo/lineTo 画出去，整条线就"不见了"；裁一下，
 *  只要线穿过可视区就一定能看见可见的那一段。 */
function clipSeg(x1, y1, x2, y2, w, h){
  var t0 = 0, t1 = 1, dx = x2-x1, dy = y2-y1;
  var p = [-dx, dx, -dy, dy], q = [x1, w-x1, y1, h-y1];
  for(var i=0;i<4;i++){
    if(p[i] === 0){ if(q[i] < 0) return null; continue; }
    var r = q[i] / p[i];
    if(p[i] < 0){ if(r > t1) return null; if(r > t0) t0 = r; }
    else { if(r < t0) return null; if(r < t1) t1 = r; }
  }
  return {x1: x1 + t0*dx, y1: y1 + t0*dy, x2: x1 + t1*dx, y2: y1 + t1*dy};
}

function drawTrend(){
  var cv = overlayEl(), box = chartEl();
  if(!cv || !box) return;
  var w = box.clientWidth, h = box.clientHeight;
  if(cv.width !== w || cv.height !== h){ cv.width = w; cv.height = h; }
  var ctx = cv.getContext('2d');
  ctx.setTransform(1,0,0,1,0,0);
  ctx.clearRect(0,0,w,h);
  if(!w || !h) return;

  var i, l, g, seg, active;
  for(i=0;i<tl.lines.length;i++){
    l = tl.lines[i];
    g = tlPixOf(l);
    if(!g) continue;
    seg = clipSeg(g.x1, g.y1, g.x2, g.y2, w, h);
    if(!seg) continue;
    active = (tl.sel === l.id || tl.hover === l.id);
    var col = tlColor(l);
    ctx.save();
    ctx.strokeStyle = col;
    ctx.globalAlpha = active ? 1 : 0.9;
    ctx.lineWidth = active ? 2.6 : 1.7;
    ctx.beginPath();
    ctx.moveTo(seg.x1, seg.y1);
    ctx.lineTo(seg.x2, seg.y2);
    ctx.stroke();
    if(active){                    // 细描边：线压在亮色 K 线上也看得清
      ctx.globalAlpha = 0.22;
      ctx.lineWidth = 6;
      ctx.stroke();
    }
    ctx.restore();
    if(active){                    // 只给"正在操作的那条"画端点手柄
      var pts = [[g.x1,g.y1],[g.x2,g.y2]];
      for(var j=0;j<2;j++){
        var px = pts[j][0], py = pts[j][1];
        if(px < -20 || px > w+20 || py < -20 || py > h+20) continue;
        ctx.save();
        ctx.beginPath();
        ctx.arc(px, py, TL_HANDLE_R, 0, Math.PI*2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();
        ctx.strokeStyle = col;
        ctx.lineWidth = 1.6;
        ctx.stroke();
        ctx.restore();
      }
    }
  }

  // ---- 画线模式：预览 ----
  // 两种情况都画同一种虚线：
  //   1) 已经点下第一点（pending），终点跟着光标走
  //   2) 正在"按住拖"（preview），两端都是定好的锚点
  if(tl.mode){
    var fromA = tl.preview ? tl.preview.a1 : tl.pending;
    var toA = tl.preview ? tl.preview.a2 : null;
    if(fromA){
      var sx = chart.timeScale().timeToCoordinate(fromA.time);
      var sy = candleSeries ? candleSeries.priceToCoordinate(fromA.price) : null;
      var ex = null, ey = null;
      if(sx !== null && sy !== null){
        if(toA){
          ex = chart.timeScale().timeToCoordinate(toA.time);
          ey = candleSeries ? candleSeries.priceToCoordinate(toA.price) : null;
        } else if(tl.cursor){
          ex = tl.cursor.x; ey = tl.cursor.y;
        }
      }
      if(sx !== null && sy !== null && ex !== null && ey !== null){
        ctx.save();
        ctx.setLineDash(tl.preview ? [] : [5,4]);
        ctx.strokeStyle = TL_COL_UP;
        ctx.globalAlpha = 0.9;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.lineTo(ex, ey);
        ctx.stroke();
        ctx.restore();
        ctx.save();
        ctx.beginPath();
        ctx.arc(sx, sy, 4.5, 0, Math.PI*2);
        ctx.strokeStyle = TL_COL_UP;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.restore();
      }
    }
  }
}

/** 命中哪条线？后画的优先（画在上面的先抓到）。
 *  返回 {id, part}，part: 0=起点 1=终点 2=线身；没命中返回 null。 */
function tlHit(x, y){
  var box = chartEl();
  if(!box) return null;
  var w = box.clientWidth, h = box.clientHeight;
  var i, l, g;
  for(i=tl.lines.length-1;i>=0;i--){          // 端点比线身更容易抓
    l = tl.lines[i]; g = tlPixOf(l);
    if(!g) continue;
    if(Math.hypot(x-g.x1, y-g.y1) <= TL_HANDLE_HIT) return {id:l.id, part:0};
    if(Math.hypot(x-g.x2, y-g.y2) <= TL_HANDLE_HIT) return {id:l.id, part:1};
  }
  for(i=tl.lines.length-1;i>=0;i--){
    l = tl.lines[i]; g = tlPixOf(l);
    if(!g) continue;
    var seg = clipSeg(g.x1, g.y1, g.x2, g.y2, w, h);
    if(!seg) continue;
    if(distToSeg(x, y, seg.x1, seg.y1, seg.x2, seg.y2) <= TL_HIT_PX) return {id:l.id, part:2};
  }
  return null;
}

/** 像素坐标 → 锚点（时间 + 价格） */
function pixToAnchor(x, y){
  var ts = chart.timeScale();
  var time = ts.coordinateToTime(x);
  var price = candleSeries.coordinateToPrice(y);
  if(time === null || price === null || price === undefined) return null;
  return {time: time, price: price};
}

function addLine(a, b){
  if(!a || !b) return null;
  var l = {id: tl.nextId++, t1:a.time, p1:a.price, t2:b.time, p2:b.price};
  tl.lines.push(l);
  tl.sel = l.id;
  saveTl(); drawTrend();
  return l;
}

function delLine(id){
  var hit = false;
  for(var i=0;i<tl.lines.length;i++){
    if(tl.lines[i].id === id){ tl.lines.splice(i,1); hit = true; break; }
  }
  if(!hit) return;
  if(tl.sel === id) tl.sel = -1;
  if(tl.hover === id) tl.hover = -1;
  saveTl(); drawTrend();
}

function undoLine(){
  if(!tl.lines.length) return;
  delLine(tl.lines[tl.lines.length-1].id);
}

/** 选中的那条（没选中就用光标下的、再不行用最后一条） */
function activeLine(){
  return lineById(tl.sel) || (tl.hover >= 0 ? lineById(tl.hover) : null)
      || (tl.lines.length ? tl.lines[tl.lines.length - 1] : null);
}

/** 克隆一条：往右挪一点（时间上是原线跨度的 15%），价格不变，
 *  克隆出来的直接选中，接着拖到想要的位置就行 —— 用户要的"复制/克隆"。 */
function cloneLine(){
  var l = activeLine();
  if(!l) return;
  var span = Math.abs(timeDelta(l.t1, l.t2));
  var off = typeof l.t1 === 'number' ? (Math.round(span * 0.15) || 1800) : 0;
  var copy = {id: tl.nextId++, t1: addTime(l.t1, off), p1: l.p1,
              t2: addTime(l.t2, off), p2: l.p2};
  tl.lines.push(copy);
  tl.sel = copy.id;
  saveTl(); drawTrend();
}

function clearLines(){
  if(!tl.lines.length) return;
  tl.lines = []; tl.sel = -1; tl.hover = -1;
  saveTl(); drawTrend();
}

function initTrend(){
  // 一次性守卫：这个函数只能初始化一次。
  // 被调用两次的话 pointer 监听会成对注册 —— 第一份处理器把线画好，
  // 第二份紧接着又把状态重置回去，表现为"条件都满足、线就是出不来"。
  if(initTrend._done) return;
  initTrend._done = true;

  var cv = overlayEl(), box = chartEl();
  if(!cv || !box) return;

  var dbtn = document.getElementById('draw');
  var ubtn = document.getElementById('undo');
  var cbtn = document.getElementById('clr');
  if(dbtn) dbtn.onclick = function(){
    tl.mode = !tl.mode;
    tl.pending = null;
    tl.preview = null;
    if(tl.mode) tl.sel = -1;
    paintMode(); drawTrend();
  };
  if(ubtn) ubtn.onclick = function(){ cancelPending(); undoLine(); };
  if(cbtn) cbtn.onclick = function(){ cancelPending(); clearLines(); };
  var clbtn = document.getElementById('clone');
  if(clbtn) clbtn.onclick = function(){ cancelPending(); cloneLine(); };

  function cancelPending(){
    if(tl.pending || tl.preview){
      tl.pending = null; tl.preview = null;
      paintMode(); drawTrend();
    }
  }

  // 点击判定放在 pointerup 里自己做：
  // chart.subscribeClick 在画线模式下第二次点击不派发（实测），
  // 而 DOM 事件是正常送到的，所以不依赖它。
  box.addEventListener('pointerdown', function(e){
    tl._down = {x: e.offsetX, y: e.offsetY, moved: false};
    tl.cursor = {x: e.offsetX, y: e.offsetY};
    var hit = tlHit(e.offsetX, e.offsetY);
    if(hit){
      var a = pixToAnchor(e.offsetX, e.offsetY);
      if(a){
        var l = lineById(hit.id);
        tl._down.moved = true;              // 已经进入拖拽，抬起时不要再当点击
        tl._down.onLine = true;             // ★ 按住的是**已有的线**（不是空白处）
        tl.sel = hit.id;
        tl.drag = hit;
        tl.preview = null;
        if(hit.part === 2 && l){            // 拖线身：记住光标与两端的价格/时间差
          tl.dragGrab = {p1: l.p1 - a.price, p2: l.p2 - a.price,
                         t1: l.t1, t2: l.t2};
          // 只有拖线身才拦默认行为（否则图表会被一起平移）。
          // 注意：**不能无条件 preventDefault** —— 那会把 click 事件整个吃掉。
          e.preventDefault();
        }
        try{ box.setPointerCapture(e.pointerId); }catch(_){}
        drawTrend();
        return;
      }
    }
    tl.preview = null;
    // 画线模式下从空白处按下：先记住起点，拖出去就成线（TradingView 手感），
    // 没拖（原地抬起）就走下面"点两下"的那条路。
    if(tl.mode){
      tl._down.from = tl.pending || pixToAnchor(e.offsetX, e.offsetY);
    }
  });

  box.addEventListener('pointermove', function(e){
    tl.cursor = {x: e.offsetX, y: e.offsetY};

    // 1) 正在拖端点 / 拖线身
    if(tl.drag){
      var a = pixToAnchor(e.offsetX, e.offsetY);
      var l = lineById(tl.drag.id);
      if(a && l){
        if(tl.drag.part === 0){ l.t1 = a.time; l.p1 = a.price; }
        else if(tl.drag.part === 1){ l.t2 = a.time; l.p2 = a.price; }
        else if(tl.dragGrab){
          // 平移：两端按同一个"时间差"整体挪，价格按各自偏移平移
          var dt = timeDelta(tl.dragGrab.t1, a.time);
          l.t1 = addTime(tl.dragGrab.t1, dt); l.p1 = a.price + tl.dragGrab.p1;
          l.t2 = addTime(tl.dragGrab.t2, dt); l.p2 = a.price + tl.dragGrab.p2;
        }
      }
      drawTrend();
      return;
    }

    // 2) 画线模式下按住拖 = 一次成线（用户要的"点第一下、拖第二下"都行）
    if(tl.mode && tl._down && tl._down.from && !tl._down.moved){
      if(Math.abs(e.offsetX - tl._down.x) > 3 ||
         Math.abs(e.offsetY - tl._down.y) > 3){
        tl._down.moved = true;
      }
    }
    if(tl.mode && tl._down && tl._down.moved && tl._down.from){
      var a2 = pixToAnchor(e.offsetX, e.offsetY);
      if(a2) tl.preview = {a1: tl._down.from, a2: a2};
      drawTrend();
      return;
    }

    // 3) 平时：悬停高亮 + 光标形状；画线中还要重画橡皮筋
    var h = tlHit(e.offsetX, e.offsetY);
    var hid = h ? h.id : -1;
    var need = false;
    if(hid !== tl.hover){ tl.hover = hid; need = true; }
    if(tl.mode && tl.pending) need = true;
    if(need) drawTrend();
    setCursor(tl.mode ? 'crosshair' : (h ? (h.part === 2 ? 'move' : 'grab') : 'default'));
  });

  box.addEventListener('pointerup', function(e){
    var d = tl._down;
    tl._down = null;

    // 0) 按住拖出来的线：落定它（这就是"一次按下-拖动-抬起就成线"）
    if(tl.mode && d && d.moved && tl.preview){
      addLine(tl.preview.a1, tl.preview.a2);
      tl.preview = null;
      tl.pending = null;
      try{ box.releasePointerCapture(e.pointerId); }catch(_){}
      paintMode(); drawTrend();
      return;
    }
    tl.preview = null;

    // 1) 结束拖拽（拖端点 / 拖线身）——只有真的移动过才算拖拽。
    //    按下时只要碰上线就会设 tl.drag（那只是"候选"），
    //    没移动的话这次其实是**一次点击**，必须放过去走下面的分支。
    if(tl.drag){
      var real = d && (d.moved ||
        Math.abs(e.offsetX - d.x) > 4 || Math.abs(e.offsetY - d.y) > 4);
      tl.drag = null; tl.dragGrab = null;
      try{ box.releasePointerCapture(e.pointerId); }catch(_){}
      if(real){ saveTl(); drawTrend(); return; }
    }

    if(!d) return;
    // ★ 按在**已有的线**上松开（且没拖动）= 只是"选中它"，绝不能再起一条新线。
    //   画完一条之后还留在画线模式，点它想调整却变成"放新线起点" ——
    //   用户看到的就是"我改不了，只能画第二条"（反馈过的原话）。
    if(d.onLine){
      paintMode(); drawTrend();
      return;
    }
    var moved = Math.abs(e.offsetX - d.x) > 4 || Math.abs(e.offsetY - d.y) > 4;
    if(d.moved || moved) return;              // 拖动过 -> 不算点击

    // 2) 按"点两下"的语义：第一下放起点，第二下成线
    if(!tl.mode) return;                      // 非画线模式下点空白不做事（不打扰看图）
    var a = pixToAnchor(e.offsetX, e.offsetY);
    if(!a) return;
    if(!tl.pending){
      tl.pending = a;
      paintMode(); drawTrend();
      return;
    }
    addLine(tl.pending, a);
    tl.pending = null;
    // ★ 画完**不退出**画线模式：用户要"想画多少条就画多少条"。
    // 退出靠 Esc 或再点一次按钮。
    paintMode(); drawTrend();
  });

  box.addEventListener('pointercancel', function(){
    tl.drag = null; tl.dragGrab = null; tl._down = null; tl.preview = null;
    drawTrend();
  });

  document.addEventListener('keydown', function(e){
    var tgt = e.target || {};
    if(tgt.tagName === 'INPUT') return;        // 在搜索框里打字，别抢快捷键
    if(e.key === 'c' || e.key === 'C'){        // 克隆选中的那条
      cloneLine(); e.preventDefault(); return;
    }
    if(e.key === 'Escape'){
      if(tl.pending || tl.preview){
        tl.pending = null; tl.preview = null;
        paintMode(); drawTrend(); return;
      }
      if(tl.mode){ tl.mode = false; paintMode(); drawTrend(); return; }
      if(tl.sel >= 0){ tl.sel = -1; drawTrend(); }
      return;
    }
    if(e.key === 'Delete' || e.key === 'Backspace'){
      if(tl.sel >= 0){ delLine(tl.sel); e.preventDefault(); }
      else if(tl.hover >= 0){ delLine(tl.hover); e.preventDefault(); }
      return;
    }
    if((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')){
      undoLine(); e.preventDefault();
    }
  });

  // 缩放/平移图表时基座变了，立刻重画（看门狗之外的第一道保障）
  if(chart.timeScale().subscribeVisibleLogicalRangeChange){
    chart.timeScale().subscribeVisibleLogicalRangeChange(function(){ drawTrend(); });
  }
  window.addEventListener('resize', function(){ tl.lastSig = ''; drawTrend(); });

  // ★ 看门狗：叠加层是自己画的 canvas，**不会**自动跟着图表走。
  // 只在"时间区间变化"时重画是不够的 —— 价格轴自适应、拖价格轴、
  // 容器尺寸变化都不会触发那个回调，线就会**停在屏幕上不动**，
  // 看起来就是"线没粘在 K 线上、跟着屏幕跑"。这里每 120ms 比一次签名，
  // 只有真的变了才重画（不动就不画，几乎不费 CPU）。
  tl.watch = function(){
    try{
      if(!chart || !candleSeries) return;
      var r = chart.timeScale().getVisibleLogicalRange();
      var y = candleSeries.priceToCoordinate(1);
      var bx = chartEl();
      var sig = (r ? (r.from.toFixed(3) + ',' + r.to.toFixed(3)) : '-')
              + '|' + (y === null ? 'x' : y.toFixed(2))
              + '|' + bx.clientWidth + 'x' + bx.clientHeight
              + '|' + tl.lines.length + '|' + tl.sel + '|' + tl.hover;
      if(sig !== tl.lastSig){ tl.lastSig = sig; drawTrend(); }
    }catch(err){}
  };
  setInterval(tl.watch, 120);

  paintMode(); paintTl();
  loadTl();
}

/* 时间加减：lightweight-charts 的时间可能是秒级时间戳，也可能是业务日对象。
   这里只处理我们实际会用到的两种情况（币安 K 线是秒级数字）。 */
function timeDelta(t1, t2){
  if(typeof t1 === 'number' && typeof t2 === 'number') return t2 - t1;
  return 0;
}
function addTime(t, d){
  if(typeof t === 'number') return t + d;
  return t;
}

/* ── 左侧扫盘栏 ──────────────────────────────────────────────
   单击 / 双击都只是**切图表**，留在本页一路往下点就能复盘完所有品种。
   双击**不再加自选**（用户明确要求：直接打开行情就行，别动我的列表）。
   要加自选请用行情条底部输入框。
   ────────────────────────────────────────────────────────── */
function toneClass(t){ return t==='up'?'up':(t==='down'?'down':'vol'); }

function esc(s){
  return String(s==null?'':s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

function renderSide(j){
  var box=document.getElementById('groups');
  if(!box || !j || !j.groups) return;
  var keep=box.scrollTop;      // 别把用户正在看的位置冲掉
  var html='', g, i, grp, items, it, isCur, pct;
  for(g=0; g<j.groups.length; g++){
    grp=j.groups[g]; items=grp.items||[];
    if(!items.length) continue;
    html += '<div class="grp"><h4>'+esc(grp.label)+'</h4>';
    for(i=0;i<items.length;i++){
      it=items[i];
      isCur = (it.base === cur);
      pct = (it.change>=0?'+':'') + Number(it.change).toFixed(2) + '%';
      html += '<div class="it'+(isCur?' cur':'')+'" data-b="'+esc(it.base)+'">'
            +   '<span class="rk">'+(i+1)+'</span>'
            +   '<span class="nm">'+(it.inWatch?'<b>✓</b> ':'')+esc(it.base)+'</span>'
            +   '<span class="pct '+toneClass(grp.tone)+'">'+pct+'</span>'
            + '</div>';
    }
    html += '</div>';
  }
  box.innerHTML = html;
  box.scrollTop = keep;
}

function pick(base){
  // 只切图表。双击会连发两次 click，第二次是同一个品种 —— 直接跳过，
  // 省一次没必要的请求和重绘。
  if(base === cur) return;
  fetch('/api/pick?base='+encodeURIComponent(base), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(j && j.ok){
        cur = base;
        // ★ 立刻换图：以前只能等下一秒的 /api/symbol 轮询，扫盘时那 1 秒很碍事
        var s = document.getElementById('sym');
        if(s) s.textContent = base;
        loadKlines();
      }
      loadSide();          // 高亮跟着走
    }).catch(function(){});
}

function loadSide(){
  if(SCAN){ loadScan(false); return; }      // 扫盘页的"侧栏"就是全品种列表
  fetch('/api/rankings', {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(j){ renderSide(j); })
    .catch(function(){});
}

/* ── 全品种扫盘（SCAN 模式）──────────────────────────────────
   左边列出**全市场所有品种**：加密 + 币安 TradFi（黄金/白银/原油/股票/指数），
   按成交额倒序。↑↓ 一路切过去看图 = 扫盘。
   和「行情图表」共用同一份代码（K 线/周期/趋势线都在），只有左侧栏不一样。
   ─────────────────────────────────────────────────────────── */
var scan = { rows: [], view: [], sel: '', cat: 'all', q: '', ts: 0, favs: [] };
var SCAN_CATS = [['all', '全部'], ['fav', '♥ 收藏'], ['crypto', '加密'],
                 ['股票', '股票'], ['黄金', '贵金属'], ['商品', '原油/商品'],
                 ['tradfi', '其他 TradFi']];

function scanIsFav(base){
  for(var i=0;i<scan.favs.length;i++) if(scan.favs[i] === base) return true;
  return false;
}
/** 点 ♥：收藏 / 取消（立刻写进行情条的 config.json） */
function scanToggleFav(base){
  fetch('/api/fav?base='+encodeURIComponent(base), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(j && j.ok){
        scan.favs = j.favs || [];
        scanFilter(); paintScan(); scanScrollTo();
      }
    }).catch(function(){});
}

/** 把收藏清单复制到剪贴板（TradingView 符号格式） */
function scanCopyFavs(){
  var el = document.getElementById('favcopy');
  fetch('/api/copyfavs', {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(el) el.textContent = (j && j.ok) ? ('✓ 已复制 ' + j.count + ' 个') : '还没有收藏';
      setTimeout(function(){ if(el) el.textContent = '⧉ 复制收藏'; }, 2600);
    }).catch(function(){});
}

/** 用他自己的浏览器打开 TradingView（带登录/cookie/画线） */
function scanOpenTV(){
  fetch('/api/tvopen?base='+encodeURIComponent(scan.sel || ''), {cache:'no-store'})
    .catch(function(){});
}

/** 双击侧边栏 = 把图表"复位"到一个舒服的视角：
 *  最近 45% 的 K 线铺满屏幕、右边留一点点空，扫盘时一眼看完一段行情。
 *  （用户要求：双击就回到"一览无余、适合看"的位置） */
function scanCenter(){
  try{
    var ts = chart.timeScale();
    var n = diag.klines || 500;
    var span = Math.max(60, Math.round(n * 0.45));
    ts.setVisibleLogicalRange({from: n - span, to: n + 2});
  }catch(e){}
}

function scanFilter(){
  var q = (scan.q || '').trim().toUpperCase();
  scan.view = scan.rows.filter(function(r){
    if(scan.cat === 'fav' && !scanIsFav(r.base)) return false;
    if(scan.cat === 'crypto' && r.kind !== 'crypto') return false;
    if(scan.cat === 'tradfi' && r.kind !== 'tradfi') return false;
    if(scan.cat === '股票' && r.cat !== '股票') return false;
    if(scan.cat === '黄金' && r.cat !== '黄金' && r.cat !== '白银') return false;
    if(scan.cat === '商品' && r.cat !== '商品') return false;
    if(q && r.base.toUpperCase().indexOf(q) < 0) return false;
    return true;
  });
}
function scanIdx(base){
  for(var i=0;i<scan.view.length;i++) if(scan.view[i].base === base) return i;
  return -1;
}
function scanFmt(v){
  v = Number(v) || 0;
  if(v >= 1000) return v.toFixed(2);
  if(v >= 1) return v.toFixed(3);
  if(v >= 0.01) return v.toFixed(5);
  return v.toFixed(7);
}
function scanBig(v){
  v = Number(v) || 0;
  if(v >= 1e8) return (v/1e8).toFixed(1) + '亿';
  if(v >= 1e4) return (v/1e4).toFixed(0) + '万';
  if(v <= 0) return '--';
  return v.toFixed(0);
}
function paintScan(){
  var box = document.getElementById('groups');
  if(!box) return;
  var keep = box.scrollTop, html = '', i, r, isCur, pct;
  for(i=0;i<scan.view.length;i++){
    r = scan.view[i];
    isCur = (r.base === scan.sel);
    pct = (r.change>=0?'+':'') + Number(r.change).toFixed(2) + '%';
    var isFav = scanIsFav(r.base);
    html += '<div class="it'+(isCur?' cur':'')+'" data-b="'+esc(r.base)+'">'
          +   '<span class="fav'+(isFav?' on':'')+'" data-fav="'+esc(r.base)+'"'
          +     ' title="收藏（同步到 TradingView 用）">'+(isFav?'♥':'♡')+'</span>'
          +   '<span class="rk">'+(i+1)+'</span>'
          +   '<span class="nm">'+esc(r.base)+'</span>'
          +   (r.kind === 'tradfi' ? '<span class="tag">'+esc(r.cat)+'</span>' : '')
          +   '<span class="px">'+scanFmt(r.price)+'</span>'
          +   '<span class="vol">'+scanBig(r.volume)+'</span>'
          +   '<span class="vol oi">'+(r.oi ? scanBig(r.oi) : '--')+'</span>'
          +   '<span class="pct '+(r.change>=0?'up':'down')+'">'+pct+'</span>'
          + '</div>';
  }
  box.innerHTML = html;
  box.scrollTop = keep;
  var t = document.getElementById('sidetitle');
  if(t) t.textContent = '全品种 ' + scan.view.length + ' / ' + scan.rows.length;
  // 收藏数量直接写在筛选胶囊上，一眼知道收藏了几个
  var favChip = document.querySelector('#scancats .chip[data-cat="fav"]');
  if(favChip) favChip.textContent = '♥ 收藏 ' + scan.favs.length;
}
function scanScrollTo(){
  var box = document.getElementById('groups');
  if(!box) return;
  var el = box.querySelector('.it.cur');
  if(el && el.scrollIntoView) el.scrollIntoView({block:'nearest'});
}
/** 选中某个品种：load=false 时只动列表，不换图（换图由调用方负责） */
function scanSelect(base, load){
  if(!base) return;
  scan.sel = base;
  try{ localStorage.setItem('scanSel', base); }catch(e){}
  paintScan(); scanScrollTo();
  if(load !== false) scanPick(base);
}
function scanMove(delta){
  if(!scan.view.length) return;
  var i = scanIdx(scan.sel);
  i = (i < 0) ? 0 : Math.max(0, Math.min(scan.view.length - 1, i + delta));
  scanSelect(scan.view[i].base);
}
/** 扫盘时换图要**立刻**，不等那 1 秒的 /api/symbol 轮询 */
function scanPick(base){
  if(base === cur) return;
  fetch('/api/pick?base='+encodeURIComponent(base), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(j && j.ok){
        cur = base;
        var s = document.getElementById('sym');
        if(s) s.textContent = base;
        loadKlines();
      }
    }).catch(function(){});
}
function loadScan(force){
  fetch('/api/all' + (force ? '?force=1' : ''), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(!j || !j.rows) return;
      scan.rows = j.rows;
      scan.ts = j.ts || 0;
      scan.favs = j.favs || scan.favs || [];
      scanFilter();
      if(!scan.sel || scanIdx(scan.sel) < 0){
        var saved = null;
        try{ saved = localStorage.getItem('scanSel'); }catch(e){}
        scan.sel = (saved && scanIdx(saved) >= 0) ? saved
                 : (scan.view[0] ? scan.view[0].base : '');
      }
      paintScan(); scanScrollTo();
    }).catch(function(){});
}
function initScan(){
  if(initScan._done) return;
  initScan._done = true;
  document.body.className = 'scan';
  document.title = '行情图表 · 全品种扫盘';   // 仍以"行情图表"开头，窗口复用才找得到
  var tools = document.getElementById('scantools');
  if(tools) tools.style.display = 'block';
  var back = document.getElementById('backchart');
  if(back) back.style.display = 'inline';
  var catBox = document.getElementById('scancats');
  SCAN_CATS.forEach(function(c){
    var el = document.createElement('span');
    el.className = 'chip' + (c[0] === 'all' ? ' on' : '');
    el.textContent = c[1];
    el.setAttribute('data-cat', c[0]);
    el.onclick = function(){
      scan.cat = c[0];
      var all = document.querySelectorAll('#scancats .chip');
      for(var i=0;i<all.length;i++){
        all[i].className = 'chip' + (all[i].getAttribute('data-cat') === c[0] ? ' on' : '');
      }
      scanFilter();
      if(scanIdx(scan.sel) < 0) scan.sel = scan.view[0] ? scan.view[0].base : '';
      paintScan(); scanScrollTo();
      if(scan.sel) scanPick(scan.sel);
    };
    catBox.appendChild(el);
  });
  var q = document.getElementById('scanq');
  if(q){
    q.addEventListener('input', function(){
      scan.q = q.value || '';
      scanFilter();
      if(scanIdx(scan.sel) < 0 && scan.view.length) scan.sel = scan.view[0].base;
      paintScan(); scanScrollTo();
    });
  }
  if(back) back.onclick = function(){
    fetch('/api/mode?scan=0', {cache:'no-store'}).then(function(){ location.href = '/'; })
      .catch(function(){ location.href = '/'; });
  };
  document.addEventListener('keydown', function(e){
    var t = e.target || {};
    var inInput = (t.tagName === 'INPUT');
    if(inInput && t.id !== 'scanq') return;
    if(e.ctrlKey || e.metaKey || e.altKey) return;
    var nav = {'ArrowDown':1, 'j':1, 'ArrowUp':-1, 'k':-1,
               'PageDown':10, 'PageUp':-10};
    if(nav[e.key] !== undefined){
      e.preventDefault();
      scanMove(nav[e.key]);
      return;
    }
    if(inInput) return;                       // 在搜索框里打字，别抢
    if(e.key === 'Home' && scan.view.length){ e.preventDefault(); scanSelect(scan.view[0].base); }
    else if(e.key === 'End' && scan.view.length){
      e.preventDefault(); scanSelect(scan.view[scan.view.length-1].base);
    }
    else if(e.key === '/' && q){ e.preventDefault(); q.focus(); }
  });
  var rf = document.getElementById('rf');
  if(rf) rf.onclick = function(){ loadScan(true); };
  var fc = document.getElementById('favcopy');
  if(fc) fc.onclick = scanCopyFavs;
  var ftv = document.getElementById('favtv');
  if(ftv) ftv.onclick = scanOpenTV;
  loadScan();
}

function initSide(){
  if(initSide._done) return;                 // 同上：防重复注册
  initSide._done = true;
  var box=document.getElementById('groups');
  // 单击、双击都只切图表 —— 双击不加自选
  box.addEventListener('click', function(e){
    // ♥ 收藏：点它只切换收藏，别顺带把图表也切了
    var fav = e.target.closest ? e.target.closest('.fav') : null;
    if(fav){
      e.preventDefault();
      if(e.stopPropagation) e.stopPropagation();
      scanToggleFav(fav.getAttribute('data-fav'));
      return;
    }
    var row = e.target.closest ? e.target.closest('.it') : null;
    if(!row) return;
    var b=row.getAttribute('data-b');
    if(!b) return;
    if(SCAN) scanSelect(b); else pick(b);      // 扫盘页点一下 = 选中 + 换图
  });
  // 双击时浏览器会连发两次 click，第二次是同一个品种（pick 里已跳过），
  // 再把双击的默认行为吃掉，避免任何多余动作。
  // ★ 扫盘页里双击 = 图表**复位到舒服的视角**（用户要的"一览无余"）。
  box.addEventListener('dblclick', function(e){
    if(SCAN){ scanCenter(); }
    e.preventDefault();
  });
  var rf=document.getElementById('rf');
  if(rf) rf.onclick=function(){ loadSide(); };
}

function tick(){
  fetch('/api/symbol', {cache:'no-store'}).then(function(r){return r.json();}).then(function(j){
    // 页面模式由行情条那边决定：行情图表 ↔ 全品种扫盘。
    // 用"页面自己跳"而不是"再开一个标签页"，才不会越点越多标签。
    // 刚加载的 2 秒内不理会：那会儿"反向确认模式"的请求可能还没到服务端，
    // 直接照做会把刚打开的 /scan 又弹回 '/'。
    // ⚠️ 刚加载的 2 秒内不理会模式切换（否则直接打开 /scan 会被弹回 /）
    if(Date.now() - pageLoadedAt > 2000 && !!j.scan !== !!SCAN){
      location.href = j.scan ? '/scan' : '/';
      return;
    }
    // 主题变了就原地换（不用刷新页面）
    if(j.theme && j.theme !== THEME){ THEME = j.theme; applyTheme(); }
    // ⚠️ 这里用 split('|')[0] 比较：pick()/scanPick() 会把 cur 设成**裸 base**，
    // 而 /api/symbol 给的是 "BASE|QUOTE"。不这样比的话，每次换图都会
    // 被这一秒的轮询**再拉一次** K 线（扫盘时就是双倍流量）。
    if(!j.key || j.key === cur || j.key.split('|')[0] === cur) return;
    cur = j.key;
    document.getElementById('sym').textContent = j.name || j.key;
    loadKlines();      // 只换数据，图表实例不重建 —— 这就是快的原因
    loadSide();        // 侧栏高亮跟着走
    // TradingView 链接按需解析（中文币要查拼音，慢，别拖慢主流程）
    fetch('/api/tvurl', {cache:'no-store'}).then(function(r){return r.json();})
      .then(function(t){ document.getElementById('tvlink').href = t.url || '#'; })
      .catch(function(){});
  }).catch(function(){});
}

initChart();
applyTheme();                 // 按行情条下发的主题上色（夜间/白天）
initPeriods();
initSide();
initTrend();
if(SCAN) initScan();          // 全品种扫盘页：把左侧栏换成全市场列表 + 键盘导航
// 页面加载时**反向确认**自己现在是什么模式。
// 不确认的话：直接打开 /scan（书签、或手动敲 URL）会被服务端那个
// "该显示扫盘吗" 的标志判成"你在图表页"，一秒后又把你弹回 '/'。
try{ fetch('/api/mode?scan=' + (SCAN ? 1 : 0), {cache:'no-store'}); }catch(e){}
// 先把当前品种定下来，这样侧栏高亮一开始就是对的。
// ⚠️ 坑：这里设了 cur 之后，tick() 会因为"品种没变"而跳过加载，
// K 线就永远画不出来（页面一片黑、也不报错）。所以这里必须**顺手把 K 线画上**。
fetch('/api/symbol', {cache:'no-store'}).then(function(r){return r.json();})
  .then(function(j){
    if(!j || !j.key) return;
    cur = j.key;
    document.getElementById('sym').textContent = j.name || j.key;
    loadKlines();          // ← 不能省。省了就是"打开一片黑"
    fetch('/api/tvurl', {cache:'no-store'}).then(function(r){return r.json();})
      .then(function(t){ document.getElementById('tvlink').href = t.url || '#'; })
      .catch(function(){});
  })
  .catch(function(){})
  .then(function(){ loadSide(); });

tick();
setInterval(tick, 1000);
setInterval(loadKlines, 30000);     // 顺带自动刷新 K 线
setInterval(loadSide, 60000);       // 榜单变化慢，60 秒刷一次就够
setInterval(updateDiag, 1000);
updateDiag();
</script></body></html>
"""


class _ChartHandler(BaseHTTPRequestHandler):
    """只服务本机 127.0.0.1 上的页面、本地库和一个 JSON 接口。"""

    app = None                              # 由 TickerApp 注入

    def log_message(self, *_args):
        pass                                # 别刷屏

    def _send(self, ctype, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        try:
            self._do_GET()
        except Exception:
            # 同样的原因：--noconsole 的 exe 没有 stderr，异常必须自己落盘
            log("图表请求失败:\n" + traceback.format_exc())
            try:
                self._send("text/plain; charset=utf-8",
                           ("服务端出错: " + traceback.format_exc()).encode("utf-8"), 500)
            except Exception:
                pass

    def _do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        def page(scan: bool) -> bytes:
            # 两张页面共用同一份代码（K 线/周期/趋势线/扫盘栏全都在里面），
            # 只有一处开关不同 —— 少维护一份，也不会两边功能慢慢跑偏。
            return CHART_PAGE.replace("__SCAN_MODE__",
                                      "true" if scan else "false").replace(
                "__THEME__", getattr(self.app, "theme", "night")).encode("utf-8")

        if path in ("/", "/index.html"):
            self._send("text/html; charset=utf-8", page(False))
        elif path in ("/scan", "/scan.html"):
            self._send("text/html; charset=utf-8", page(True))
        elif path == "/api/all":
            # 全品种名单（加密 + 币安 TradFi：黄金/白银/原油/股票/指数）
            force = (query.get("force") or ["0"])[0] == "1"
            try:
                rows = load_all_symbols(force=force)
            except Exception as exc:
                log(f"全品种名单不可用: {exc}")
                rows = []
            app = self.app
            favs = app.scan_favs() if app else []
            self._send("application/json; charset=utf-8",
                       json.dumps({"rows": rows, "ts": time.time(), "favs": favs},
                                  ensure_ascii=False).encode("utf-8"))
        elif path == "/api/fav":
            # 扫盘页点 ♥：收藏 / 取消收藏（立刻落盘）
            app = self.app
            base = (query.get("base") or [""])[0]
            raw = (query.get("on") or [""])[0]
            on = None if raw == "" else raw == "1"
            state = False
            if app is not None and base:
                state = app.set_scan_fav(base, on)
            self._send("application/json; charset=utf-8",
                       json.dumps({"ok": bool(app and base), "base": base.upper(),
                                   "on": bool(state),
                                   "favs": app.scan_favs() if app else []},
                                  ensure_ascii=False).encode("utf-8"))
        elif path == "/api/favs":
            app = self.app
            favs = app.scan_favs() if app else []
            self._send("application/json; charset=utf-8",
                       json.dumps({"favs": favs}, ensure_ascii=False).encode("utf-8"))
        elif path == "/api/copyfavs":
            app = self.app
            n = app.copy_favs_to_clipboard() if app else 0
            self._send("application/json; charset=utf-8",
                       json.dumps({"ok": n > 0, "count": n}).encode("utf-8"))
        elif path == "/api/tvopen":
            app = self.app
            base = (query.get("base") or [""])[0] or None
            if app is not None:
                app.open_my_tradingview(base)
            self._send("application/json; charset=utf-8",
                       json.dumps({"ok": bool(app)}).encode("utf-8"))
        elif path == "/lib/lightweight-charts.js":
            # 本地库：CDN 只有 160KB，但走本地能做到"打开即出图"，
            # 也不受代理抖动影响
            try:
                with open(CHART_LIB, "rb") as fh:
                    self._send("application/javascript; charset=utf-8", fh.read())
            except Exception as exc:
                self._send("text/plain; charset=utf-8",
                           f"缺少图表库 {CHART_LIB}: {exc}".encode("utf-8"), 404)
        elif path == "/api/symbol":
            app = self.app
            info = app.chart_symbol() if app else {"key": "", "name": ""}
            if app:
                app.note_chart_poll()
            self._send("application/json; charset=utf-8",
                       json.dumps(info, ensure_ascii=False).encode("utf-8"))
        elif path == "/api/klines":
            self._send("application/json; charset=utf-8",
                       self._klines().encode("utf-8"))
        elif path == "/api/tvurl":
            app = self.app
            url = app.tradingview_link() if app else ""
            self._send("application/json; charset=utf-8",
                       json.dumps({"url": url}, ensure_ascii=False).encode("utf-8"))
        elif path == "/api/rankings":
            app = self.app
            data = app.chart_rankings() if app else {"groups": []}
            self._send("application/json; charset=utf-8",
                       json.dumps(data, ensure_ascii=False).encode("utf-8"))
        elif path == "/api/mode":
            # 页面自己请求切换"行情图表 ↔ 全品种扫盘"（扫盘页上那个「← 行情图表」链接用）
            app = self.app
            want = (query.get("scan") or ["0"])[0] == "1"
            if app is not None:
                app._want_scan = want
            self._send("application/json; charset=utf-8",
                       json.dumps({"ok": True, "scan": want}).encode("utf-8"))
        elif path == "/api/pick":
            # 侧边栏点一个品种：**只切图表**。
            # 这里刻意不再支持"加自选"（曾经有 mode=add，双击用它）——
            # 用户明确要求：双击直接打开行情就行，别动我的观察列表。
            # 把这条能力从接口上删掉，比只改前端更稳：
            # 以后谁再挂个双击也加不进去。
            app = self.app
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            base = (query.get("base") or [""])[0].strip()
            mode = (query.get("mode") or ["chart"])[0].strip()
            ok = False
            if app is not None and base and mode != "add":
                app.set_chart_symbol(base, app.cfg.get("quote", "USDT"))
                ok = True
            self._send("application/json; charset=utf-8",
                       json.dumps({"ok": ok, "base": base,
                                   "mode": "chart" if ok else mode},
                                  ensure_ascii=False).encode("utf-8"))
        elif path == "/favicon.ico":
            self._send("image/x-icon", b"")
        else:
            self.send_error(404)

    def _klines(self):
        """把币安 K 线转发给页面。

        页面直接请求币安也行（币安带 CORS 头），但走本地能复用重试逻辑，
        中文字符也不用在浏览器里再编码一次。
        """
        app = self.app
        if app is None:
            return "[]"
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        interval = (query.get("interval") or ["1h"])[0]
        if interval not in CHART_INTERVALS:      # 别把任意字符串透传给币安
            interval = "1h"
        try:
            limit = max(20, min(1500, int((query.get("limit") or ["500"])[0])))
        except ValueError:
            limit = 500
        base, quote = app._chart_target
        symbol = urllib.parse.quote(f"{base}{quote}")
        url = ("https://fapi.binance.com/fapi/v1/klines"
               f"?symbol={symbol}&interval={urllib.parse.quote(interval)}&limit={limit}")
        try:
            data = _http_json(url, 15.0)
            return json.dumps(data if isinstance(data, list) else [],
                              ensure_ascii=False)
        except Exception as exc:
            log(f"K 线抓取失败 ({base} {interval}): {exc}")
            return "[]"


CHART_TITLE = "行情图表"
def _chart_lib_path() -> str:
    """图表库的位置：打包后优先找解压目录(_MEIPASS)，再找 exe 旁边。"""
    for base in (RES_DIR, APP_DIR):
        p = os.path.join(base, "lightweight-charts.js")
        if os.path.exists(p):
            return p
    return os.path.join(RES_DIR, "lightweight-charts.js")


CHART_LIB = _chart_lib_path()
# 币安 K 线支持的周期，页面传别的值一律拒掉。
# 注意大小写：1m = 一分钟，1M = 一个月。
CHART_INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h",
                   "6h", "8h", "12h", "1d", "3d", "1w", "1M")


# ══════════════════════════════════════════════════════════════════
# 价位提醒：引擎 + 通知 + 邮件
#
# 提醒存在内存里（不落盘）—— 这是"今天盯一下"的临时工具，
# 重启就清空反而符合直觉；要长期保留的价格线应该记在脑子里或别处。
# ══════════════════════════════════════════════════════════════════

ALERT_POLL = 3.0                  # 提醒检查间隔（秒），跟价格刷新节奏一致


class AlertEngine:
    """价格提醒。

    每个提醒 = 「品种 + 方向(上破/下破) + 目标价 + 是否重复 + 通知渠道」。
    命中一次后：
      * repeat=False → 自动停用（一次性）
      * repeat=True  → 处于"已触发"状态，价格**回到目标价的另一侧**才重新武装，
                       避免价格在目标价上下来回抖时被反复轰炸
    """

    def __init__(self, app):
        self.app = app
        self.alerts = []          # [{id, base, quote, dir, price, repeat, toast, mail,
                                  #   enabled, triggered, created, last_fired, fire_count}]
        self._lock = threading.Lock()
        self._seq = 0
        self._stop = threading.Event()

    # ---------------------------------------------------------- CRUD --
    def add(self, base, quote, price, direction="above", repeat=False,
            toast=True, mail=False):
        with self._lock:
            self._seq += 1
            item = {
                "id": f"al_{int(time.time()*1000)}_{self._seq}",
                "base": str(base), "quote": str(quote or "USDT"),
                "dir": "below" if str(direction).lower() in ("below", "down", "下破") else "above",
                "price": float(price),
                "repeat": bool(repeat),
                "toast": bool(toast), "mail": bool(mail),
                "enabled": True, "triggered": False,
                "created": time.time(), "last_fired": 0.0, "fire_count": 0,
            }
            self.alerts.append(item)
            return item

    def update(self, alert_id, **fields):
        with self._lock:
            for a in self.alerts:
                if a["id"] == alert_id:
                    for k in ("price", "repeat", "toast", "mail", "enabled", "dir"):
                        if k in fields and fields[k] is not None:
                            a[k] = fields[k]
                    if "price" in fields or "dir" in fields:
                        a["triggered"] = False      # 改了条件就重新武装
                    return a
        return None

    def remove(self, alert_id):
        with self._lock:
            before = len(self.alerts)
            self.alerts = [a for a in self.alerts if a["id"] != alert_id]
            return len(self.alerts) != before

    def clear_symbol(self, base, quote=None):
        with self._lock:
            before = len(self.alerts)
            self.alerts = [a for a in self.alerts
                           if not (a["base"].upper() == str(base).upper()
                                   and (quote is None or a["quote"].upper() == str(quote).upper()))]
            return before - len(self.alerts)

    def for_symbol(self, base, quote=None):
        with self._lock:
            return [dict(a) for a in self.alerts
                    if a["base"].upper() == str(base).upper()
                    and (quote is None or a["quote"].upper() == str(quote).upper())]

    def all(self):
        with self._lock:
            return [dict(a) for a in self.alerts]

    def symbol_set(self):
        """有提醒的品种集合，key = BASE|QUOTE。"""
        with self._lock:
            return {f"{a['base'].upper()}|{a['quote'].upper()}" for a in self.alerts}

    # -------------------------------------------------------- 检查 --
    def check(self, rows):
        """拿最新行情检查一遍。rows: {(base,quote): {"price":..,..}}"""
        fired = []
        with self._lock:
            for a in self.alerts:
                if not a["enabled"]:
                    continue
                row = rows.get((a["base"], a["quote"]))
                if not row:
                    continue
                px = float(row.get("price") or 0)
                if px <= 0:
                    continue
                above = a["dir"] == "above"
                hit_line = px >= a["price"] if above else px <= a["price"]

                if a["triggered"]:
                    # 重复提醒：价格回到另一侧才重新武装，防止来回抖着刷屏
                    if (above and px < a["price"]) or (not above and px > a["price"]):
                        a["triggered"] = False
                    continue
                if not hit_line:
                    continue

                a["triggered"] = True
                a["last_fired"] = time.time()
                a["fire_count"] += 1
                if not a["repeat"]:
                    a["enabled"] = False            # 一次性提醒，触发后自动停用
                fired.append(dict(a))
        for a in fired:
            self._deliver(a)
        if fired:
            # 让主线程刷新铃铛/弹窗状态（这里可能是引擎线程）
            try:
                self.app._queue.put(("alerts", None))
            except Exception:
                pass
        return fired

    def _deliver(self, a):
        base, quote, price = a["base"], a["quote"], a["price"]
        direction = "上破" if a["dir"] == "above" else "下破"
        title = f"{base} {direction} {fmt_price(price)}"
        body = (f"{base}/{quote} 已达到 {fmt_price(price)}"
                f"（{direction}），当前价 {self._current_price_text(a)}。"
                f"{' 重复提醒' if a['repeat'] else ' 一次性提醒，已自动停用。'}")
        log(f"🔔 提醒触发：{title}")

        if a["toast"]:
            threading.Thread(target=_windows_toast, args=(title, body),
                             daemon=True).start()
        if a["mail"]:
            threading.Thread(target=self._send_mail, args=(a, title, body),
                             daemon=True).start()

    def _current_price_text(self, a):
        try:
            row = self.app.rows.get((a["base"], a["quote"])) or {}
            return fmt_price(row.get("price")) if row.get("price") else "—"
        except Exception:
            return "—"

    def _send_mail(self, a, title, body):
        cfg = (self.app.cfg.get("alert_mail") or {})
        to_addr = cfg.get("to")
        user = cfg.get("user")
        pw = cfg.get("password")
        if not (to_addr and user and pw):
            log("邮件提醒未发送：还没有配置 QQ 邮箱（菜单 → 价格提醒设置）")
            return
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = Header(f"[行情提醒] {title}", "utf-8")
            msg["From"] = formataddr((str(Header("行情条提醒", "utf-8")), user))
            msg["To"] = to_addr
            host = cfg.get("smtp_host") or "smtp.qq.com"
            port = int(cfg.get("smtp_port") or 465)
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) as s:
                s.login(user, pw)
                s.sendmail(user, [to_addr], msg.as_string())
            log(f"邮件提醒已发送 -> {to_addr}")
        except Exception as exc:
            log(f"邮件提醒发送失败: {exc}")

    # ---------------------------------------------------------- 线程 --
    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                with self._lock:
                    pending = any(a["enabled"] for a in self.alerts)
                if pending:
                    rows = dict(self.app.rows or {})
                    self.check(rows)
            except Exception as exc:
                log(f"提醒检查出错: {exc}")
            if self._stop.wait(ALERT_POLL):
                return


def _windows_toast(title, body):
    """Windows 弹窗通知。用 Win10+ 的 Toast，失败退回气泡提示。

    为什么要转义单引号：标题/正文会经 PowerShell 单引号字符串传入，
    里面出现一个 ' 就会把脚本截断（价格和币种名虽少见，但不能不防）。
    """
    def q(s):
        return str(s).replace("'", "''")

    toast_script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
        "[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$t.GetElementsByTagName('text').Item(0).AppendChild($t.CreateTextNode('{q(title)}')) > $null;"
        f"$t.GetElementsByTagName('text').Item(1).AppendChild($t.CreateTextNode('{q(body)}')) > $null;"
        "$n=[Windows.UI.Notifications.ToastNotification]::new($t);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'行情条').Show($n);"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", toast_script],
            capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode == 0:
            return
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()[:200]
        log(f"Toast 返回码 {proc.returncode}（{err}），改用气泡提示")
    except Exception as exc:
        log(f"Toast 通知失败({exc})，改用气泡提示")
    # 退路：老式气泡提示
    try:
        import ctypes as _ct
        _ct.windll.user32.MessageBoxW(None, f"{title}\n\n{body}", "行情提醒", 0x40)
    except Exception as exc:
        log(f"弹窗提醒也失败了: {exc}")


def find_window_by_title(title: str):
    """按标题找可见顶层窗口（Tk 之外的地方用）。"""
    if not ctypes:
        return 0
    found = []

    def _cb(hwnd, _l):
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value.startswith(title):
            found.append(hwnd)
        return True

    try:
        ctypes.windll.user32.EnumWindows(
            ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(_cb), 0)
    except Exception:
        return 0
    return found[0] if found else 0


class ChartServer:
    """常驻本机图表页。

    为什么不用 webbrowser.open 直接开 TradingView：
    那样每点一个品种都会多开一个标签页。这里改成开一个本地页面，
    页面每秒轮询当前品种，原地换 iframe 地址 —— 始终只有一个页面。
    """

    def __init__(self, app):
        self.app = app
        self.port = 0
        self._httpd = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def start(self):
        if self._httpd is not None:
            return self.port
        try:
            handler = type("Handler", (_ChartHandler,), {"app": self.app})
            # 端口传 0 让系统分配，避免和别人撞端口
            self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            self._httpd.daemon_threads = True
            # ⚠️ 打包成 --noconsole 的 exe 后 **stderr 是空的**，
            #    默认的 handle_error() 把异常打到 stderr 就等于**静默吞掉**：
            #    表现为"端口在监听、请求却永远不回"（客户端一直等到超时）。
            #    所以自己接管，把 traceback 写进日志文件。
            def _handle_error(request, client_address):
                log("图表服务处理请求出错:\n" + traceback.format_exc())
            self._httpd.handle_error = _handle_error
            self.port = self._httpd.server_address[1]
            threading.Thread(target=self._httpd.serve_forever,
                             daemon=True).start()
            # 打包后排查用：设了 TICKER_SELFTEST=1 就从**进程内部**请求一次自己。
            # 这一步能把"HTTP 线程没干活"和"外部（防火墙/代理）被挡"分开。
            if os.environ.get("TICKER_SELFTEST"):
                threading.Thread(target=self._selftest, daemon=True).start()
            log(f"图表页已就绪: {self.url}")
            return self.port
        except Exception as exc:
            log(f"图表页启动失败: {exc}")
            self._httpd = None
            return 0

    def _selftest(self):
        """进程内自请求（只在 TICKER_SELFTEST=1 时跑，正常使用不受影响）。"""
        try:
            log(f"[selftest] 线程起来了，环境变量={os.environ.get('TICKER_SELFTEST')!r}")
            import urllib.request
            time.sleep(4)
            log(f"[selftest] 开始请求 {self.url}")
            for path in ("lib/lightweight-charts.js", "", "scan"):
                try:
                    with urllib.request.urlopen(self.url + path, timeout=10) as resp:
                        data = resp.read()
                    log(f"[selftest] /{path} -> 成功 {len(data)} 字节")
                except Exception as exc:
                    log(f"[selftest] /{path} -> 失败 {exc!r}")
        except Exception:
            # ⚠️ --noconsole 的 exe **没有 stderr**：线程里的异常会被静默吞掉，
            #    所以排查期必须自己写进日志文件，不然只能看到"什么都没发生"。
            log("[selftest] 线程崩了:\n" + traceback.format_exc())

    def stop(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None


class TickerApp:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        # ★ 主题必须**最先**生效：后面建控件时会直接按名字取 UI_* 颜色
        self.theme = apply_theme_palette(resolve_theme(cfg))
        self.rows = {}                 # (base,quote) -> 行情 dict
        self.last_ok = 0.0
        self.last_try = 0.0
        self.error = None
        self.source = "-"
        self._price_width = 0          # 单调递增，避免窗口宽度抖动
        self._fonts = {}
        self._drag = None
        self._drag_moved = False        # 本次按下是否真的拖动过
        self._last_drag_time = 0.0      # 上次真正拖动的时间，用于压制误触双击
        self._press_at = (0, 0)
        self._queue: queue.Queue = queue.Queue()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._save_job = None
        self._hidden = False
        self._hwnd_cache = 0
        self._ct_dirty = False
        self._hotkey_map = {}
        self._hotkey_labels = {}
        self._symbol_universe = None       # 永续合约清单（后台预热）
        self._market_overview = None       # 榜单数据
        self._symbols_loading = False
        self._flash = {}                   # (base,quote) -> (方向, 起始时间)
        self._anim_job = None
        self._icon_geom = []               # 行尾图标命中区（闹铃/垃圾桶）
        self._icon_pending = None          # 本次按下落在哪个图标上
        self._level_geom = []              # 品种名后「仓位标记」按钮命中区
        self._level_pending = None         # 本次按下落在哪个标记按钮上
        self._level_win = None             # 仓位设置弹窗
        self._resize = None                # 拖边缩放：当前拖的是哪条边
        self._resize_start = None          # 缩放起点（宽度/高度/字号/位置）
        self._natural_w = 0                # 上一次渲染算出来的"内容自然宽度"
        self._cursor_now = ""
        self._game_mode = False            # 游戏模式（锁鼠标），只存内存不落盘
        self._alerts = AlertEngine(self)   # 价格提醒引擎

        self.root = tk.Tk()
        self.root.title("Crypto Ticker")
        self.root.overrideredirect(True)
        self._apply_style_attrs()

        self.family = resolve_font(self.root, cfg.get("font_family"))
        self.ui = pick_ui_font(self.root)

        # 三段式布局：顶部滚动条 / 中间行情 / 底部输入框
        self.tape = tk.Canvas(self.root, highlightthickness=0, bd=0)
        self.tape.pack(side="top", fill="x")

        self.inbar = tk.Frame(self.root)
        self.inbar.pack(side="bottom", fill="x")
        self._entry_var = tk.StringVar()
        self.entry = tk.Entry(self.inbar, relief="flat", bd=0, highlightthickness=0,
                              width=1,        # ★ 宽度交给 fill/expand 撑，
                                              # 别让输入栏的"请求宽度"把窗口顶宽 ——
                                              # 顶宽了右边就会多出一条没画东西的黑边
                              textvariable=self._entry_var)
        self.entry.pack(side="left", fill="x", expand=True, padx=(3, 2), ipady=1)
        # 用 StringVar 的 trace 而不是 <KeyRelease>：
        # 中文输入法、粘贴、SendInput 的 VK_PACKET 都不会触发 KeyRelease 绑定，
        # 但内容一定变，trace 全都抓得到。
        self._entry_var.trace_add("write", self._on_entry_key)
        # 齿轮 = 设置中心（放在「更多 ▸」左边）。
        # 用户要求：右键菜单太长了，常用开关都收进设置窗口，右键只留快捷项。
        self.gear = ui_gear(self.inbar, self.open_settings, bg=BLUR_TINT)
        self.gear.pack(side="right", padx=(0, 2))
        # 窗口里的「更多」入口：直接打开品种选择器，不用翻右键菜单
        self.more = tk.Label(self.inbar, text="更多 ▸", anchor="e", bd=0,
                             cursor="hand2")
        self.more.pack(side="right", padx=(0, 5))
        self.more.bind("<Button-1>", self._on_more_click)
        self.hint = tk.Label(self.inbar, text="", anchor="e", bd=0)
        self.hint.pack(side="right", padx=(0, 8))
        # 游戏模式指示：**默认不显示**（pack_forget）。
        # ⚠️ 空标签在这里会占出一条深色带（毛玻璃模式下底色是 #1c1c1e），
        # 看着就是"右边多了一块不明所以的黑块"。所以只在真的有字时才 pack 出来。
        self.game_label = tk.Label(self.inbar, text="", anchor="w", bd=0)

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0)
        self.canvas.pack(side="top", fill="both", expand=True)

        self._tape_packed = True
        self._inbar_packed = True
        self._tape_segs = []            # [(文本, 颜色), …]
        self._tape_dirty = True
        self._tape_font = None
        self._tape_offset = 0.0
        self._tape_job = None
        self._tape_width = 0
        self._tape_h = 0
        self._tape_hits = []            # [(x0, x1, base), …] 供点击命中
        self._entry_fg = None
        self._placeholder_fg = None
        self._cand_win = None           # IME 式候选弹窗
        self._cand = None
        self._cand_hits = []
        self._cand_index = 0
        self._inbar_h = 0
        self._win_w = 0
        self._win_h = 0
        self._chart_target = ("BTC", "USDT")    # 图表页当前品种（纯内存，不落盘）
        self._want_scan = False                 # 图表页该显示"全品种扫盘"吗
        self._chart_poll_at = 0.0               # 页面最后一次轮询的时间
        self._tv_symbols = {}                   # 自选代号 -> TradingView 符号
        self._chart_server = None
        # 注意：_entry_var 必须一直持有 Python 引用。
        # tkinter.Variable 被回收时 __del__ 会删掉对应的 Tcl 变量，
        # Entry 的 textvariable 和 trace 就一起失效了。

        self.entry.bind("<KeyPress>", self._on_entry_keypress)
        self.entry.bind("<Return>", self._on_entry_submit)
        self.entry.bind("<Button-1>", self._activate_window, add="+")
        self.inbar.bind("<Button-1>", self._activate_window, add="+")
        self.entry.bind("<Escape>", self._on_entry_escape)
        self.entry.bind("<Tab>", self._on_entry_tab)
        self.entry.bind("<FocusIn>", self._on_entry_focus_in)
        self.entry.bind("<FocusOut>", self._on_entry_focus_out)
        self.tape.bind("<Button-1>", self._on_tape_press)
        self.tape.bind("<B1-Motion>", self._on_drag)
        self.tape.bind("<ButtonRelease-1>", self._on_tape_release)
        self.tape.bind("<Double-Button-1>", self._on_tape_double)
        self._tape_click_job = None
        self._pick_win = None           # 已废弃：下拉不再用独立弹窗
        self._pick_box = None           # 当前展开的那一组列表控件
        self._pick_items = None         # 当前展开那一组的榜单数据
        self._board_panels = {}         # {"topVolume": {row, body, items, open…}}
        self._board_open = None         # 当前展开的组（手风琴，一次一组）

        self.root.bind("<Button-1>", self._on_press)
        self.root.bind("<B1-Motion>", self._on_drag)
        self.root.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Button-3>", self._on_menu)
        self.root.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Button-3>", self._on_menu)
        self.root.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        # 鼠标移到窗口边缘就换成缩放光标（自己做的边框，得自己提示）
        self.root.bind("<Motion>", self._on_hover, add="+")
        self.canvas.bind("<Motion>", self._on_hover, add="+")
        self.root.bind("<Escape>", lambda _e: self.quit())
        self.root.bind("<Control-MouseWheel>", self._on_ctrl_wheel)

        self._build_menu()
        self._cfg_win = None            # 设置中心窗口
        self._settings_page = "display"  # 设置中心当前分类
        self._place_window()
        self._apply_widget_style()
        self._chart_server = ChartServer(self)
        self._chart_server.start()          # 开机就绪，第一次点图表不用等
        self._start_fetcher()
        self._alerts.start()               # 价格提醒检查线程
        self._start_hotkeys()
        self._warm_symbols()
        self.root.after(120, self._pump)
        self.root.after(600, self._start_tape)

    # ------------------------------------------------------------ 窗口 --

    def _apply_widget_style(self):
        """滚动条 / 输入框跟随外观模式：纯文字模式用色键透明，卡片模式用底板色。"""
        if not hasattr(self, "tape"):
            return
        cfg = self.cfg
        style = str(cfg.get("style", "float")).lower()
        float_mode = style == "float"
        day = getattr(self, "theme", "night") == "day"
        card_bg = ((LIGHT_TINT if style == "blur" else LIGHT_CARD) if day
                   else (BLUR_TINT if style == "blur" else BG_DARK))
        pal = text_palette(cfg) if float_mode else (DARK_TEXT if day else LIGHT_TEXT)
        bg = TRANSPARENT_KEY if float_mode else card_bg
        fsize = max(8, int(cfg.get("font_size", 9)) - 1)
        self._tape_font = (self.ui, fsize)
        for widget in (self.tape, self.inbar, self.hint, self.canvas):
            try:
                widget.configure(bg=bg)
            except Exception:
                pass
        try:
            self._entry_fg = pal["sym"]
            self._placeholder_fg = pal["dim"]
            self.entry.configure(
                bg=bg, fg=self._entry_fg, insertbackground=pal["sym"],
                font=(self.ui, fsize),
                selectbackground=PANEL_ACCENT, selectforeground="#000000",
            )
            self.hint.configure(fg=pal["dim"], bg=bg, font=(self.ui, fsize))
            self.more.configure(fg=PANEL_ACCENT, bg=bg, font=(self.ui, fsize))
            self.game_label.configure(fg=LEVEL_WATCH, bg=bg, font=(self.ui, fsize))
            self.gear.configure(bg=bg)
            self.gear.paint(UI_DIM)
            if not self.entry.get().strip() or self._placeholder_on():
                self._show_placeholder()
        except Exception:
            pass

    def _apply_style_attrs(self):
        style = str(self.cfg.get("style", "float")).lower()
        alpha = max(0.2, min(1.0, float(self.cfg.get("alpha", 1.0))))
        try:
            if style == "float":
                # 纯文字：色键透明，桌面直接透出来
                self.root.configure(bg=TRANSPARENT_KEY)
                self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
            elif style == "blur":
                # 毛玻璃：不能用色键，否则没有地方承载模糊
                bg = LIGHT_TINT if getattr(self, "theme", "night") == "day" else BLUR_TINT
                self.root.configure(bg=bg)
                self.root.attributes("-transparentcolor", "")
            else:
                bg = LIGHT_CARD if getattr(self, "theme", "night") == "day" else BG_DARK
                self.root.configure(bg=bg)
                self.root.attributes("-transparentcolor", "")
            self.root.attributes("-alpha", alpha)
            self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
        except Exception as exc:
            log(f"设置窗口属性失败: {exc}")
        self._set_blur(style == "blur")
        self.apply_click_through()

    def _set_blur(self, enable):
        """开启 Windows 亚克力毛玻璃背景（未公开 API，失败就静默降级）。"""
        if not ctypes or WINCOMPATTRDATA is None:
            return
        hwnd = self._hwnd()
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            if not hasattr(user32, "SetWindowCompositionAttribute"):
                return
            accent = ACCENT_POLICY()
            if enable:
                accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
                accent.AccentFlags = 2
                accent.GradientColor = BLUR_ABGR
            else:
                accent.AccentState = ACCENT_DISABLED
            data = WINCOMPATTRDATA(WCA_ACCENT_POLICY,
                                   ctypes.pointer(accent),
                                   ctypes.sizeof(accent))
            ok = user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
            log(f"毛玻璃 {'已开启' if enable else '已关闭'} (API 返回 {ok})")
        except Exception as exc:
            log(f"毛玻璃设置失败: {exc}")

    def _apply_round_region(self, w, h, radius=11):
        """用窗口区域裁出圆角，毛玻璃/卡片模式下四个角才不会是方的。"""
        if not ctypes:
            return
        hwnd = self._hwnd()
        if not hwnd:
            return
        style = str(self.cfg.get("style", "float")).lower()
        try:
            if style == "float":
                ctypes.windll.user32.SetWindowRgn(hwnd, None, True)   # 纯文字模式不要裁
                return
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1,
                                                         radius * 2, radius * 2)
            if rgn and not ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True):
                ctypes.windll.gdi32.DeleteObject(rgn)
        except Exception as exc:
            log(f"圆角设置失败: {exc}")

    def _place_window(self):
        pos = self.cfg.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            self._pos = [int(pos[0]), int(pos[1])]
            self._pos_auto = False
        else:
            self._pos = None            # 首次运行：靠右上角摆放，并随宽度自适应
            self._pos_auto = True

    def _set_geometry(self, w: int, h: int):
        if self._pos is None:
            self._pos = [0, 24]
        if self._pos_auto:
            # 价格位数变化会改变窗口宽度，始终贴住右边缘才不会超出屏幕
            self._pos[0] = max(0, self.root.winfo_screenwidth() - w - 24)
        x, y = self._pos
        x = max(0, min(x, self.root.winfo_screenwidth() - w))
        y = max(0, min(y, self.root.winfo_screenheight() - h))
        self._pos = [x, y]
        cur = self.root.geometry()                       # "WxH+X+Y"
        try:
            size = cur.split("+", 1)[0]
            cw, ch = (int(v) for v in size.split("x"))
        except Exception:
            cw = ch = -1
        if cw == w and ch == h and self._mapped_pos == (x, y):
            self._win_w, self._win_h = w, h      # 尺寸没变也要记，候选窗要用
            return
        self._mapped_pos = (x, y)
        self._win_w, self._win_h = w, h
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._apply_round_region(w, h)

    _mapped_pos = None

    # ---------------------------------------------- Windows 窗口扩展 --

    def _hwnd(self):
        """真正的**顶层**窗口句柄。

        ⚠️ 这里踩过一个很隐蔽的大坑：原来是
            (GetParent(root.winfo_id()) or root.winfo_id())
        而且**只算一次、缓存起来**。可它在 `__init__` 早期就被调用了
        （`_apply_style_attrs` → `apply_click_through`），那时候 Tk 还没把这个
        窗口挂到 TkTopLevel 下面，`GetParent` 返回 0，于是缓存下来的是
        **内层 TkChild**。后果有两个：

        1. `WS_EX_LAYERED` 被加到了子窗口上，而子窗口没有任何分层属性，
           DWM 不再合成它的内容 → **整个窗口变成一块不透明黑方块**，内容全看不见
           （用户原话：「一点锁鼠标，整个窗口都变成黑色，什么东西都不见了」）
        2. 「鼠标穿透」其实**从来没真生效**：透明位加在子窗口上，
           点击只是落到父窗口，并没有穿透到游戏里

        现在改成每次都解析一遍，用 `GetAncestor(GA_ROOT)` 一路找到真正的顶层。
        """
        if not ctypes:
            return 0
        user32 = ctypes.windll.user32
        try:
            base = self.root.winfo_id()
            GA_ROOT = 2
            hwnd = user32.GetAncestor(base, GA_ROOT) or user32.GetParent(base) or base
        except Exception:
            return 0
        self._hwnd_cache = hwnd
        return hwnd

    def apply_click_through(self):
        """开启后整窗（含文字）都不接收鼠标，游戏点击完全不受影响。

        ⚠️ 两条铁律（都是踩出来的）：

        1. **只动 `WS_EX_TRANSPARENT` 这一位**。`WS_EX_LAYERED` 是 *Tk 自己*
           为了 `-alpha` / `-transparentcolor` 加的，我们既不该替它加、
           也不该替它删。以前那句 `ex | WS_EX_LAYERED` 会往一个没有分层属性的
           窗口上硬加分层样式 —— 结果就是整窗黑掉（内容不可见）。
        2. **改完样式必须补一次分层属性**。`SetWindowLongW` 会把 Tk 之前设好的
           alpha / 透明色键清掉，不补的话窗口会变成一块不透明深色方块。
           所以 `_restore_layered_attrs()` 开、关两个方向都要调。
        """
        if not ctypes:
            return
        # 游戏模式强制穿透：这样点击是"落到游戏里"，而不是被行情条吃掉
        want = bool(self.cfg.get("click_through")) or bool(getattr(self, "_game_mode", False))
        if not want and not self._ct_dirty:
            return
        hwnd = self._hwnd()
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex = (ex | WS_EX_TRANSPARENT) if want else (ex & ~WS_EX_TRANSPARENT)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
            self._ct_dirty = True
            self._restore_layered_attrs()
        except Exception as exc:
            log(f"设置鼠标穿透失败: {exc}")

    def _restore_layered_attrs(self):
        """SetWindowLong 之后重新下发分层属性，否则窗口会整体变透明。"""
        try:
            float_mode = str(self.cfg.get("style", "float")).lower() == "float"
            if float_mode:
                self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
            else:
                self.root.attributes("-transparentcolor", "")
            self.root.attributes("-alpha", max(0.2, min(1.0, float(self.cfg.get("alpha", 1.0)))))
        except Exception as exc:
            log(f"恢复窗口透明度失败: {exc}")

    def toggle_click_through(self, value=None):
        self.cfg["click_through"] = (not bool(self.cfg.get("click_through"))
                                     if value is None else bool(value))
        self.apply_click_through()
        save_config(self.cfg)

    def toggle_visible(self):
        if self._hidden:
            self.root.deiconify()
            self._hidden = False
            self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
            self.apply_click_through()
        else:
            self.root.withdraw()
            self._hidden = True

    def _warm_symbols(self):
        """后台预热合约清单与榜单，打开选择器时就不用等。"""
        def work():
            try:
                overview = load_market_overview()
                self._market_overview = overview
                self._symbol_universe = overview.get("symbols") or FALLBACK_SYMBOLS
                self._tape_dirty = True
            except Exception as exc:
                log(f"合约清单预热失败: {exc}")
        threading.Thread(target=work, daemon=True).start()
        self._start_rank_refresh()
        self._start_oi_refresh()

    def _start_oi_refresh(self):
        """持仓变化榜。

        要逐个币查 openInterestHist，没有批量接口，所以：
        * 只扫成交额前 OI_SCAN_LIMIT 名（有行情的那批）
        * 刷新间隔比普通榜单长得多（默认 10 分钟，4 小时窗口本来也变化慢）
        """
        if not bool(self.cfg.get("show_oi", True)):
            return
        interval = max(120, int(self.cfg.get("oi_refresh", 600)))

        def loop():
            # 先等合约清单就绪。这里必须"等着"，不能"读不到就跳过"——
            # 否则会和清单加载线程抢跑，读空之后直接睡满 interval，
            # 表现为增仓榜有时十几分钟才出来。
            for _ in range(180):                # 最多等 90 秒
                if self._stop.is_set():
                    return
                if (self._market_overview or {}).get("symbols"):
                    break
                self._stop.wait(0.5)

            while not self._stop.is_set():
                overview = self._market_overview or {}
                symbols = list(overview.get("symbols") or [])
                if not symbols:
                    if self._stop.wait(5):
                        return
                    continue
                scan = symbols if OI_SCAN_LIMIT <= 0 else symbols[:OI_SCAN_LIMIT]
                started = time.time()
                try:
                    rows = fetch_oi_changes(scan, self.cfg.get("quote", "USDT"))
                    top = rank_oi(rows, 10)
                    if top:
                        merged = dict(self._market_overview or {})
                        merged["topOI"] = top
                        self._market_overview = merged
                        self._tape_dirty = True
                        self._queue.put(("render", None))
                        log(f"增仓榜已更新：查了 {len(rows)} 个币，"
                            f"耗时 {time.time()-started:.1f}s，"
                            f"首位 {top[0]['base']} {top[0]['change']:+.2f}%")
                except Exception as exc:
                    log(f"增仓榜刷新失败: {exc}")
                if self._stop.wait(interval):
                    return

        threading.Thread(target=loop, daemon=True).start()

    def _start_rank_refresh(self):
        """榜单单独定时刷新——涨幅榜几分钟就换一批，不能跟着 24h 的合约清单走。"""
        interval = max(30, int(self.cfg.get("rank_refresh", 60)))

        def loop():
            while not self._stop.is_set():
                if self._stop.wait(interval):
                    return
                universe = getattr(self, "_symbol_universe", None)
                overview = self._market_overview or {}
                if not universe:
                    continue
                try:
                    fresh = fetch_rankings(universe, overview.get("bigCaps") or [], timeout=15)
                    if fresh.get("symbols"):
                        merged = dict(overview)
                        for key in ("topVolume", "topGainers", "topLosers"):
                            merged[key] = fresh.get(key) or []
                        self._market_overview = merged
                        self._tape_dirty = True
                        self._queue.put(("render", None))
                except Exception as exc:
                    log(f"榜单刷新失败: {exc}")

        threading.Thread(target=loop, daemon=True).start()

    # -------------------------------------------------------- 全局热键 --

    def _start_hotkeys(self):
        if not ctypes or not self.cfg.get("hotkeys", True):
            return
        threading.Thread(target=self._hotkey_loop, daemon=True).start()

    def _hotkey_loop(self):
        user32 = ctypes.windll.user32
        registered, labels, hid = [], {}, 100
        for name, candidates in HOTKEY_DEFS.items():
            for label, mods, vk in candidates:
                if user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                    self._hotkey_map[hid] = name
                    labels[name] = label
                    registered.append(hid)
                    hid += 1
                    break
            else:
                log(f"热键注册失败（候选组合都被占用）: {name}")
        self._hotkey_labels = labels
        log(f"全局热键就绪: {labels}")
        self._queue.put(("hotkeys", dict(labels)))
        msg = wintypes.MSG()
        while not self._stop.is_set():
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY:
                    self._queue.put(("hotkey", int(msg.wParam)))
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.06)
        for hid_ in registered:
            user32.UnregisterHotKey(None, hid_)

    def _handle_hotkey(self, hid):
        name = self._hotkey_map.get(hid)
        if name == "toggle":
            self.toggle_visible()
        elif name == "menu":
            self.popup_menu_at_cursor()
        elif name == "click":
            self.toggle_click_through()
        elif name == "symbols":
            self.open_symbols()
        elif name == "game":
            self.toggle_game_mode()
        elif name == "scan":
            self.open_scan()

    def _update_hotkey_hint(self, labels):
        """把实际注册成功的组合键写进菜单。

        为什么要写进菜单：热键**会因为被别的程序占用而自动顺延**
        （Ctrl+Alt+H 被占就退到 Ctrl+Shift+Alt+H）。组合键悄悄变了，
        用户按原键没反应，只会以为功能坏了。所以真实生效的组合键
        必须能一眼看到——「热键」子菜单，外加直接挂在
        「隐藏窗口」/「游戏模式」这两条常用项后面。
        """
        self._hotkey_labels = dict(labels or {})
        # 「隐藏窗口 (Ctrl+Alt+H)」：最常用的一个，直接写在菜单项上
        idx = getattr(self, "_mi_hide_idx", None)
        if idx is not None:
            try:
                combo = self._hotkey_labels.get("toggle") or "未注册"
                self.menu.entryconfigure(idx, label=f"隐藏窗口（{combo}）")
            except Exception:
                pass
        # 游戏模式同理 —— 锁住鼠标之后只剩热键能解开，更不能忘
        gidx = getattr(self, "_mi_game_idx", None)
        if gidx is not None:
            try:
                combo = self._hotkey_labels.get("game") or "未注册"
                self.menu.entryconfigure(gidx, label=f"游戏模式（锁鼠标 · {combo}）")
            except Exception:
                pass
        menu = getattr(self, "_hk_menu", None)
        if menu is None:
            return
        try:
            menu.delete(0, "end")
            for key in ("toggle", "menu", "symbols", "click", "game", "scan"):
                name = HOTKEY_NAMES.get(key, key)
                menu.add_command(label=f"{name}   {self._hotkey_labels.get(key, '未注册')}",
                                 state="disabled")
        except Exception:
            pass

    # -------------------------------------------------------- 字体缓存 --

    def _font(self, kind: str, size: int, bold: bool = False):
        # 一律不加粗：细体字重本身就是这套配色的优雅来源
        key = (kind, size)
        if key not in self._fonts:
            family = self.family if kind == "mono" else self.ui
            self._fonts[key] = tkfont.Font(family=family, size=size, weight="normal")
        return self._fonts[key]

    # ---------------------------------------------------------- 渲染 --

    def render(self):
        cfg = self.cfg
        cv = self.canvas
        cv.delete("all")

        style = str(cfg.get("style", "float")).lower()
        float_mode = style == "float"
        blur_mode = style == "blur"
        # 白天主题：卡片底色转浅、文字转黑（纯文字模式本来就是透明 + 用户自选字色）
        day = getattr(self, "theme", "night") == "day"
        card_bg = ((LIGHT_TINT if blur_mode else LIGHT_CARD) if day
                   else (BLUR_TINT if blur_mode else BG_DARK))
        flip = str(cfg.get("scheme", "west")).lower() == "cn"
        up_color = UP_CN if flip else UP_WEST
        down_color = DOWN_CN if flip else DOWN_WEST
        colored = bool(cfg.get("change_colored", False))
        # 卡片模式自带底色，无论如何都得用对比够的字色
        pal = text_palette(cfg) if float_mode else (DARK_TEXT if day else LIGHT_TEXT)

        size = int(cfg.get("font_size", 9))
        show_change = bool(cfg.get("show_change", True))
        show_header = bool(cfg.get("show_header", False))
        fresh = (time.time() - self.last_ok) < max(8, float(cfg.get("interval", 3)) * 3)
        f_sym = self._font("num", size)
        f_num = self._font("num", size)
        f_meta = self._font("ui", max(8, size - 2))

        pairs = self.pairs
        # 纯文字模式：留白压到最小，只包住文字本身
        pad = 2 if float_mode else 11
        gap = 8 if float_mode else 10
        row_h = int(f_num.metrics("linespace") * (1.28 if float_mode else 1.62))
        header_h = (f_meta.metrics("linespace") + 2) if show_header else 0

        # 列宽（价格列宽单调递增，避免数字位数变化导致窗口左右跳动）
        show_del = bool(cfg.get("show_del", False))
        show_bell = bool(cfg.get("show_alert", True))
        ICON_W = 13                       # 每个图标占的宽度（图形只有 5~8px，
                                          # 格子太宽行尾就会空出一截"莫名的空格"）
        icon_gap = 3                      # 图标区前面的间距（原来 8 太空）
        icon_w = (ICON_W if show_bell else 0) + (ICON_W if show_del else 0)
        sym_w = max([f_sym.measure(b) for b, _q in pairs] + [f_sym.measure("BTC")]) + 2
        chg_w = f_num.measure("-00.00%") + 2 if show_change else 0

        # 仓位 / 关注价位标记列（品种名右边）：
        # 一个小按钮（尺寸固定）+ 一枚小字标签。用户要求标签字号**小于价格数字**、
        # 颜色也要能区分，所以这里用 UI 字体 + size-2，而不是价格那套数字字体。
        show_levels = bool(cfg.get("show_levels", True))
        f_tag = self._font("ui", max(7, size - 2))
        LEV_BTN_W = 11
        lev_tag_w = 0
        if show_levels:
            for _base, _q in pairs:
                _info = self.level_of(_base)
                if _info:
                    lev_tag_w = max(lev_tag_w, f_tag.measure(_info[3]))
        lev_w = (LEV_BTN_W + 3 + lev_tag_w) if show_levels else 0

        for _key, item in self.rows.items():
            self._price_width = max(self._price_width, f_num.measure(fmt_price(item["price"])))
        self._price_width = max(self._price_width, f_num.measure("0.00"))

        quote = pairs[0][1]
        market = str(cfg.get("market", "perp")).lower()
        market_label = "永续" if market == "perp" else "现货"
        title = f"{cfg.get('title', '行情')} · {quote} {market_label}"
        stamp = time.strftime("%H:%M:%S", time.localtime(self.last_ok)) if self.last_ok else "--:--:--"
        head_w = f_meta.measure(title) + f_meta.measure(stamp) + 34 if show_header else 0

        # 列位置：品种 | 标记按钮+标签 | 价格 | 涨跌幅 | 行尾图标
        lev_left = pad + sym_w + gap
        price_right = (lev_left + lev_w + gap + self._price_width) if lev_w \
            else (pad + sym_w + gap + self._price_width)
        width = price_right + (gap + chg_w if show_change else 0) \
            + (icon_gap + icon_w if icon_w else 0) + pad
        width = max(width, head_w, 60)
        height = pad + header_h + row_h * len(pairs) + pad

        # 顶部滚动条 / 底部输入框：占了窗口高度，但不占主画布
        show_tape = bool(cfg.get("show_tape", True))
        show_input = bool(cfg.get("show_input", True))
        if self._tape_dirty or not self._tape_segs:
            self._rebuild_tape()
            self._tape_dirty = False
        self._sync_widgets(show_tape, show_input)

        tape_h = (f_meta.metrics("linespace") + 8) if (show_tape and self._tape_segs) else 0
        self._tape_h = tape_h
        inbar_h = (f_meta.metrics("linespace") + 9) if show_input else 0
        self._inbar_h = inbar_h

        # ★ 宽度必须**三块完全一致**（滚动条 / 行情画布 / 底部输入栏）。
        #   只要有一块的"请求宽度"比别的大，Tk 就会把整个窗口撑宽，
        #   右侧多出来的那几像素没有任何控件画东西 —— 毛玻璃合成出来就是
        #   一条竖着的黑边，还会压住行尾的 ×/🔔 和底部的「更多 ▸」。
        #   （用户反复反馈过"右边多了一个黑的东西"。窗口窄的时候看不出来，
        #    加了仓位标记列变宽之后就很明显。）
        self.root.update_idletasks()
        self._natural_w = int(width)        # 拖边缩放要用它反推字号（见 _do_resize）
        try:
            # ⚠️ 只把**底部输入栏**的请求宽度算进来。
            #   千万别把滚动条(tape)的请求宽度也算上 —— 它上一次被设成多宽，
            #   这一次就"要求"多宽，于是宽度只增不减（自锁棘轮），
            #   拖边缩放也会因此变得迟钝。
            need = max(int(width), self.inbar.winfo_reqwidth())
        except Exception:
            need = int(width)
        width = need

        if tape_h:
            self.tape.configure(width=width, height=tape_h)
        if show_input:
            self.inbar.configure(width=width, height=inbar_h)
            self.inbar.pack_propagate(False)
            try:
                self.entry.configure(font=(self.ui, max(8, size - 1)))
                self.hint.configure(font=(self.ui, max(8, size - 1)))
            except Exception:
                pass
        cv.configure(width=width, height=height, bg=TRANSPARENT_KEY if float_mode else card_bg)

        self._set_geometry(width, height + tape_h + inbar_h)

        if tape_h:
            self._draw_tape()
            self._start_tape()

        # 毛玻璃 / 卡片：画一块圆角底板；纯文字模式什么都不画
        if not float_mode:
            # ⚠️ 必须用 canvas 的**实际**尺寸来画，不能用算出来的 width。
            # canvas 是 fill="both" 撑开的，实际会比 width 宽几个像素，
            # 用 width 画的话右边那几像素就是"没画到底"的空白 ——
            # 毛玻璃合成出来就是**右边一条黑边**（用户一眼就看出来了）。
            cv.update_idletasks()
            rw = max(self.canvas.winfo_width(), width)
            rh = max(self.canvas.winfo_height(), height)
            round_rect(cv, 0, 0, rw, rh, 11, fill=card_bg, outline="")

        # 文字效果：细描边最耐看，粗描边只在背景极花时用
        ring = EFFECT_OFFSETS.get(str(cfg.get("text_effect", "outline")))
        if not isinstance(ring, (list, tuple)):
            # ⚠️ 打包成 exe 后这里真的拿到过**字符串**（于是 put() 里
            #    `for dx, dy in ring` 逐字符解包 → ValueError: not enough values
            #    to unpack (expected 2, got 1) → 第一次渲染就崩、进程退出，
            #    表现却是"端口在监听、图表页永远不回" —— 查了很久。
            #    与其猜（exe 里没有 stderr，异常还会被吞），不如就地兜住 + 记下来。
            log(f"文字效果 {cfg.get('text_effect')!r} 的偏移量异常：{ring!r}，改用细描边")
            ring = EFFECT_OFFSETS["outline"]
        ring = [p for p in ring
                if isinstance(p, (list, tuple)) and len(p) == 2]

        def put(x, y, text, font, fill, anchor):
            if float_mode:
                for dx, dy in ring:
                    cv.create_text(x + dx, y + dy, text=text, font=font,
                                   fill=pal["outline"], anchor=anchor)
            cv.create_text(x, y, text=text, font=font, fill=fill, anchor=anchor)

        # ---- 表头（默认关闭，省地方）----
        if show_header:
            hy = pad + header_h // 2
            dot = "#0ecb81" if (fresh and not self.error) else "#f0b90b"
            if self.error and self.rows:
                dot = "#f6465d"
            cv.create_oval(pad, hy - 3, pad + 5, hy + 3, fill=dot, outline="")
            put(pad + 9, hy, title, f_meta, pal["dim"], "w")
            if self.error and not self.rows:
                put(width - pad, hy, "连接中…", f_meta, "#f0b90b", "e")
            else:
                put(width - pad, hy, stamp, f_meta, pal["dim"], "e")

        # ---- 币种行 ----
        chg_right = price_right + (gap + chg_w if show_change else 0)
        self._row_geom = []                  # 双击命中测试用：[y_top, y_bottom, base, quote]
        # 行尾图标命中区：[y_top, y_bottom, base, quote, x0, x1, kind]
        # kind: 'bell' 闹铃 / 'del' 垃圾桶。两个都是**单击**生效，不防误触。
        self._icon_geom = []
        # 仓位标记命中区：[y_top, y_bottom, base, quote, x0, x1]
        self._level_geom = []
        alerted = set()
        engine = getattr(self, "_alerts", None)
        if engine is not None:
            try:
                alerted = engine.symbol_set()
            except Exception:
                alerted = set()
        icon_right = width - pad
        for idx, (base, quote_) in enumerate(pairs):
            row_top = pad + header_h + row_h * idx
            cy = row_top + row_h // 2
            self._row_geom.append((row_top, row_top + row_h, base, quote_))
            item = self.rows.get((base, quote_))
            # 断网时价格变暗，替代表头指示灯，不占额外空间
            price_color = pal["price"] if (fresh or not self.rows) else pal["dim"]
            if item is None:
                put(pad, cy, base, f_sym, pal["sym"], "w")
                put(price_right, cy, "—", f_num, pal["dim"], "e")
                if show_change:
                    put(chg_right, cy, "—", f_num, pal["dim"], "e")
            else:
                change = item["change"]
                color = (up_color if change >= 0 else down_color) if colored else pal["change"]

                # 刚变过价：价格先染成亮绿/亮红，再按平方曲线淡回原色
                flash = self._flash.get((base, quote_))
                if flash:
                    direction, started = flash
                    elapsed_ms = (time.time() - started) * 1000.0
                    if elapsed_ms < FLASH_MS:
                        k = 1.0 - (elapsed_ms / FLASH_MS)
                        price_color = lerp_color(price_color,
                                                 FLASH_UP if direction > 0 else FLASH_DOWN,
                                                 k * k)

                put(pad, cy, base, f_sym, pal["sym"], "w")
                put(price_right, cy, fmt_price(item["price"]), f_num, price_color, "e")
                if show_change:
                    put(chg_right, cy, f"{change:+.2f}%", f_num, color, "e")

            # ---- 品种名后的「仓位 / 关注价位」小按钮 + 标记 ----
            # 小按钮是个"靶心"：没设过是暗灰的，设过就染成标记色（多=红 空=绿 看=琥珀）。
            # 点了（单击）弹设置窗，可以改价位、改方向、删掉。
            if lev_w:
                info = self.level_of(base)
                # ⚠️ 变量名别叫 ring！上面 `ring` 是**文字描边偏移量**，
                #    put() 闭包要用它；这里覆盖成颜色字符串之后，
                #    纯文字(float)模式下 put() 会拿颜色去逐字符解包 →
                #    ValueError: not enough values to unpack (expected 2, got 1)
                #    → 第一次渲染就崩（默认配置就是 float，所以打包出来的 exe 一启动就死）。
                ring_col = info[2] if info else pal["dim"]
                bx = lev_left + LEV_BTN_W / 2.0
                cv.create_oval(bx - 3.4, cy - 3.4, bx + 3.4, cy + 3.4,
                               outline=ring_col, width=1)
                cv.create_oval(bx - 1.0, cy - 1.0, bx + 1.0, cy + 1.0,
                               fill=ring_col, outline="")
                hit_right = lev_left + LEV_BTN_W + 2
                if info:
                    put(lev_left + LEV_BTN_W + 3, cy, info[3], f_tag, info[2], "w")
                    hit_right = lev_left + LEV_BTN_W + 3 + f_tag.measure(info[3]) + 2
                self._level_geom.append((row_top, row_top + row_h, base, quote_,
                                         lev_left - 3, hit_right))

            # ---- 行尾图标：闹铃（设提醒） / 垃圾桶（删自选）----
            if icon_w:
                ix = icon_right
                if show_del:
                    ix -= ICON_W
                    self._icon_geom.append((row_top, row_top + row_h, base, quote_, ix, ix + ICON_W, "del"))
                    tcx = ix + ICON_W / 2.0
                    d = 2.5
                    cv.create_line(tcx - d, cy - d, tcx + d, cy + d, fill=pal["dim"], width=1)
                    cv.create_line(tcx - d, cy + d, tcx + d, cy - d, fill=pal["dim"], width=1)
                if show_bell:
                    ix -= ICON_W
                    self._icon_geom.append((row_top, row_top + row_h, base, quote_, ix, ix + ICON_W, "bell"))
                    # 有提醒的品种，铃铛点亮成黄色，一眼能看出"这个我设过"
                    has = (f"{base.upper()}|{quote_.upper()}" in alerted)
                    bell_col = OVERLAY_ON if has else pal["dim"]
                    bx = ix + ICON_W / 2.0
                    by = cy - 0.5
                    # 铃身：一个半圆 + 两条边
                    cv.create_arc(bx - 4, by - 6, bx + 4, by + 2, start=0, extent=180,
                                  style="chord", fill=bell_col, outline=bell_col)
                    cv.create_line(bx - 4, by - 2, bx - 4, by + 2, fill=bell_col, width=1)
                    cv.create_line(bx + 4, by - 2, bx + 4, by + 2, fill=bell_col, width=1)
                    cv.create_line(bx - 5, by + 2.5, bx + 5, by + 2.5, fill=bell_col, width=1)
                    # 铃舌
                    cv.create_oval(bx - 1.2, by + 3.6, bx + 1.2, by + 6.0,
                                   fill=bell_col, outline=bell_col)

        self.canvas.update_idletasks()

    # -------------------------------------------------------- 交互 --

    def _in_input_area(self, event):
        """点在底部输入区时不要触发拖拽/双击图表。"""
        return event.widget in (self.entry, self.inbar, self.hint, self.more)

    def _on_more_click(self, _event=None):
        """点「更多 ▸」打开品种选择器。"""
        if self._blocked():
            return "break"
        self.open_symbols()
        return "break"

    DRAG_SLOP = 5                       # 超过这么多像素才算"拖动"，不是"点击"

    # ---- 拖边缩放（v0.19）---------------------------------------------
    # 用户要求：「鼠标能拖动这个窗口的大小，它会自适应的缩小字，不妨碍我看」。
    # overrideredirect 窗口没有系统边框，所以边缘感应区得自己做。
    RESIZE_PX = 6
    RESIZE_CURSORS = {"left": "size_we", "right": "size_we",
                      "top": "size_ns", "bottom": "size_ns",
                      "tl": "size_nw_se", "br": "size_nw_se",
                      "tr": "size_ne_sw", "bl": "size_ne_sw"}

    def _resize_zone(self, x, y):
        """鼠标在窗口边缘的哪一段？返回 None / left / right / top / bottom / 四角。"""
        w, h = int(self._win_w or 0), int(self._win_h or 0)
        if w <= 20 or h <= 20:
            return None
        left = x <= self.RESIZE_PX
        right = x >= w - self.RESIZE_PX
        top = y <= self.RESIZE_PX
        bot = y >= h - self.RESIZE_PX
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bot and left:
            return "bl"
        if bot and right:
            return "br"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bot:
            return "bottom"
        return None

    def _win_xy(self, event):
        """事件坐标 → 窗口内坐标（不管事件来自哪个子控件）。"""
        try:
            return (event.x_root - self.root.winfo_rootx(),
                    event.y_root - self.root.winfo_rooty())
        except Exception:
            return (event.x, event.y)

    def _begin_resize(self, zone, event):
        self._resize = zone
        self._resize_start = {
            "zone": zone, "x": event.x_root, "y": event.y_root,
            "w": int(self._win_w or 0), "h": int(self._win_h or 0),
            "size": int(self.cfg.get("font_size", 9)),
            "pos": list(self._pos),
        }
        self._drag = None
        self._drag_moved = False
        self._icon_pending = None
        self._level_pending = None
        try:
            self.root.configure(cursor=self.RESIZE_CURSORS.get(zone, "fleur"))
        except Exception:
            pass

    def _do_resize(self, event):
        """拖边 = 整体缩放：字号按比例变，窗口尺寸跟着内容自适应。

        为什么用"缩放字号"而不是"拉伸画布"：一行的列宽全是按字号量出来的，
        字号一动，价格/涨跌/标记列会**一起**等比缩放，数字不会挤在一起、
        也不会被裁掉 —— 这正是用户要的"自适应的缩小字，不妨碍看"。
        """
        st = getattr(self, "_resize_start", None)
        if not st:
            return
        zone = st["zone"]
        dx = event.x_root - st["x"]
        dy = event.y_root - st["y"]
        w0, h0 = max(st["w"], 1), max(st["h"], 1)
        want_w = w0 + (dx if "r" in zone or zone == "right" else
                       (-dx if "l" in zone or zone == "left" else 0))
        want_h = h0 + (dy if "b" in zone or zone == "bottom" else
                       (-dy if "t" in zone or zone == "top" else 0))
        # 只按"真正被拖的那个方向"定比例；四角优先用宽度
        if zone in ("top", "bottom"):
            ratio = want_h / float(h0)
        else:
            ratio = want_w / float(w0)
        ratio = max(0.4, min(3.0, ratio))
        new_size = int(round(st["size"] * ratio))
        new_size = max(7, min(24, new_size))
        if new_size == int(self.cfg.get("font_size", 9)):
            return
        self.cfg["font_size"] = new_size
        self.render()
        # 拖左边/上边时，让对边别动
        if "l" in zone or zone == "left":
            self._pos = [st["pos"][0] + (st["w"] - self._win_w), self._pos[1]]
        if "t" in zone or zone == "top":
            self._pos = [self._pos[0], st["pos"][1] + (st["h"] - self._win_h)]
        self._mapped_pos = None
        try:
            self.root.geometry(f"+{int(self._pos[0])}+{int(self._pos[1])}")
        except Exception:
            pass
        self._schedule_save_position()

    def _end_resize(self):
        st = getattr(self, "_resize_start", None)
        self._resize = None
        self._resize_start = None
        try:
            self.root.configure(cursor="")
        except Exception:
            pass
        if st and int(self.cfg.get("font_size", 9)) != st["size"]:
            save_config(self.cfg)          # 缩放结果落盘（下次开机还是这个大小）
            log(f"窗口缩放 → 字号 {self.cfg['font_size']}")

    def _on_hover(self, event):
        """鼠标移到边缘就换缩放光标，让人知道"这儿能拖"。"""
        if getattr(self, "_resize", None) or getattr(self, "_drag", None):
            return
        try:
            x, y = self._win_xy(event)
            zone = self._resize_zone(x, y)
            cur = self.RESIZE_CURSORS.get(zone, "") if zone else ""
            if cur != getattr(self, "_cursor_now", ""):
                self._cursor_now = cur
                self.root.configure(cursor=cur)
        except Exception:
            pass

    def _begin_press(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        self._drag_moved = False
        self._press_at = (self._pos[0], self._pos[1])

    def _on_press(self, event):
        if self._blocked():
            return "break"
        if self._in_input_area(event):
            return
        # 拖窗口边缘 = 缩放（先判断，不然会被当成拖窗口/点图标）
        x, y = self._win_xy(event)
        zone = self._resize_zone(x, y)
        if zone:
            self._begin_resize(zone, event)
            return "break"
        # 行尾图标（闹铃/垃圾桶）和品种名后的仓位标记按钮：
        # 都不要走拖窗口那套，否则第一下就把窗口拖走了
        hit = None
        lv = None
        if event.widget is self.canvas:
            lv = self._level_at(event.x, event.y)
            if lv is None:
                hit = self._row_trash_at(event.x, event.y)
        if lv is not None:
            self._level_pending = lv
            self._icon_pending = None
            self._drag = None
            self._drag_moved = False
            return
        if hit is not None:
            self._level_pending = None
            self._icon_pending = hit
            self._drag = None
            self._drag_moved = False
            return
        self._level_pending = None
        self._icon_pending = None
        self._begin_press(event)

    def _on_drag(self, event):
        if self._blocked():
            return "break"
        if getattr(self, "_resize", None):
            self._do_resize(event)
            return "break"
        if not self._drag:
            return
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        if not self._drag_moved:
            # 抖动几像素不算拖动——否则"想拖窗口"会被当成"点了两下"
            if abs(x - self._press_at[0]) < self.DRAG_SLOP and \
               abs(y - self._press_at[1]) < self.DRAG_SLOP:
                return
            self._drag_moved = True
            self._last_drag_time = time.time()
        self._pos = [x, y]
        self._pos_auto = False           # 用户手动拖过之后，不再自动贴右边缘
        self._mapped_pos = (x, y)
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, event):
        if self._blocked():
            return "break"
        if getattr(self, "_resize", None):
            self._end_resize()
            return "break"
        # 仓位标记按钮：起落必须在同一个按钮上才算数（按住挪走就作废）
        lv_pending = getattr(self, "_level_pending", None)
        self._level_pending = None
        if lv_pending is not None:
            drop = None
            if event is not None and getattr(event, "widget", None) is self.canvas:
                drop = self._level_at(event.x, event.y)
            if drop is not None and \
                    (str(drop[0]).upper(), str(drop[1]).upper()) == \
                    (str(lv_pending[0]).upper(), str(lv_pending[1]).upper()):
                self.open_level(drop[0], drop[1])
            return
        # 行尾图标的起落必须在同一个图标上才算数（按住挪走就作废）
        pending = getattr(self, "_icon_pending", None)
        self._icon_pending = None
        if pending is not None:
            drop = None
            if event is not None and getattr(event, "widget", None) is self.canvas:
                drop = self._row_trash_at(event.x, event.y)
            if drop is not None and \
                    (str(drop[0]).upper(), str(drop[1]).upper(), drop[2]) == \
                    (str(pending[0]).upper(), str(pending[1]).upper(), pending[2]):
                self._on_icon_click(drop[0], drop[1], drop[2])
            return
        if self._drag:
            moved = self._drag_moved
            self._drag = None
            # 用完立刻清掉。Tk 里双击的第二次按下只触发 <Double-Button-1>，
            # 不会再走 _on_press，旧值留着会让下一次正常双击被误拦。
            self._drag_moved = False
            if moved:
                self._schedule_save_position()

    def _dragged_recently(self, window=0.6):
        """刚拖过窗口就不响应点击类动作，避免"想拖动却打开了图表"。"""
        if self._drag_moved:
            return True
        return (time.time() - getattr(self, "_last_drag_time", 0.0)) < window

    def _schedule_save_position(self):
        if self._save_job:
            try:
                self.root.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.root.after(600, self._save_position)

    def _save_position(self):
        self._save_job = None
        if self._pos:
            self.cfg["position"] = [int(self._pos[0]), int(self._pos[1])]
            save_config(self.cfg)

    def _on_wheel(self, event):
        if self._blocked():
            return "break"
        step = 0.05 if event.delta > 0 else -0.05
        self.set_alpha(float(self.cfg.get("alpha", 1.0)) + step)
        return "break"

    def _on_ctrl_wheel(self, event):
        if self._blocked():
            return "break"
        self.set_font_size(int(self.cfg.get("font_size", 13)) + (1 if event.delta > 0 else -1))
        return "break"

    # ------------------------------------------ 顶部滚动条 / 底部输入 --

    def _tape_enabled(self):
        return bool(self.cfg.get("show_tape", True))

    def _rebuild_tape(self):
        """把榜单拼成若干带颜色的片段，供滚动显示。"""
        ov = self._market_overview or {}
        flip = str(self.cfg.get("scheme", "west")).lower() == "cn"
        up, down = (UP_CN, DOWN_CN) if flip else (UP_WEST, DOWN_WEST)
        style = str(self.cfg.get("style", "float")).lower()
        pal = text_palette(self.cfg) if style == "float" else LIGHT_TEXT
        label_color = pal["dim"]

        segs = []
        # 滚动条上只放前 5 个，太长会滚很久才轮到下一组
        groups = (
            ("涨幅", "topGainers", up),
            ("跌幅", "topLosers", down),
            ("成交量", "topVolume", pal["sym"]),
        )
        if bool(self.cfg.get("show_oi", True)) and ov.get("topOI"):
            groups = groups + (("增仓", "topOI", up),)
        for label, key, color in groups:
            items = (ov.get(key) or [])[:5]
            if not items:
                continue
            if segs:
                segs.append(("     ◆     ", label_color, None))
            segs.append((f"{label} ", label_color, None))
            for item in items:
                base = str(item.get("base") or "?")
                change = float(item.get("change") or 0.0)
                # 名称和涨跌幅都带上币种，点哪一段都能跳图表
                segs.append((f"{base} ", pal["sym"], base))
                segs.append((f"{change:+.1f}%  ", color, base))

        self._tape_segs = segs
        self._tape_width = 0
        if segs and self._tape_font is not None:
            try:
                f = tkfont.Font(root=self.root, font=self._tape_font)
                self._tape_width = int(sum(f.measure(text) for text, _c, _b in segs))
            except Exception:
                self._tape_width = 0
        if self._tape_width <= 0:
            self._tape_offset = 0.0

    def _start_tape(self):
        if self._tape_job is None and self._tape_enabled():
            self._tape_job = self.root.after(60, self._tape_tick)

    def _tape_tick(self):
        self._tape_job = None
        if not self._tape_enabled() or self._hidden:
            return
        if self._tape_width > 0:
            self._tape_offset = (self._tape_offset + 1.4) % self._tape_width
            self._draw_tape()
        self._tape_job = self.root.after(45, self._tape_tick)

    def _draw_tape(self):
        cv = self.tape
        cv.delete("all")
        self._tape_hits = []
        segs = self._tape_segs
        if not segs or self._tape_width <= 0 or self._tape_h <= 0:
            return
        font = self._tape_font
        width = max(self.tape.winfo_width(), 1)
        try:
            f = tkfont.Font(root=self.root, font=font)
        except Exception:
            return
        x = -self._tape_offset
        mid = self._tape_h / 2
        guard = 0
        # x 单调递增，各片段区间互不重叠，可以直接记录命中范围
        while x < width and guard < 500:
            for text, color, base in segs:
                if x > width:
                    break
                cv.create_text(x, mid, text=text, anchor="w", font=font, fill=color)
                w = f.measure(text)
                if base:
                    self._tape_hits.append((x, x + w, base))
                x += w
            guard += 1

    def _on_tape_press(self, event):
        if self._blocked():
            return "break"
        self._begin_press(event)

    def _on_tape_release(self, event):
        """滚动条上：拖动过就只移窗口，鼠标没动才算点击。

        单击 = 加入自选；**双击 = 直接进行情图表（不进自选）**。
        Tk 会立刻发 Button-1，所以单击要**推迟 260ms** 再执行——
        这期间如果来了 Double-Button-1，就把那次单击取消掉
        （见 `_on_tape_double`），所以双击不会顺手加一个。
        """
        if self._blocked():
            return "break"
        moved = self._drag_moved
        self._drag = None
        self._drag_moved = False
        if moved:
            self._schedule_save_position()
            return "break"
        self._cancel_tape_click()
        self._tape_click_job = self.root.after(
            260, lambda: self._tape_single_click(event.x))
        return "break"

    def _cancel_tape_click(self):
        job = getattr(self, "_tape_click_job", None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._tape_click_job = None

    def _tape_base_at(self, x):
        for x0, x1, base in getattr(self, "_tape_hits", []):
            if x0 <= x <= x1:
                return base
        return None

    def _tape_single_click(self, x):
        """单击：把币种加进自选，方便一路点过去扫。"""
        self._tape_click_job = None
        base = self._tape_base_at(x)
        if not base:
            return
        if self.add_symbol(base):
            log(f"滚动条单击加入自选: {base}")
        else:
            log(f"滚动条单击: {base} 已在自选中")

    def _on_tape_double(self, event):
        """双击：**直接切图表**（用户明确要求：不进自选，直接看行情图）。"""
        if self._blocked():
            return "break"
        self._cancel_tape_click()
        base = self._tape_base_at(event.x)
        if not base:
            return "break"
        log(f"滚动条双击切图表: {base}")
        self.open_tradingview(base, self.cfg.get("quote", "USDT"))
        return "break"

    def _sync_widgets(self, show_tape, show_input):
        """按开关显示/隐藏滚动条与输入框，只在状态变化时重排，避免每帧抖动。"""
        if show_tape != self._tape_packed:
            if show_tape:
                self.tape.pack(side="top", fill="x", before=self.canvas)
            else:
                self.tape.pack_forget()
            self._tape_packed = show_tape
        if show_input != self._inbar_packed:
            if show_input:
                self.inbar.pack(side="bottom", fill="x")
            else:
                self.inbar.pack_forget()
            self._inbar_packed = show_input

    # ------------------------------------------------------ 内联输入 --

    PLACEHOLDER = "输入币种，回车添加…"

    def _placeholder_on(self):
        return self.entry.get() == self.PLACEHOLDER

    def _show_placeholder(self):
        self.entry.delete(0, "end")
        self.entry.insert(0, self.PLACEHOLDER)
        try:
            self.entry.configure(fg=self._placeholder_fg or "#8e8e93")
        except Exception:
            pass

    def _on_entry_focus_in(self, _event=None):
        if self._placeholder_on():
            self.entry.delete(0, "end")
            try:
                self.entry.configure(fg=self._entry_fg or "#ffffff")
            except Exception:
                pass

    def _on_entry_focus_out(self, _event=None):
        if not self.entry.get().strip():
            self._show_placeholder()
        self.hint.configure(text="")
        # 点到候选窗也是合法操作，延迟一点再决定要不要收起
        self.root.after(220, self._maybe_hide_candidates)

    def _maybe_hide_candidates(self):
        """鼠标还在候选窗上就先别收，否则点击会被打断。"""
        try:
            win = self._cand_win
            if win is not None and win.winfo_exists() and win.winfo_viewable():
                px, py = self.root.winfo_pointerxy()
                cx, cy = win.winfo_x(), win.winfo_y()
                cw, ch = win.winfo_width(), win.winfo_height()
                if cx <= px <= cx + cw and cy <= py <= cy + ch:
                    return
        except Exception:
            pass
        self._hide_candidates()

    # ---------------------------------------------------- 候选列表 --

    CAND_MAX = 9

    def _candidate_hits(self):
        if self._placeholder_on():
            return []
        text = self.entry.get().strip()
        if not text:
            return []
        universe = getattr(self, "_symbol_universe", None) or FALLBACK_SYMBOLS
        return match_symbols(text, universe, limit=self.CAND_MAX)

    def _ensure_cand_window(self):
        """候选窗：独立无边框顶层窗口，悬在输入框正上方。

        刻意用**实心底板**而不是跟着主窗口透明——主窗口在纯文字模式下是全透明的，
        下拉框要是也透明就没法看了。
        """
        if self._cand_win is not None:
            try:
                if self._cand_win.winfo_exists():
                    return self._cand_win
            except Exception:
                pass
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.withdraw()
        wrap = tk.Frame(win, bg=PANEL_ACCENT, padx=1, pady=1)
        wrap.pack(fill="both", expand=True)
        lb = tk.Listbox(wrap, activestyle="none", highlightthickness=0, bd=0,
                        exportselection=False, height=1,
                        bg=PANEL_BG, fg=PANEL_FG,
                        selectbackground=PANEL_ACCENT, selectforeground="#000000")
        lb.pack(fill="both", expand=True)
        lb.bind("<Button-1>", self._on_cand_click)
        self._cand_win = win
        self._cand_wrap = wrap
        self._cand = lb
        return win

    def _style_cand_window(self):
        fsize = max(8, int(self.cfg.get("font_size", 9)) - 1)
        try:
            self._cand.configure(font=(self.ui, fsize))
        except Exception:
            pass

    def _refresh_candidates(self):
        hits = self._candidate_hits()
        self._cand_hits = hits
        if not hits:
            self._hide_candidates()
            return
        win = self._ensure_cand_window()
        self._style_cand_window()
        lb = self._cand
        lb.delete(0, "end")
        for idx, name in enumerate(hits, 1):
            lb.insert("end", f"{idx}  {name}")
        lb.configure(height=len(hits))
        self._cand_index = min(self._cand_index, len(hits) - 1)
        lb.selection_clear(0, "end")
        lb.selection_set(self._cand_index)
        lb.activate(self._cand_index)

        self.root.update_idletasks()
        # 用自己跟踪的位置和尺寸，别用 winfo_x/y —— 窗口还没被窗口管理器映射时
        # winfo 返回的是无意义默认值，候选窗会跑到屏幕左上角
        px, py = self._pos if self._pos else (self.root.winfo_x(), self.root.winfo_y())
        win_h = self._win_h or self.root.winfo_height()
        width = max(self._win_w or self.root.winfo_width(), 130)
        height = lb.winfo_reqheight()
        screen_h = self.root.winfo_screenheight()
        y = py + win_h - self._inbar_h - height
        if y < 0:
            # 窗口贴着屏幕顶边时上方放不下，就放到输入框下面
            # （以前直接 max(0, y) 硬夹，结果候选窗扣在行情上，很难看）
            y = py + win_h
            if y + height > screen_h:
                y = max(0, screen_h - height)
        win.geometry(f"{width}x{height}+{px}+{y}")
        win.deiconify()
        win.lift()

    def _hide_candidates(self):
        self._cand_hits = []
        self._cand_index = 0
        if self._cand_win is not None:
            try:
                self._cand_win.withdraw()
            except Exception:
                pass

    def _on_cand_click(self, event):
        idx = self._cand.nearest(event.y)
        if 0 <= idx < len(self._cand_hits):
            self._accept_candidate(idx)
        return "break"

    def _accept_candidate(self, idx):
        if not (0 <= idx < len(self._cand_hits)):
            return False
        name = self._cand_hits[idx]
        added = self.add_symbol(name)
        self.entry.delete(0, "end")
        self._hide_candidates()
        self.hint.configure(text=f"已加入 {name}" if added else f"{name} 已在自选中")
        try:
            self.entry.focus_set()
        except Exception:
            pass
        return True

    def _move_candidate(self, step):
        if not self._cand_hits:
            return
        self._cand_index = (self._cand_index + step) % len(self._cand_hits)
        try:
            self._cand.selection_clear(0, "end")
            self._cand.selection_set(self._cand_index)
            self._cand.activate(self._cand_index)
            self._cand.see(self._cand_index)
        except Exception:
            pass

    def _on_entry_keypress(self, event):
        """数字键选候选——但纯数字查询时数字照常输入，否则打不出 1000PEPE。

        注意 event.char 对方向键/回车等是空字符串，而 Python 里
        `'' in '123456789'` 是 True，必须显式判断非空。
        """
        char = event.char or ""
        if self._cand_hits and char and char in "123456789":
            query = self.entry.get().strip()
            if not query.isdigit():
                idx = int(char) - 1
                if idx < len(self._cand_hits):
                    self._accept_candidate(idx)
                    return "break"
        if self._cand_hits:
            if event.keysym == "Down":
                self._move_candidate(1)
                return "break"
            if event.keysym == "Up":
                self._move_candidate(-1)
                return "break"
            if event.keysym == "space":
                self._accept_candidate(self._cand_index)
                return "break"
        return None

    def _activate_window(self, _event=None):
        """把行情条激活成前台窗口。

        overrideredirect（无边框）窗口被点击时不会自动获得前台激活，
        键盘输入就送不到输入框——点了却打不出字。这里手动完成激活。
        """
        if self._blocked():
            return "break"
        if not ctypes:
            return
        try:
            self.root.focus_force()
        except Exception:
            pass
        try:
            u = ctypes.windll.user32
            k = ctypes.windll.kernel32
            hwnd = self._hwnd()
            if not hwnd:
                return
            fg = u.GetForegroundWindow()
            if fg == hwnd:
                return
            tid_fg = u.GetWindowThreadProcessId(fg, None)
            tid_me = k.GetCurrentThreadId()
            # AttachThreadInput 是绕过 Windows 前台锁的标准做法
            if tid_fg and tid_fg != tid_me:
                u.AttachThreadInput(tid_fg, tid_me, True)
                u.SetForegroundWindow(hwnd)
                u.AttachThreadInput(tid_fg, tid_me, False)
            else:
                u.SetForegroundWindow(hwnd)
            log("已激活窗口（准备接收键盘输入）")
        except Exception as exc:
            log(f"激活窗口失败: {exc}")

    def _on_entry_key(self, *_args):
        """内容变化回调（由 StringVar 的 trace 触发，兼容输入法/粘贴）。"""
        if self._placeholder_on():
            self.hint.configure(text="")
            self._hide_candidates()
            return
        text = self.entry.get().strip()
        self._cand_index = 0
        self._refresh_candidates()
        if not text:
            self.hint.configure(text="")
        elif self._cand_hits:
            self.hint.configure(text="↑↓ 选择 · 回车添加")
        else:
            self.hint.configure(text="无匹配")

    def _on_entry_tab(self, _event=None):
        """Tab 把当前高亮的候选填进输入框。"""
        hits = self._candidate_hits()
        if hits:
            idx = min(self._cand_index, len(hits) - 1)
            self.entry.delete(0, "end")
            self.entry.insert(0, hits[idx])
            self._on_entry_key()
        return "break"

    def _on_entry_escape(self, _event=None):
        self.entry.delete(0, "end")
        self._show_placeholder()
        self.hint.configure(text="")
        self._hide_candidates()
        self.root.focus_set()
        return "break"              # 别让 Esc 冒泡到根窗口去退出程序

    def _on_entry_submit(self, _event=None):
        if self._placeholder_on():
            return "break"
        # 有候选时优先用高亮的那一个
        if self._cand_hits:
            self._accept_candidate(self._cand_index)
            return "break"
        text = self.entry.get().strip()
        if not text:
            return "break"
        names = [p for p in text.replace(" ", "").split(",") if p]
        added = 0
        for name in names:
            if self.add_symbol(name):
                added += 1
        self.entry.delete(0, "end")
        self._hide_candidates()
        if added:
            self.hint.configure(text=f"已加入 {added} 个")
        else:
            self._show_placeholder()
            self.hint.configure(text="已在自选中")
        return "break"

    def add_symbol(self, name):
        """把一个币种加进自选并立即生效。

        **可以从任意线程调**：配置改动当场生效（返回值也就可信），
        但重画窗口必须丢回主线程——HTTP 线程直接碰 Tk 会
        `RuntimeError: main thread is not in main loop`（图表页侧栏加自选就走这条路）。
        """
        item = normalize_symbol(name, self.cfg.get("quote", "USDT"))
        if not item:
            return False
        base, quote = item
        label = base if quote == self.cfg.get("quote", "USDT") else f"{base}-{quote}"
        existing = [str(s).upper() for s in self.cfg.get("symbols", [])]
        if label.upper() in existing:
            log(f"{label} 已在自选中")
            return False
        self.cfg.setdefault("symbols", []).append(label)
        save_config(self.cfg)
        self.pairs = build_pairs(self.cfg["symbols"], self.cfg.get("quote", "USDT"))
        self.rows = {}
        self._price_width = 0
        self._mapped_pos = None
        self._tape_dirty = True
        self._ui_call(self._after_symbols_changed)
        log(f"已加入自选: {label}")
        return True

    def _after_symbols_changed(self):
        """主线程里重画行情窗并立刻抓一次价格。"""
        self.render()
        self.force_refresh()

    def _ui_call(self, fn):
        """把一个回调丢回主线程执行（`_pump` 里消费）。

        已经站在主线程时就直接跑——避免多等一个 250ms 的消息泵周期，
        那会让本地点击明显发顿。
        """
        try:
            if threading.current_thread() is threading.main_thread():
                fn()
                return
        except Exception as exc:
            log(f"主线程直调失败: {exc}")
            return
        self._queue.put(("call", fn))

    # ---------------------------------------------------------- 菜单 --

    def _build_menu(self):
        self.var_top = tk.BooleanVar(value=bool(self.cfg.get("always_on_top", True)))
        self.var_chg = tk.BooleanVar(value=bool(self.cfg.get("show_change", True)))
        self.var_style = tk.StringVar(value=str(self.cfg.get("style", "card")))
        self.var_scheme = tk.StringVar(value=str(self.cfg.get("scheme", "west")))
        self.var_head = tk.BooleanVar(value=bool(self.cfg.get("show_header", False)))
        self.var_click = tk.BooleanVar(value=bool(self.cfg.get("click_through", False)))
        self.var_font = tk.StringVar(value=str(self.cfg.get("font_family", "")))
        self.var_effect = tk.StringVar(value=str(self.cfg.get("text_effect", "outline")))
        self.var_color = tk.StringVar(value=str(self.cfg.get("text_color", "black")))
        self.var_market = tk.StringVar(value=str(self.cfg.get("market", "perp")))
        self.var_colored = tk.BooleanVar(value=bool(self.cfg.get("change_colored", False)))
        self.var_tape = tk.BooleanVar(value=bool(self.cfg.get("show_tape", True)))
        self.var_input = tk.BooleanVar(value=bool(self.cfg.get("show_input", True)))
        self.var_capfilter = tk.IntVar(value=int(self.cfg.get("market_cap_filter", 20)))
        self.var_dblclick = tk.BooleanVar(value=bool(self.cfg.get("dblclick_chart", True)))
        self.var_oi = tk.BooleanVar(value=bool(self.cfg.get("show_oi", True)))
        self.var_del = tk.BooleanVar(value=bool(self.cfg.get("show_del", False)))
        self.var_alert = tk.BooleanVar(value=bool(self.cfg.get("show_alert", True)))
        self.var_levels = tk.BooleanVar(value=bool(self.cfg.get("show_levels", True)))
        self.var_game = tk.BooleanVar(value=bool(getattr(self, "_game_mode", False)))

        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="立即刷新", command=self.force_refresh)
        m.add_separator()
        m.add_checkbutton(label="窗口置顶", variable=self.var_top, command=self._toggle_top)
        m.add_checkbutton(label="显示涨跌幅", variable=self.var_chg, command=self._toggle_change)
        m.add_checkbutton(label="显示表头", variable=self.var_head,
                          command=self._toggle_header)
        # 游戏模式：锁住鼠标防误触。组合键会在热键注册成功后补进 label
        m.add_checkbutton(label="游戏模式（锁鼠标）", variable=self.var_game,
                          command=self.toggle_game_mode)
        self._mi_game_idx = m.index("end")
        m.add_checkbutton(label="鼠标穿透", variable=self.var_click,
                          command=self._toggle_click_through)
        m.add_checkbutton(label="顶部滚动条", variable=self.var_tape,
                          command=self._toggle_tape)
        m.add_checkbutton(label="底部输入框", variable=self.var_input,
                          command=self._toggle_input)
        m.add_checkbutton(label="双击行打开图表", variable=self.var_dblclick,
                          command=self._toggle_dblclick)
        m.add_checkbutton(label="持仓变化榜", variable=self.var_oi,
                          command=self._toggle_oi)
        m.add_checkbutton(label="显示删除按钮（行尾 ×）", variable=self.var_del,
                          command=self._toggle_del)
        m.add_checkbutton(label="显示提醒按钮（行尾🔔）", variable=self.var_alert,
                          command=self._toggle_alert)
        m.add_command(label="价格提醒设置…", command=self.open_alert_settings)
        m.add_command(label="测试提醒（弹窗+邮件）", command=self.test_alert)

        # 仓位 / 关注价位：行内标记 + 一键清空
        level_menu = tk.Menu(m, tearoff=0)
        level_menu.add_checkbutton(label="显示仓位标记（品种名后）",
                                   variable=self.var_levels,
                                   command=self._toggle_levels)
        level_menu.add_command(label="清空全部标记", command=self.clear_all_levels)
        m.add_cascade(label="仓位 / 关注价位", menu=level_menu)

        cap_menu = tk.Menu(m, tearoff=0)
        for label, value in (("不剔除", 0), ("剔除市值前 10", 10),
                             ("剔除市值前 20", 20), ("剔除市值前 30", 30)):
            cap_menu.add_radiobutton(label=label, variable=self.var_capfilter,
                                     value=value, command=self._toggle_capfilter)
        m.add_cascade(label="成交量榜", menu=cap_menu)
        m.add_separator()

        style_menu = tk.Menu(m, tearoff=0)
        style_menu.add_radiobutton(label="纯文字悬浮（背景全透明）", variable=self.var_style,
                                   value="float", command=self._toggle_style)
        style_menu.add_radiobutton(label="毛玻璃（透明度 + 背景模糊）", variable=self.var_style,
                                   value="blur", command=self._toggle_style)
        style_menu.add_radiobutton(label="纯色卡片", variable=self.var_style, value="card",
                                   command=self._toggle_style)
        m.add_cascade(label="外观样式", menu=style_menu)

        market_menu = tk.Menu(m, tearoff=0)
        market_menu.add_radiobutton(label="U 本位永续合约", variable=self.var_market,
                                    value="perp", command=self._toggle_market)
        market_menu.add_radiobutton(label="现货", variable=self.var_market,
                                    value="spot", command=self._toggle_market)
        m.add_cascade(label="市场类型", menu=market_menu)

        scheme_menu = tk.Menu(m, tearoff=0)
        scheme_menu.add_radiobutton(label="绿涨红跌", variable=self.var_scheme, value="west",
                                    command=self._toggle_scheme)
        scheme_menu.add_radiobutton(label="红涨绿跌", variable=self.var_scheme, value="cn",
                                    command=self._toggle_scheme)
        m.add_cascade(label="涨跌配色", menu=scheme_menu)

        color_menu = tk.Menu(m, tearoff=0)
        color_menu.add_radiobutton(label="纯黑", variable=self.var_color, value="black",
                                   command=self._toggle_text_color)
        color_menu.add_radiobutton(label="白色", variable=self.var_color, value="white",
                                   command=self._toggle_text_color)
        m.add_cascade(label="文字颜色", menu=color_menu)
        m.add_checkbutton(label="涨跌幅用红绿着色", variable=self.var_colored,
                          command=self._toggle_colored)

        # 不透明度 / 字号全部放在菜单里，不再单开一个浮动面板
        # （那个面板和菜单功能重复，位置还飘，用起来别扭）
        opacity_menu = tk.Menu(m, tearoff=0)
        for pct in OPACITY_STEPS:
            opacity_menu.add_command(
                label=f"{pct}%",
                command=lambda p=pct: self.set_alpha(p / 100))
        opacity_menu.add_separator()
        opacity_menu.add_command(label="更不透明（滚轮↑）",
                                 command=lambda: self.set_alpha(
                                     float(self.cfg.get("alpha", 1.0)) + 0.05))
        opacity_menu.add_command(label="更透明（滚轮↓）",
                                 command=lambda: self.set_alpha(
                                     float(self.cfg.get("alpha", 1.0)) - 0.05))
        m.add_cascade(label="不透明度", menu=opacity_menu)

        size_menu = tk.Menu(m, tearoff=0)
        size_menu.add_command(label="放大（Ctrl+滚轮↑）",
                              command=lambda: self.set_font_size(
                                  int(self.cfg.get("font_size", 9)) + 1))
        size_menu.add_command(label="缩小（Ctrl+滚轮↓）",
                              command=lambda: self.set_font_size(
                                  int(self.cfg.get("font_size", 9)) - 1))
        size_menu.add_separator()
        for preset in FONT_SIZE_STEPS:
            size_menu.add_command(label=f"设为 {preset}",
                                  command=lambda p=preset: self.set_font_size(p))
        m.add_cascade(label="字号", menu=size_menu)

        font_menu = tk.Menu(m, tearoff=0)
        installed = set(tkfont.families(self.root))
        for label, family in FONT_PRESETS:
            if family not in installed:
                continue
            font_menu.add_radiobutton(label=label, variable=self.var_font, value=family,
                                      command=self._toggle_font)
        m.add_cascade(label="字体", menu=font_menu)

        effect_menu = tk.Menu(m, tearoff=0)
        for label, value in TEXT_EFFECTS:
            effect_menu.add_radiobutton(label=label, variable=self.var_effect, value=value,
                                        command=self._toggle_effect)
        m.add_cascade(label="文字效果", menu=effect_menu)

        m.add_separator()
        m.add_command(label="选择品种…", command=self.open_symbols)
        m.add_command(label="全品种扫盘（全市场 · ↑↓ 切）…", command=self.open_scan)
        m.add_command(label="打开 TradingView", command=lambda: self.open_tradingview())
        m.add_command(label=f"隐藏窗口（{HOTKEY_DEFS['toggle'][0][0]}）",
                      command=self.toggle_visible)
        self._mi_hide_idx = m.index("end")
        m.add_command(label="重新加载配置", command=self.reload_config)
        m.add_command(label="打开配置文件", command=self.open_config)

        # 热键放进二级菜单，避免长文案把主菜单撑宽
        hk_menu = tk.Menu(m, tearoff=0)
        for key in ("toggle", "menu", "symbols", "click", "game"):
            hk_menu.add_command(label=f"{HOTKEY_NAMES.get(key, key)}", state="disabled")
        m.add_cascade(label="热键", menu=hk_menu)
        self._hk_menu = hk_menu

        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        # ★ 菜单瘦身（v0.18）：上面这一大堆明细项**不再挂到右键菜单**上 ——
        #   用户原话「右键菜单有点太多了……太土了而且功能也不好找」。
        #   明细全部搬进「设置中心」按分类放好，右键只留几条最常用的。
        #   注意：上面那批 var_* 变量照旧建好（设置中心直接复用它们）。
        self.menu = self._build_slim_menu()

    def _build_slim_menu(self):
        """右键菜单：只留最常用的几条，明细都在「设置中心」里。"""
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="⚙  设置…（全部开关）", command=self.open_settings)
        m.add_command(label="立即刷新", command=self.force_refresh)
        m.add_separator()
        m.add_checkbutton(label="游戏模式（锁鼠标）", variable=self.var_game,
                          command=self.toggle_game_mode)
        self._mi_game_idx = m.index("end")
        m.add_command(label="鼠标穿透", command=self._toggle_click_through)
        m.add_separator()
        m.add_command(label="全品种扫盘（全市场 · ↑↓ 切）…", command=self.open_scan)
        m.add_command(label="选择品种…", command=self.open_symbols)
        m.add_separator()
        m.add_command(label=f"隐藏窗口（{HOTKEY_DEFS['toggle'][0][0]}）",
                      command=self.toggle_visible)
        self._mi_hide_idx = m.index("end")
        hk_menu = tk.Menu(m, tearoff=0)
        for key in ("toggle", "menu", "symbols", "click", "game", "scan"):
            hk_menu.add_command(label=f"{HOTKEY_NAMES.get(key, key)}", state="disabled")
        m.add_cascade(label="热键", menu=hk_menu)
        self._hk_menu = hk_menu
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        # 真实生效的组合键立刻补进新菜单（热键线程可能早就上报过了）
        if getattr(self, "_hotkey_labels", None):
            self._update_hotkey_hint(self._hotkey_labels)
        return m

    def _refresh_menu_vars(self):
        self.var_top.set(bool(self.cfg.get("always_on_top", True)))
        self.var_chg.set(bool(self.cfg.get("show_change", True)))
        self.var_style.set(str(self.cfg.get("style", "card")))
        self.var_scheme.set(str(self.cfg.get("scheme", "west")))
        self.var_head.set(bool(self.cfg.get("show_header", False)))
        self.var_click.set(bool(self.cfg.get("click_through", False)))
        self.var_font.set(str(self.cfg.get("font_family", self.family)))
        self.var_effect.set(str(self.cfg.get("text_effect", "outline")))
        self.var_color.set(str(self.cfg.get("text_color", "black")))
        self.var_market.set(str(self.cfg.get("market", "perp")))
        self.var_colored.set(bool(self.cfg.get("change_colored", False)))
        if hasattr(self, "var_levels"):
            self.var_levels.set(bool(self.cfg.get("show_levels", True)))
        if hasattr(self, "var_game"):
            self.var_game.set(bool(getattr(self, "_game_mode", False)))

    def popup_menu_at_cursor(self):
        """供全局热键调用：在鼠标位置弹出菜单。"""
        self._refresh_menu_vars()
        try:
            x, y = self.root.winfo_pointerxy()
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def _on_menu(self, event):
        if self._blocked():
            return "break"
        self._refresh_menu_vars()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    # ------------------------------------------------------ 设置动作 --

    def set_alpha(self, value):
        value = max(0.2, min(1.0, round(float(value), 2)))
        self.cfg["alpha"] = value
        try:
            self.root.attributes("-alpha", value)
        except Exception:
            pass
        save_config(self.cfg)

    def set_font_size(self, value):
        value = max(8, min(28, int(value)))
        self.cfg["font_size"] = value
        self._price_width = 0
        self.render()
        save_config(self.cfg)

    def _toggle_top(self):
        self.cfg["always_on_top"] = bool(self.var_top.get())
        self.root.attributes("-topmost", self.cfg["always_on_top"])
        save_config(self.cfg)

    def _toggle_change(self):
        self.cfg["show_change"] = bool(self.var_chg.get())
        self.render()
        save_config(self.cfg)

    def _toggle_header(self):
        self.cfg["show_header"] = bool(self.var_head.get())
        self.render()
        save_config(self.cfg)

    def _toggle_click_through(self):
        self.toggle_click_through(self.var_click.get())

    def _toggle_tape(self):
        self.cfg["show_tape"] = bool(self.var_tape.get())
        save_config(self.cfg)
        self._mapped_pos = None
        if self.cfg["show_tape"]:
            self._tape_dirty = True
        self.render()
        self._start_tape()

    def _toggle_input(self):
        self.cfg["show_input"] = bool(self.var_input.get())
        save_config(self.cfg)
        self._mapped_pos = None
        self.render()
        if self.cfg["show_input"]:
            try:
                self.entry.focus_set()
            except Exception:
                pass

    def _toggle_dblclick(self):
        self.cfg["dblclick_chart"] = bool(self.var_dblclick.get())
        save_config(self.cfg)
        log(f"双击打开图表: {'开' if self.cfg['dblclick_chart'] else '关'}")

    def _toggle_oi(self):
        self.cfg["show_oi"] = bool(self.var_oi.get())
        save_config(self.cfg)
        self._tape_dirty = True
        self.render()
        if self.cfg["show_oi"] and not (self._market_overview or {}).get("topOI"):
            self._start_oi_refresh()        # 刚打开就立刻抓一次
        log(f"持仓变化榜: {'开' if self.cfg['show_oi'] else '关'}")

    def _toggle_capfilter(self):
        self.cfg["market_cap_filter"] = int(self.var_capfilter.get())
        save_config(self.cfg)
        self.refresh_rankings_now()

    def _toggle_del(self):
        """显示/隐藏每行末尾的删除小 ×。

        默认不开——纯文字模式下窗口很窄，一列图标会显得乱。
        **单击直接删**（用户明确要求不用防误触）。
        """
        self.cfg["show_del"] = bool(self.var_del.get())
        save_config(self.cfg)
        self._mapped_pos = None
        self.render()
        log(f"删除按钮: {'开' if self.cfg['show_del'] else '关'}")

    def _toggle_alert(self):
        """显示/隐藏每行的闹铃图标（默认开）。单击打开提醒设置。"""
        self.cfg["show_alert"] = bool(self.var_alert.get())
        save_config(self.cfg)
        self._mapped_pos = None
        self.render()
        log(f"提醒按钮: {'开' if self.cfg['show_alert'] else '关'}")

    # ------------------------------------------- 仓位 / 关注价位标记 --

    def level_of(self, base):
        """取某个品种的标记，返回 (side, price, color, text)，没有就 None。

        side 三选一：
          * `long`  做多 → **红**（用户明确要求，不跟随涨跌配色翻转）
          * `short` 做空 → **绿**
          * `watch` 仅关注 → 琥珀
        """
        levels = self.cfg.get("levels") or {}
        item = levels.get(str(base).upper())
        if not isinstance(item, dict):
            return None
        try:
            price = float(item.get("price"))
        except (TypeError, ValueError):
            return None
        side = str(item.get("side") or "watch").lower()
        if side not in ("long", "short", "watch"):
            side = "watch"
        color = {"long": LEVEL_LONG, "short": LEVEL_SHORT}.get(side, LEVEL_WATCH)
        text = {"long": "多", "short": "空"}.get(side, "看") + fmt_level(price)
        return side, price, color, text

    def set_level(self, base, side, price):
        """写入一个标记：立即重画 + 落盘。"""
        base = str(base).upper()
        levels = dict(self.cfg.get("levels") or {})
        levels[base] = {"side": str(side), "price": float(price)}
        self.cfg["levels"] = levels
        save_config(self.cfg)
        self._mapped_pos = None
        self.render()
        log(f"仓位标记: {base} {side} {price}")

    def clear_level(self, base):
        base = str(base).upper()
        levels = dict(self.cfg.get("levels") or {})
        if base not in levels:
            return False
        levels.pop(base, None)
        self.cfg["levels"] = levels
        save_config(self.cfg)
        self._mapped_pos = None
        self.render()
        log(f"仓位标记已清除: {base}")
        return True

    def clear_all_levels(self):
        levels = self.cfg.get("levels") or {}
        if not levels:
            return
        n = len(levels)
        self.cfg["levels"] = {}
        save_config(self.cfg)
        self._mapped_pos = None
        self.render()
        log(f"仓位标记已全部清空（{n} 个）")

    def _toggle_levels(self):
        self.cfg["show_levels"] = bool(self.var_levels.get())
        save_config(self.cfg)
        self._mapped_pos = None
        self.render()
        log(f"仓位标记列: {'开' if self.cfg['show_levels'] else '关'}")

    def _level_at(self, x, y):
        """命中品种名后面那个小按钮／标记？返回 (base, quote) 或 None。"""
        for top, bottom, base, quote, x0, x1 in getattr(self, "_level_geom", []):
            if top <= y < bottom and x0 <= x <= x1:
                return base, quote
        return None

    def open_level(self, base, quote=None):
        """设置某个品种的仓位 / 关注价位（点品种名后的小按钮进来）。

        就三件事：填价位、选方向（做多红 / 做空绿 / 仅关注琥珀）、保存。
        已经设过的会带出原值，还能一键删掉。
        """
        base = str(base).upper()
        quote = quote or self.cfg.get("quote", "USDT")
        cur = self.level_of(base)

        old = getattr(self, "_level_win", None)
        if old is not None:
            try:
                if old.winfo_exists():
                    old.destroy()               # 换一个品种就直接换内容，不叠窗
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        self._level_win = win
        win.title(f"{base} 仓位 / 关注价位")
        win.resizable(False, False)
        win.configure(bg=PANEL_BG)
        win.attributes("-topmost", True)
        w, hgt = 306, 196
        est_h = hgt + 56
        px = max(0, min(self._pos[0] - w - 20, self.root.winfo_screenwidth() - w - 10))
        py = max(0, min(self._pos[1], self.root.winfo_screenheight() - est_h))
        win.geometry(f"{w}x{hgt}+{px}+{py}")

        def lbl(parent, text, **kw):
            kw.setdefault("bg", PANEL_BG)
            kw.setdefault("fg", PANEL_FG)
            kw.setdefault("font", (self.ui, 9))
            return tk.Label(parent, text=text, **kw)

        item = self.rows.get((base, quote)) or {}
        live = item.get("price")
        head = f"{base}    现价 {fmt_price(live)}" if live else base
        lbl(win, head, anchor="w", font=(self.ui, 10, "bold")).pack(
            fill="x", padx=14, pady=(12, 0))

        def plain(value):
            """输入框里不要千分位逗号，用户改了还容易看错。"""
            return fmt_price(value).replace(",", "")

        preset = plain(cur[1]) if cur else (plain(live) if live else "")
        row1 = tk.Frame(win, bg=PANEL_BG)
        row1.pack(fill="x", padx=14, pady=(10, 0))
        lbl(row1, "价位").pack(side="left")
        var_price = tk.StringVar(value=preset)
        ent = tk.Entry(row1, textvariable=var_price, width=14, relief="flat",
                       bg="#2c2c2e", fg=PANEL_FG, insertbackground=PANEL_FG,
                       font=(self.ui, 10))
        ent.pack(side="left", padx=6, ipady=2)

        def use_live():
            if live:
                var_price.set(plain(live))
        tk.Button(row1, text="现价", command=use_live, relief="flat", bd=0,
                  bg="#3a3a3c", fg=PANEL_FG, activebackground=PANEL_ACCENT,
                  activeforeground="#000000", font=(self.ui, 8),
                  width=4).pack(side="left")

        row2 = tk.Frame(win, bg=PANEL_BG)
        row2.pack(fill="x", padx=14, pady=(10, 0))
        lbl(row2, "方向").pack(side="left")
        var_side = tk.StringVar(value=(cur[0] if cur else "long"))
        for text, value, color in (("做多", "long", LEVEL_LONG),
                                   ("做空", "short", LEVEL_SHORT),
                                   ("仅关注", "watch", LEVEL_WATCH)):
            tk.Radiobutton(row2, text=text, value=value, variable=var_side,
                           bg=PANEL_BG, fg=color, selectcolor=PANEL_BG,
                           activebackground=PANEL_BG, activeforeground=color,
                           font=(self.ui, 9), highlightthickness=0).pack(side="left")

        msg = lbl(win, "", anchor="w", fg=PANEL_DIM, font=(self.ui, 8))
        msg.pack(fill="x", padx=14, pady=(8, 0))

        def close():
            self._level_win = None
            try:
                win.destroy()
            except Exception:
                pass

        def do_save():
            raw = var_price.get().strip().replace(",", "").replace("，", "")
            try:
                price = float(raw)
            except ValueError:
                msg.configure(text="价位要填数字，例如 82500 或 0.1407", fg="#f6465d")
                return
            if price <= 0:
                msg.configure(text="价位要大于 0", fg="#f6465d")
                return
            self.set_level(base, var_side.get(), price)
            close()

        def do_clear():
            self.clear_level(base)
            close()

        foot = tk.Frame(win, bg=PANEL_BG)
        foot.pack(fill="x", padx=14, pady=(10, 12))
        tk.Button(foot, text="保存", command=do_save, relief="flat", bd=0,
                  bg=PANEL_ACCENT, fg="#000000", font=(self.ui, 9),
                  width=7).pack(side="right")
        tk.Button(foot, text="取消", command=close, relief="flat", bd=0,
                  bg="#3a3a3c", fg=PANEL_FG, font=(self.ui, 9),
                  width=6).pack(side="right", padx=(0, 6))
        if cur:
            tk.Button(foot, text="删除标记", command=do_clear, relief="flat", bd=0,
                      bg="#3a3a3c", fg="#f6465d", font=(self.ui, 9),
                      width=8).pack(side="left")

        win.protocol("WM_DELETE_WINDOW", close)
        win.bind("<Escape>", lambda _e: close())
        ent.bind("<Return>", lambda _e: do_save())
        ent.focus_set()

    # ---------------------------------------------------- 游戏模式 --

    def toggle_game_mode(self, value=None):
        """游戏模式：锁住鼠标，防误触。

        打开后：
          * 行情条不再响应任何鼠标事件（拖拽/单击/双击/滚轮/闹铃/垃圾桶全屏蔽）
          * 顺手打开鼠标穿透，让点击**落到游戏里**，而不是被行情条吃掉
          * 输入栏右边亮一个 🔒 指示，提醒你为什么点不动
        退出：再按一次热键，或从右键菜单把这一项点掉。

        ⚠️ 只存在内存里、**不落盘**。重启必定回到正常状态 ——
        免得哪天忘了自己开过、鼠标怎么点都没反应，还以为程序坏了。
        """
        self._game_mode = (not getattr(self, "_game_mode", False)) if value is None \
            else bool(value)
        if hasattr(self, "var_game"):
            try:
                self.var_game.set(self._game_mode)
            except Exception:
                pass
        self.apply_click_through()            # 游戏模式优先于「鼠标穿透」开关
        self._update_game_badge()
        combo = (getattr(self, "_hotkey_labels", {}) or {}).get("game") or "热键"
        log("游戏模式: " + (f"开（鼠标已锁，{combo} 解锁）" if self._game_mode else "关"))

    def _update_game_badge(self):
        label = getattr(self, "game_label", None)
        if label is None:
            return
        try:
            if getattr(self, "_game_mode", False):
                label.configure(text="🔒 游戏模式")
                if not label.winfo_ismapped():
                    label.pack(side="left", padx=(6, 0))     # 只在有字时占位
            else:
                label.configure(text="")
                if label.winfo_ismapped():
                    label.pack_forget()
        except Exception:
            pass

    def _blocked(self):
        """游戏模式里，鼠标事件一律不处理（热键与右键菜单仍然可用）。"""
        return bool(getattr(self, "_game_mode", False))

    def refresh_rankings_now(self):
        """改了市值过滤后，立刻在后台重算榜单。"""
        limit = int(self.cfg.get("market_cap_filter", 20))

        def work():
            try:
                big = fetch_big_caps(limit, 15) if limit > 0 else []
            except Exception as exc:
                log(f"市值榜抓取失败，用兜底: {exc}")
                big = FALLBACK_BIG_CAPS[:limit] if limit > 0 else []
            overview = dict(self._market_overview or {})
            overview["bigCaps"] = list(big)
            universe = getattr(self, "_symbol_universe", None) or []
            try:
                if universe:
                    fresh = fetch_rankings(universe, big, timeout=15)
                    for key in ("topVolume", "topGainers", "topLosers"):
                        overview[key] = fresh.get(key) or []
                self._market_overview = overview
                self._tape_dirty = True
                self._queue.put(("render", None))
                log(f"榜单已重算，剔除市值前 {limit}：{big[:5]}")
            except Exception as exc:
                log(f"重算榜单失败: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _toggle_font(self):
        self.cfg["font_family"] = self.var_font.get()
        self.family = resolve_font(self.root, self.cfg["font_family"])
        self._fonts.clear()
        self._price_width = 0
        self.render()
        save_config(self.cfg)

    def _toggle_effect(self):
        self.cfg["text_effect"] = self.var_effect.get()
        self.render()
        save_config(self.cfg)

    def _toggle_text_color(self):
        self.cfg["text_color"] = self.var_color.get()
        self.render()
        save_config(self.cfg)

    def _toggle_colored(self):
        self.cfg["change_colored"] = bool(self.var_colored.get())
        self.render()
        save_config(self.cfg)

    def _toggle_style(self):
        self.cfg["style"] = self.var_style.get()
        self._apply_style_attrs()
        self._mapped_pos = None          # 强制重设一次几何，让圆角区域重新生效
        self.render()
        save_config(self.cfg)

    def _toggle_market(self):
        self.cfg["market"] = self.var_market.get()
        self.rows = {}
        self._price_width = 0
        self.render()
        self.force_refresh()
        save_config(self.cfg)

    def _row_at(self, y):
        """按窗口内 y 坐标找命中的币种行，返回 (base, quote) 或 None。"""
        for top, bottom, base, quote in getattr(self, "_row_geom", []):
            if top <= y < bottom:
                return base, quote
        return None

    def _row_trash_at(self, x, y):
        """命中行尾的哪个图标？返回 (base, quote, kind)，kind = 'bell' | 'del'。

        闹铃和垃圾桶都是**单击**生效（用户明确要求不用防误触）：
        垃圾桶点了直接删，闹铃点了直接开设置弹窗（弹窗里可以改/删）。
        """
        for top, bottom, base, quote, x0, x1, kind in getattr(self, "_icon_geom", []):
            if top <= y < bottom and x0 <= x <= x1:
                return base, quote, kind
        return None

    def _is_chart_target(self, base, quote):
        tgt = getattr(self, "_chart_target", None) or ("", "")
        return str(tgt[0]).upper() == str(base).upper() and str(tgt[1]).upper() == str(quote).upper()

    def _on_icon_click(self, base, quote, kind):
        """行尾图标被单击。

        用户明确要求：**不需要防误触**。
          * `del` → 直接删掉这个品种
          * `bell` → 直接打开提醒设置弹窗（在里面可以改、可以删）
        """
        if kind == "del":
            self.remove_symbol(base, quote)
        else:
            self.open_alerts(base, quote)

    def remove_symbol(self, base, quote=None):
        """把某个品种从自选里删掉（写配置并立即生效），返回是否真的删了。

        删掉之后窗口必须重画——行位、价格列宽都会变。
        """
        quote = quote or self.cfg.get("quote", "USDT")
        target = f"{base}".upper()
        alias = f"{base}-{quote}".upper()
        before = [str(s) for s in self.cfg.get("symbols", [])]
        after = [s for s in before
                 if str(s).upper() not in (target, alias)]
        if len(after) == len(before):
            log(f"删除失败：{base} 不在自选里")
            return False

        self.cfg["symbols"] = after
        save_config(self.cfg)
        self.pairs = build_pairs(self.cfg.get("symbols", []),
                                 self.cfg.get("quote", "USDT"))
        # 清掉这一行的行情，否则删完还会残留一帧旧价格
        self.rows.pop((base, quote), None)
        self._flash.pop((base, quote), None)
        self._mapped_pos = None
        self._tape_dirty = True

        # 如果删的正好是图表页当前品种，往前挪一个，别让图表停在已删的币上
        remaining = self.pairs
        if remaining and (self._is_chart_target(base, quote) or
                          not self._is_chart_in_pairs()):
            cur = 0
            for i, (b, _q) in enumerate(remaining):
                if str(b).upper() == target:
                    cur = i
                    break
            nxt = remaining[min(cur, len(remaining) - 1)]
            self.set_chart_symbol(nxt[0], nxt[1], activate=False)
            log(f"{base} 曾是当前图表品种，自动切到 {nxt[0]}")

        # 重画必须回主线程（可能从 HTTP 线程调进来）
        self._ui_call(self._after_symbols_changed)
        log(f"已从自选删除: {base}（剩余 {len(after)} 个）")
        return True

    def _is_chart_in_pairs(self):
        """图表页当前品种还在自选里吗？"""
        tgt = getattr(self, "_chart_target", None)
        if not tgt:
            return False
        for b, q in self.pairs:
            if self._is_chart_target(b, q):
                return True
        return False

    def set_chart_symbol(self, base, quote=None, activate=True):
        """只改图表页当前品种，不重开浏览器。

        和 `open_tradingview` 的区别：这个是给侧边栏点选用的——
        用户要的是"在已经开着的图表页里一个一个扫过去"，
        不应该每次都去摸浏览器窗口、抢焦点。
        """
        quote = quote or self.cfg.get("quote", "USDT")
        self._chart_target = (base, quote)
        if not activate:
            return
        # 注意：必须先读旧时间戳再判断。页面开着就只换数据，不碰浏览器。
        page_open = (time.time() - getattr(self, "_chart_poll_at", 0.0)) < 6.0
        if page_open:
            log(f"图表侧栏切品种 -> {base}")
        else:
            self.open_tradingview(base, quote)

    # ------------------------------------------------------ 图表页 --

    def chart_symbol(self):
        """给图表页轮询用。

        只回标识和名字，**不做任何网络请求**——图表已经改成用
        lightweight-charts 画币安的 K 线，不需要再问 TradingView 要符号了。
        之前在这里查拼音，导致每次切品种页面都要卡 1.5 秒。
        """
        base, quote = self._chart_target
        return {"key": f"{base}|{quote}", "name": base,
                "base": base, "quote": quote,
                # 让页面知道该显示哪一张：行情图表 / 全品种扫盘。
                # 这样"点一下全品种扫盘"是把**已经开着的那个页面**切过去，
                # 而不是每点一次多开一个标签页。
                "scan": bool(getattr(self, "_want_scan", False)),
                # 页面靠它原地切主题（不用刷新）
                "theme": getattr(self, "theme", "night")}

    def tradingview_link(self):
        """按需解析 TradingView 图表地址（结果缓存）。

        中文名合约在 TradingView 上是拼音代码，要搜一次才知道；
        但这只在用户真的点「在 TradingView 打开」时才需要，不该拖慢轮询。
        """
        base, quote = self._chart_target
        market = self.cfg.get("market", "perp")
        exchange = self.cfg.get("tv_exchange", "BINANCE")
        key = f"{base}|{quote}|{exchange}"
        if key not in self._tv_symbols:
            self._tv_symbols[key] = tradingview_resolve(
                base, quote, market, exchange) or ""
        symbol = self._tv_symbols[key]
        if symbol:
            return ("https://www.tradingview.com/chart/?symbol="
                    + urllib.parse.quote(symbol))
        # TradingView 真没有 -> 币安自己的合约页（中文要百分号编码）
        return binance_chart_url(base, quote)

    def note_chart_poll(self):
        self._chart_poll_at = time.time()
        # 页面开着的时候顺带做两件事：榜单没数据就催一次，别让侧边栏空着
        self._chart_seen = getattr(self, "_chart_seen", 0) + 1
        if self._chart_seen % 15 == 1:
            self._warm_rankings_for_chart()

    def _warm_rankings_for_chart(self):
        """图表页侧边栏要用榜单数据，但没有就催一次（幂等，别重复起线程）。"""
        ov = self._market_overview or {}
        if ov.get("topGainers") or ov.get("topVolume"):
            return
        if getattr(self, "_rank_warming", False):
            return
        self._rank_warming = True

        def work():
            try:
                universe = getattr(self, "_symbol_universe", None)
                if not universe:
                    universe = load_symbol_universe() or FALLBACK_SYMBOLS
                    self._symbol_universe = universe
                overview = self._market_overview or {}
                fresh = fetch_rankings(universe, overview.get("bigCaps") or [],
                                       timeout=15)
                if fresh.get("symbols"):
                    merged = dict(self._market_overview or {})
                    for key in ("topVolume", "topGainers", "topLosers"):
                        merged[key] = fresh.get(key) or []
                    self._market_overview = merged
                    self._tape_dirty = True
                    self._queue.put(("render", None))
                    log("图表侧栏榜单已就绪")
            except Exception as exc:
                log(f"图表侧栏榜单加载失败: {exc}")
            finally:
                self._rank_warming = False

        threading.Thread(target=work, daemon=True).start()

    def chart_rankings(self):
        """给图表页左侧扫盘栏用的分组榜单。

        只读内存里的 `_market_overview`，**不发网络请求**——
        页面每秒轮询一次，绝不能在这里阻塞。
        """
        ov = self._market_overview or {}
        quote = self.cfg.get("quote", "USDT")
        watching = set()
        for s in self.cfg.get("symbols", []):
            watching.add(str(s).upper().split("-")[0])

        def pack(key):
            out = []
            for item in (ov.get(key) or [])[:10]:
                base = str(item.get("base") or "").strip()
                if not base:
                    continue
                out.append({
                    "base": base,
                    "change": round(float(item.get("change") or 0.0), 2),
                    "inWatch": base.upper() in watching,
                })
            return out

        groups = [
            {"key": "topGainers", "label": "涨幅前十", "tone": "up"},
            {"key": "topLosers", "label": "跌幅前十", "tone": "down"},
            {"key": "topVolume", "label": "成交量前十", "tone": "vol"},
        ]
        if bool(self.cfg.get("show_oi", True)):
            groups.append({"key": "topOI", "label": "增仓前十", "tone": "up"})

        return {
            "quote": quote,
            "groups": [dict(g, items=pack(g["key"])) for g in groups],
        }

    def open_tradingview(self, base=None, quote=None):
        """切换图表页当前品种。

        第一次点击才打开浏览器；之后只更新品种，页面原地换图，
        不会再堆一堆标签页。
        """
        if base is None:
            base, quote = self.pairs[0]
        quote = quote or self.cfg.get("quote", "USDT")
        self._chart_target = (base, quote)
        self._want_scan = False              # 切品种 = 回到行情图表页

        port = self._chart_server.start() if self._chart_server else 0
        if not port:
            # 服务起不来就退回老办法：直接开 TradingView
            url = tradingview_url(base, quote, self.cfg.get("market", "perp"),
                                  self.cfg.get("tv_exchange", "BINANCE"))
            log(f"图表页不可用，直接打开 {url}")
            try:
                webbrowser.open(url)
            except Exception as exc:
                log(f"打开浏览器失败: {exc}")
            return

        # 页面是不是还开着？
        # ⚠️ 只看"最近 6 秒有没有轮询"是不够的：页面被切到后台标签之后，
        # 浏览器会把 setInterval 降频到分钟级，"6 秒"几乎必然误判成"没开"，
        # 于是每点一次币就开一个新标签 —— 攒出一百多个图表窗口，
        # 又慢又乱（用户为此抱怨过"不要每个都开新标签页"）。
        # 所以：轮询放宽到 90 秒，再补一条"窗口标题还在不在"的硬判断。
        page_open = (time.time() - self._chart_poll_at) < 90.0
        if not page_open and ctypes:
            try:
                page_open = bool(find_window_by_title(CHART_TITLE))
            except Exception:
                page_open = False
        log(f"切换图表 -> {base}  (页面已开着: {page_open})")
        if not page_open:
            try:
                webbrowser.open(self._chart_server.url)
                # Chrome 最小化时开新标签不会自己弹出来，摸一下再拉到前台
                threading.Thread(target=self._surface_chart_window,
                                 daemon=True).start()
            except Exception as exc:
                log(f"打开浏览器失败: {exc}")
        else:
            # 页面开着但被最小化/压在别的窗口后面 → 拉出来，
            # 否则用户点了币却什么都没发生，以为坏了
            threading.Thread(target=self._surface_chart_window, args=(2,),
                             daemon=True).start()

    def scan_favs(self):
        """扫盘页收藏的品种（大写 base 列表）。"""
        return [str(s).upper() for s in (self.cfg.get("scan_favs") or []) if str(s).strip()]

    def set_scan_fav(self, base, on=None):
        """收藏 / 取消收藏（on=None 表示切换）。返回新的状态。"""
        base = str(base or "").upper().strip()
        if not base:
            return False
        favs = self.scan_favs()
        want = (base not in favs) if on is None else bool(on)
        if want and base not in favs:
            favs.append(base)
        elif not want and base in favs:
            favs.remove(base)
        self.cfg["scan_favs"] = favs
        save_config(self.cfg)
        log(f"扫盘收藏 {'✓ ' if want else '✗ '}{base}（共 {len(favs)} 个）")
        return want

    def copy_favs_to_clipboard(self):
        """把收藏清单复制到剪贴板（TradingView 符号格式，一行一个）。

        为什么要"复制"而不是直接写进 TV：
        TradingView **没有**给第三方写观察列表的接口 —— 那需要用户自己的登录态。
        能做的就是替他把清单备好，粘到 TV 的搜索框 / 导入框里最省事。
        """
        favs = self.scan_favs()
        if not favs:
            return 0
        text = "\n".join(f"BINANCE:{b}USDT" for b in favs)

        def put():
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self.root.update_idletasks()
                log(f"收藏清单已复制到剪贴板（{len(favs)} 个）")
            except Exception as exc:
                log(f"复制到剪贴板失败: {exc}")

        self._ui_call(put)          # 剪贴板要主线程碰 Tk
        return len(favs)

    def open_my_tradingview(self, base=None):
        """用**用户自己的浏览器**打开 TradingView。

        关键：走系统默认浏览器（webbrowser.open），所以他自己的 cookie /
        登录 / 画线 / 布局都在，看到的是"他自己的那个 TradingView"，
        不是无痕新会话。
        """
        favs = self.scan_favs()
        b = str(base or (favs[0] if favs else "BTC")).upper()
        url = f"https://www.tradingview.com/chart/?symbol=BINANCE%3A{b}USDT"
        try:
            webbrowser.open(url)
            log(f"打开我的 TradingView: {url}")
        except Exception as exc:
            log(f"打开 TradingView 失败: {exc}")

    def open_scan(self):
        """切到「全品种扫盘」页（全市场 700+ 个品种，↑↓ 一路扫过去）。

        和切品种一样的思路：页面**已经开着**就只是让它切过去
        （页面每秒轮询 `/api/symbol`，看到 scan=true 就自己跳到 /scan），
        不再多开标签页。没开着才开浏览器。
        """
        self._want_scan = True
        port = self._chart_server.start() if self._chart_server else 0
        if not port:
            log("图表服务不可用，无法打开全品种扫盘")
            return
        page_open = (time.time() - self._chart_poll_at) < 90.0
        if not page_open and ctypes:
            try:
                page_open = bool(find_window_by_title(CHART_TITLE))
            except Exception:
                page_open = False
        log(f"切到全品种扫盘（页面已开着: {page_open}）")
        if page_open:
            threading.Thread(target=self._surface_chart_window, args=(2,),
                             daemon=True).start()
            return
        try:
            webbrowser.open(self._chart_server.url + "scan")
            threading.Thread(target=self._surface_chart_window,
                             daemon=True).start()
        except Exception as exc:
            log(f"打开浏览器失败: {exc}")

    def _surface_chart_window(self, tries=14):
        """把图表页那个浏览器窗口还原并拉到前台。

        Chrome 最小化时 webbrowser.open 只在后台加个标签，用户看不到。
        """
        if not ctypes:
            return
        u = ctypes.windll.user32
        for _ in range(tries):
            time.sleep(0.5)
            hwnd = find_window_by_title(CHART_TITLE)
            if not hwnd:
                continue
            try:
                if u.IsIconic(hwnd):
                    u.ShowWindow(hwnd, 9)          # SW_RESTORE
                u.SetForegroundWindow(hwnd)
                log("已把图表页窗口拉到前台")
            except Exception as exc:
                log(f"拉起图表页窗口失败: {exc}")
            return

    def _on_double(self, event):
        if self._blocked():
            return "break"
        if self._in_input_area(event):
            return None
        # 刚拖过窗口就忽略这次双击——想拖窗口的人不该被弹去浏览器
        if self._dragged_recently():
            log("刚拖动过窗口，忽略双击（防误触）")
            return "break"
        hit = self._row_at(event.y)
        if hit is None:
            self.popup_menu_at_cursor()   # 双击空白 -> 直接弹菜单
        elif bool(self.cfg.get("dblclick_chart", True)):
            self.open_tradingview(*hit)
        return "break"

    def _pick_open_chart(self, idx):
        """弹出列表里双击 -> 打开该品种的图表。"""
        items = getattr(self, "_pick_items", None) or []
        if not (0 <= idx < len(items)):
            return
        name = str(items[idx].get("base") or "")
        if not name:
            return
        log(f"下拉双击切图表: {name}")
        self.open_tradingview(name, self.cfg.get("quote", "USDT"))

    def _close_pick_list(self):
        """收起榜单下拉。

        ⚠️ 语义变了：以前是"关掉那个独立弹窗"，现在是"收起对话框里展开的那一组"。
        对外行为一样（调用方不用改），但它**再也不会**在屏幕上留下一串飘着的列表。
        """
        self._collapse_board_group()

    def _on_any_click(self, event):
        """兼容保留：现在下拉长在对话框里，不需要"点别处就收回"的全局监听了。"""
        return None

    def _toggle_board_group(self, key):
        """在「选择品种」对话框里原地展开/收起某一组榜单前 10。

        * **单击**一项 = 加进对话框的自选列表，**列表不关**（方便一路点过去）
        * **双击**一项 = 打开图表
        展开是"手风琴"式的：一次只开一组，免得对话框被四组列表撑爆。

        为什么不用 tk.Menu 做下拉：它一点就收。为什么也不再用独立 Toplevel：
        它按屏幕绝对坐标摆，窗口一挪就会"分离"。原地展开 = 同一个窗口，
        天然贴住标题，也不存在被别的东西盖住的问题。
        """
        panels = getattr(self, "_board_panels", None) or {}
        panel = panels.get(key)
        if not panel:
            return
        if panel.get("open"):
            self._close_pick_list()
            return
        self._close_pick_list()                 # 先收起别组（手风琴）

        items = panel["items"] or []
        if not items:
            return
        tone = panel["tone"]
        flip = str(self.cfg.get("scheme", "west")).lower() == "cn"
        up, down = (UP_CN, DOWN_CN) if flip else (UP_WEST, DOWN_WEST)

        wrap = tk.Frame(panel["body"], bg=UI_ACCENT_BG, padx=1, pady=1)
        wrap.pack(fill="x", padx=8, pady=(0, 4))
        lb = ui_style_listbox(tk.Listbox(wrap, height=len(items), width=30,
                                         font=(self.ui, 9)))
        lb.pack(fill="both", expand=True)
        self._pick_box = lb
        self._pick_items = items
        self._pick_win = None                   # 已经不再有独立弹窗了
        panel["open"] = True
        panel["row"].configure(text=f"{panel['label']}  ▴")
        self._board_open = key

        def watched():
            """已加自选的基础币集合。把选择器对话框里**还没保存**的也算上，
            这样点了列表就能立刻看到 ✓。"""
            raw = []
            items_fn = getattr(self, "_sym_items", None)
            if items_fn:
                try:
                    raw = list(items_fn())
                except Exception:
                    raw = []
            if not raw:
                raw = list(self.cfg.get("symbols", []))
            return {str(s).upper().split("-")[0] for s in raw}

        def redraw():
            added = watched()
            lb.delete(0, "end")
            for idx, item in enumerate(items, 1):
                name = str(item.get("base") or "?")
                change = float(item.get("change") or 0.0)
                color = tone or (up if change >= 0 else down)
                mark = "✓" if name.upper() in added else " "
                lb.insert("end",
                          f"{mark} {idx:>2}.  {name}   {change:+.2f}%")
                lb.itemconfig(idx - 1, foreground=color)

        state = {"job": None}

        def cancel():
            if state["job"]:
                try:
                    self.root.after_cancel(state["job"])
                except Exception:
                    pass
            state["job"] = None

        def name_at(idx):
            return str(items[idx].get("base")) if 0 <= idx < len(items) else None

        def do_add():
            state["job"] = None
            sel = lb.curselection()
            if not sel:
                return
            name = name_at(sel[0])
            if not name:
                return
            # 加到**选择器对话框的自选列表**里，而不是直接写配置——
            # 否则就绕过了「保存并应用 / 取消」，和对话框的语义打架
            add_to = getattr(self, "_sym_add", None)
            if add_to:
                add_to([name])
            else:
                self.add_symbol(name)
            log(f"下拉单击加入自选: {name}")
            redraw()                      # 更新 ✓ —— 列表不关
            lb.selection_clear(0, "end")

        def on_release(_e=None):
            cancel()
            state["job"] = self.root.after(260, do_add)
            return "break"

        def on_double(event=None):
            cancel()
            idx = lb.nearest(event.y) if event is not None else (
                lb.curselection()[0] if lb.curselection() else -1)
            self._pick_open_chart(idx)
            return "break"

        lb.bind("<ButtonRelease-1>", on_release)
        lb.bind("<Double-Button-1>", on_double)
        lb.bind("<Escape>", lambda _e: (self._close_pick_list(), "break")[1])
        redraw()
        panel["body"].pack(fill="x")

    def _collapse_board_group(self):
        """收起当前展开的那一组（列表控件一并销毁）。"""
        panels = getattr(self, "_board_panels", None) or {}
        key = getattr(self, "_board_open", None)
        panel = panels.get(key) if key else None
        self._board_open = None
        self._pick_box = None
        self._pick_items = None
        self._pick_win = None
        if not panel:
            return
        try:
            panel["body"].pack_forget()
            for child in panel["body"].winfo_children():
                child.destroy()
            panel["row"].configure(text=f"{panel['label']}  ▾")
        except Exception:
            pass
        panel["open"] = False


    # ---------------------------------------------------- 品种选择器 --

    # ------------------------------------------------------- 价格提醒 --

    def open_alerts(self, base, quote=None):
        """某个品种的提醒设置。点行尾闹铃进来，可以加、改、删。

        不做防误触（用户要求单击即开）——所以这里必须能改能删，
        不然手滑点错就没法收拾了。
        """
        base = str(base)
        quote = quote or self.cfg.get("quote", "USDT")
        win_key = f"{base}|{quote}"

        old = getattr(self, "_alert_win", None)
        if old is not None:
            try:
                if old.winfo_exists():
                    # 已经开着就直接切到目标品种，不叠窗口
                    self._alert_target = (base, quote)
                    self._alert_refresh()
                    old.deiconify()
                    old.lift()
                    old.focus_force()
                    return
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        self._alert_win = win
        self._alert_target = (base, quote)
        win.title(f"{base} 价格提醒")
        win.resizable(False, False)
        win.configure(bg=PANEL_BG)
        win.attributes("-topmost", True)

        w, hgt = 400, 430
        est_h = hgt + 56
        px = max(0, min(self._pos[0] - w - 20, self.root.winfo_screenwidth() - w - 10))
        py = max(0, min(self._pos[1], self.root.winfo_screenheight() - est_h))
        win.geometry(f"{w}x{hgt}+{px}+{py}")

        def lbl(parent, text, **kw):
            kw.setdefault("bg", PANEL_BG)
            kw.setdefault("fg", PANEL_FG)
            kw.setdefault("font", (self.ui, 9))
            return tk.Label(parent, text=text, **kw)

        # ---- 当前价 ----
        top = tk.Frame(win, bg=PANEL_BG)
        top.pack(fill="x", padx=14, pady=(12, 0))
        self._alert_head = lbl(top, "", anchor="w",
                               font=(self.ui, 10, "bold"))
        self._alert_head.pack(side="left")

        # ---- 新建 / 编辑表单 ----
        box = tk.Frame(win, bg=PANEL_BG)
        box.pack(fill="x", padx=14, pady=(10, 0))

        row1 = tk.Frame(box, bg=PANEL_BG)
        row1.pack(fill="x", pady=2)
        lbl(row1, "目标价").pack(side="left")
        self._al_price = tk.StringVar()
        ent = tk.Entry(row1, textvariable=self._al_price, width=14, relief="flat",
                       bg="#2c2c2e", fg=PANEL_FG, insertbackground=PANEL_FG,
                       font=(self.ui, 10))
        ent.pack(side="left", padx=6, ipady=2)
        lbl(row1, "（到价就提醒）").pack(side="left")

        row2 = tk.Frame(box, bg=PANEL_BG)
        row2.pack(fill="x", pady=4)
        lbl(row2, "方向").pack(side="left")
        self._al_dir = tk.StringVar(value="above")
        tk.Radiobutton(row2, text="上破", value="above", variable=self._al_dir,
                       bg=PANEL_BG, fg=PANEL_FG, selectcolor=PANEL_BG,
                       activebackground=PANEL_BG, activeforeground=PANEL_FG,
                       font=(self.ui, 9), highlightthickness=0).pack(side="left")
        tk.Radiobutton(row2, text="下破", value="below", variable=self._al_dir,
                       bg=PANEL_BG, fg=PANEL_FG, selectcolor=PANEL_BG,
                       activebackground=PANEL_BG, activeforeground=PANEL_FG,
                       font=(self.ui, 9), highlightthickness=0).pack(side="left")

        row3 = tk.Frame(box, bg=PANEL_BG)
        row3.pack(fill="x", pady=4)
        lbl(row3, "提醒方式").pack(side="left")
        self._al_toast = tk.BooleanVar(value=True)
        self._al_mail = tk.BooleanVar(value=False)
        self._al_repeat = tk.BooleanVar(value=False)
        tk.Checkbutton(row3, text="电脑弹窗", variable=self._al_toast,
                       bg=PANEL_BG, fg=PANEL_FG, selectcolor=PANEL_BG,
                       activebackground=PANEL_BG, activeforeground=PANEL_FG,
                       font=(self.ui, 9), highlightthickness=0).pack(side="left")
        tk.Checkbutton(row3, text="QQ 邮箱", variable=self._al_mail,
                       bg=PANEL_BG, fg=PANEL_FG, selectcolor=PANEL_BG,
                       activebackground=PANEL_BG, activeforeground=PANEL_FG,
                       font=(self.ui, 9), highlightthickness=0).pack(side="left")

        row4 = tk.Frame(box, bg=PANEL_BG)
        row4.pack(fill="x", pady=4)
        lbl(row4, "重复").pack(side="left")
        tk.Radiobutton(row4, text="只提醒一次", value=False, variable=self._al_repeat,
                       bg=PANEL_BG, fg=PANEL_FG, selectcolor=PANEL_BG,
                       activebackground=PANEL_BG, activeforeground=PANEL_FG,
                       font=(self.ui, 9), highlightthickness=0).pack(side="left")
        tk.Radiobutton(row4, text="反复提醒（回撤后重新武装）", value=True,
                       variable=self._al_repeat,
                       bg=PANEL_BG, fg=PANEL_FG, selectcolor=PANEL_BG,
                       activebackground=PANEL_BG, activeforeground=PANEL_FG,
                       font=(self.ui, 9), highlightthickness=0).pack(side="left")

        self._al_editing = None          # 正在编辑哪条（None = 新建）
        self._alert_hint = lbl(box, "", anchor="w", fg=PANEL_DIM,
                               font=(self.ui, 8))
        self._alert_hint.pack(fill="x", pady=(2, 0))

        btns = tk.Frame(box, bg=PANEL_BG)
        btns.pack(fill="x", pady=(4, 0))

        def do_add():
            try:
                price = float(str(self._al_price.get()).strip())
            except ValueError:
                self._alert_hint.configure(text="目标价要填数字", fg="#f6465d")
                return
            if price <= 0:
                self._alert_hint.configure(text="目标价必须大于 0", fg="#f6465d")
                return
            if self._al_editing:
                self._alerts.update(self._al_editing, price=price,
                                    dir=self._al_dir.get(),
                                    repeat=self._al_repeat.get(),
                                    toast=self._al_toast.get(),
                                    mail=self._al_mail.get(),
                                    enabled=True)
                log(f"提醒已修改：{base} {'上破' if self._al_dir.get()=='above' else '下破'} "
                    f"{fmt_price(price)}")
                self._al_editing = None
                self._alert_hint.configure(text="已修改", fg="#0ecb81")
            else:
                self._alerts.add(base, quote, price, self._al_dir.get(),
                                 self._al_repeat.get(), self._al_toast.get(),
                                 self._al_mail.get())
                log(f"提醒已添加：{base} {'上破' if self._al_dir.get()=='above' else '下破'} "
                    f"{fmt_price(price)}"
                    f"{'（反复）' if self._al_repeat.get() else '（一次）'}")
                self._alert_hint.configure(text="已添加", fg="#0ecb81")
            self._al_price.set("")
            self._alert_refresh()
            self.render()

        tk.Button(btns, text="添加提醒", command=do_add, relief="flat", bd=0,
                  bg=PANEL_ACCENT, fg="#000000", font=(self.ui, 9),
                  activebackground=PANEL_ACCENT, cursor="hand2",
                  padx=10).pack(side="left")

        def do_mail_cfg():
            self.open_mail_settings()

        tk.Button(btns, text="邮箱设置…", command=do_mail_cfg, relief="flat", bd=0,
                  bg="#2c2c2e", fg=PANEL_FG, font=(self.ui, 9),
                  activebackground="#3a3a3c", activeforeground=PANEL_FG,
                  cursor="hand2", padx=8).pack(side="right")

        # ---- 已有提醒列表 ----
        lbl(win, "已有的提醒（点一条可改；按「删除」移除）",
            anchor="w", fg=PANEL_DIM, font=(self.ui, 8)).pack(
                fill="x", padx=14, pady=(12, 2))

        wrap = tk.Frame(win, bg=PANEL_ACCENT, padx=1, pady=1)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        self._alert_list = tk.Listbox(
            wrap, activestyle="none", highlightthickness=0, bd=0,
            exportselection=False, bg="#2c2c2e", fg=PANEL_FG,
            selectbackground=PANEL_ACCENT, selectforeground="#000000",
            font=(self.ui, 9))
        self._alert_list.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(wrap, command=self._alert_list.yview)
        sb.pack(side="right", fill="y")
        self._alert_list.configure(yscrollcommand=sb.set)

        lb_btns = tk.Frame(win, bg=PANEL_BG)
        lb_btns.pack(fill="x", padx=14, pady=(0, 10))

        def selected_id():
            sel = self._alert_list.curselection()
            items = getattr(self, "_alert_items", [])
            if not sel or sel[0] >= len(items):
                return None
            return items[sel[0]]["id"]

        def do_load():
            aid = selected_id()
            if not aid:
                self._alert_hint.configure(text="先在上面选一条", fg="#f0b90b")
                return
            item = next((a for a in self._alerts.all() if a["id"] == aid), None)
            if not item:
                return
            self._al_editing = aid
            self._al_price.set(fmt_price(item["price"]).replace(",", ""))
            self._al_dir.set(item["dir"])
            self._al_repeat.set(bool(item["repeat"]))
            self._al_toast.set(bool(item["toast"]))
            self._al_mail.set(bool(item["mail"]))
            self._alert_hint.configure(
                text=f"正在修改这条（改完点「添加提醒」保存）", fg=PANEL_ACCENT_DIM)

        def do_del():
            aid = selected_id()
            if not aid:
                self._alert_hint.configure(text="先在上面选一条", fg="#f0b90b")
                return
            if self._alerts.remove(aid):
                log(f"提醒已删除：{base} {aid}")
                if self._al_editing == aid:
                    self._al_editing = None
                self._alert_hint.configure(text="已删除", fg="#f6465d")
                self._alert_refresh()
                self.render()

        def do_toggle():
            aid = selected_id()
            if not aid:
                self._alert_hint.configure(text="先在上面选一条", fg="#f0b90b")
                return
            item = next((a for a in self._alerts.all() if a["id"] == aid), None)
            if not item:
                return
            self._alerts.update(aid, enabled=not item["enabled"])
            self._alert_refresh()
            self.render()

        for text, cmd in (("改这条", do_load), ("启用/停用", do_toggle),
                          ("删除", do_del)):
            tk.Button(lb_btns, text=text, command=cmd, relief="flat", bd=0,
                      bg="#2c2c2e", fg=PANEL_FG, font=(self.ui, 9),
                      activebackground="#3a3a3c", activeforeground=PANEL_FG,
                      cursor="hand2", padx=10).pack(side="left", padx=(0, 6))

        def do_close():
            self._alert_win = None
            try:
                win.destroy()
            except Exception:
                pass

        tk.Button(lb_btns, text="关闭", command=do_close, relief="flat", bd=0,
                  bg="#2c2c2e", fg=PANEL_DIM, font=(self.ui, 9), cursor="hand2",
                  padx=10).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", do_close)
        win.bind("<Escape>", lambda _e: do_close())
        self._alert_refresh()
        ent.focus_set()

    def _alert_refresh(self):
        """刷新提醒弹窗里的当前价与列表。"""
        win = getattr(self, "_alert_win", None)
        if not win:
            return
        try:
            if not win.winfo_exists():
                return
        except Exception:
            return
        base, quote = getattr(self, "_alert_target", ("", "USDT"))
        row = self.rows.get((base, quote)) or {}
        px = row.get("price")
        chg = row.get("change")
        head = f"{base}/{quote}   当前 {fmt_price(px) if px else '—'}"
        if chg is not None:
            head += f"   {chg:+.2f}%"
        try:
            self._alert_head.configure(text=head)
        except Exception:
            return

        items = self._alerts.for_symbol(base, quote) if self._alerts else []
        self._alert_items = items
        lb = getattr(self, "_alert_list", None)
        if lb is None:
            return
        lb.delete(0, "end")
        now = time.time()
        for it in items:
            arrow = "↑上破" if it["dir"] == "above" else "↓下破"
            flags = []
            flags.append("反复" if it["repeat"] else "一次")
            if it["toast"]:
                flags.append("弹窗")
            if it["mail"]:
                flags.append("邮件")
            state = "✓启用" if it["enabled"] else "⏸停用"
            fired = ""
            if it["fire_count"]:
                fired = f"  已触发{it['fire_count']}次"
                if it["last_fired"] and now - it["last_fired"] < 86400:
                    fired += f"（{time.strftime('%H:%M:%S', time.localtime(it['last_fired']))}）"
            lb.insert("end", f"{state} {arrow} {fmt_price(it['price'])}  "
                             f"[{'/'.join(flags)}]{fired}")
            color = PANEL_FG if it["enabled"] else PANEL_DIM
            lb.itemconfig("end", foreground=color)

    def open_mail_settings(self):
        """QQ 邮箱发信设置。

        注意：这里存的是**授权码**，不是 QQ 登录密码 ——
        QQ 邮箱必须开 SMTP 并用「设置 → 账户 → POP3/SMTP → 生成授权码」那串码。
        """
        win = getattr(self, "_mail_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    return
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        self._mail_win = win
        win.title("邮箱提醒设置")
        win.resizable(False, False)
        win.configure(bg=PANEL_BG)
        win.attributes("-topmost", True)
        w, hgt = 420, 300
        est_h = hgt + 56
        px = max(0, min(self._pos[0] - w - 20, self.root.winfo_screenwidth() - w - 10))
        py = max(0, min(self._pos[1], self.root.winfo_screenheight() - est_h))
        win.geometry(f"{w}x{hgt}+{px}+{py}")

        mcfg = dict(self.cfg.get("alert_mail") or {})
        vars_ = {
            "user": tk.StringVar(value=str(mcfg.get("user") or "")),
            "password": tk.StringVar(value=str(mcfg.get("password") or "")),
            "to": tk.StringVar(value=str(mcfg.get("to") or "")),
            "smtp_host": tk.StringVar(value=str(mcfg.get("smtp_host") or "smtp.qq.com")),
            "smtp_port": tk.StringVar(value=str(mcfg.get("smtp_port") or "465")),
        }

        def lbl(parent, text, **kw):
            kw.setdefault("bg", PANEL_BG)
            kw.setdefault("fg", PANEL_FG)
            kw.setdefault("font", (self.ui, 9))
            return tk.Label(parent, text=text, **kw)

        lbl(win, "用 QQ 邮箱给你发提醒", anchor="w",
            font=(self.ui, 10, "bold")).pack(fill="x", padx=14, pady=(12, 2))
        lbl(win, "授权码不是 QQ 密码：QQ邮箱 → 设置 → 账户 →\n"
                 "开启 POP3/SMTP 服务 → 生成授权码，填在下面。",
            anchor="w", fg=PANEL_DIM, font=(self.ui, 8),
            justify="left").pack(fill="x", padx=14, pady=(0, 8))

        form = tk.Frame(win, bg=PANEL_BG)
        form.pack(fill="x", padx=14)
        rows = (("发件 QQ 邮箱", "user"), ("授权码", "password"),
                ("收件邮箱", "to"), ("SMTP 服务器", "smtp_host"),
                ("端口", "smtp_port"))
        for text, key in rows:
            r = tk.Frame(form, bg=PANEL_BG)
            r.pack(fill="x", pady=2)
            lbl(r, text, width=12, anchor="w").pack(side="left")
            tk.Entry(r, textvariable=vars_[key], width=30, relief="flat",
                     show=("*" if key == "password" else ""),
                     bg="#2c2c2e", fg=PANEL_FG, insertbackground=PANEL_FG,
                     font=(self.ui, 9)).pack(side="left", ipady=2)

        hint = lbl(win, "", anchor="w", fg=PANEL_DIM, font=(self.ui, 8))
        hint.pack(fill="x", padx=14, pady=(6, 0))

        btns = tk.Frame(win, bg=PANEL_BG)
        btns.pack(fill="x", padx=14, pady=(8, 10))

        def collect():
            return {
                "user": vars_["user"].get().strip(),
                "password": vars_["password"].get().strip(),
                "to": vars_["to"].get().strip() or vars_["user"].get().strip(),
                "smtp_host": vars_["smtp_host"].get().strip() or "smtp.qq.com",
                "smtp_port": int(vars_["smtp_port"].get().strip() or "465"),
            }

        def do_save():
            self.cfg["alert_mail"] = collect()
            save_config(self.cfg)
            hint.configure(text="已保存", fg="#0ecb81")
            log("邮箱提醒设置已保存")

        def do_test():
            m = collect()
            if not (m["user"] and m["password"] and m["to"]):
                hint.configure(text="发件邮箱、授权码、收件邮箱都要填", fg="#f6465d")
                return
            self.cfg["alert_mail"] = m
            save_config(self.cfg)
            hint.configure(text="正在发送测试邮件…", fg=PANEL_ACCENT)
            self._alerts._send_mail(
                {"base": "测试", "quote": "", "price": 0},
                "这是一封测试邮件",
                "如果你收到这封邮件，说明行情条的邮箱提醒已经配置成功。")

        tk.Button(btns, text="保存", command=do_save, relief="flat", bd=0,
                  bg=PANEL_ACCENT, fg="#000000", font=(self.ui, 9), cursor="hand2",
                  padx=12).pack(side="left")
        tk.Button(btns, text="发一封测试邮件", command=do_test, relief="flat", bd=0,
                  bg="#2c2c2e", fg=PANEL_FG, font=(self.ui, 9), cursor="hand2",
                  padx=10).pack(side="left", padx=6)

        def do_close():
            self._mail_win = None
            try:
                win.destroy()
            except Exception:
                pass

        tk.Button(btns, text="关闭", command=do_close, relief="flat", bd=0,
                  bg="#2c2c2e", fg=PANEL_DIM, font=(self.ui, 9), cursor="hand2",
                  padx=10).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", do_close)
        win.bind("<Escape>", lambda _e: do_close())

    def test_alert(self):
        """菜单里的「测试提醒」：立刻走一遍真通知 + 真邮件，方便你确认配置对不对。

        这个入口很有必要 —— 提醒是"关键时刻要能用"的功能，
        等真的到价了才发现没配好就晚了。
        """
        base, quote = (self.pairs[0] if self.pairs
                       else (self.cfg.get("symbols", ["BTC"])[0], self.cfg.get("quote", "USDT")))
        row = self.rows.get((base, quote)) or {}
        px = row.get("price")
        price_txt = fmt_price(px) if px else "—"
        title = f"[测试] {base} 提醒"
        body = (f"这是一条测试提醒。{base}/{quote} 当前 {price_txt}。"
                f"真到价时会用同样的方式提醒你。")
        log(f"测试提醒：{title}")
        threading.Thread(target=_windows_toast, args=(title, body), daemon=True).start()
        cfgm = self.cfg.get("alert_mail") or {}
        if cfgm.get("user") and cfgm.get("password"):
            threading.Thread(
                target=self._alerts._send_mail,
                args=({"base": base, "quote": quote, "price": px or 0}, title, body),
                daemon=True).start()
            log("测试邮件已发起（看日志确认结果）")
        else:
            log("测试邮件跳过：还没配置 QQ 邮箱（菜单 → 价格提醒设置 → 邮箱设置）")

    def open_alert_settings(self):
        if self.pairs:
            self.open_alerts(self.pairs[0][0], self.pairs[0][1])
        else:
            self.open_mail_settings()

    # ------------------------------------------------------- 设置中心 --

    def set_theme(self, value):
        """切换主题皮肤：改颜色 → 落盘 → 重画（开着的窗口按新主题重建）。"""
        self.cfg["theme"] = str(value)
        save_config(self.cfg)
        self.theme = apply_theme_palette(resolve_theme(self.cfg))
        log(f"主题皮肤: {self.cfg['theme']}（实际生效: {self.theme}）")
        self._reload_theme_windows()

    def _reload_theme_windows(self):
        """让已经打开的窗口换成新主题。

        Tk 没法"重新套一遍样式"，所以：设置中心原地重建（保住当前分类），
        其它对话框（更多/仓位/提醒）直接关掉 —— 下次打开就是新颜色。
        半新半旧的花脸窗口比关掉更让人困惑。
        """
        for attr in ("_level_win", "_alert_win"):
            w = getattr(self, attr, None)
            try:
                if w is not None and w.winfo_exists():
                    w.destroy()
            except Exception:
                pass
            setattr(self, attr, None)
        sym = getattr(self, "_sym_win", None)
        try:
            if sym is not None and sym.winfo_exists():
                sym.destroy()
        except Exception:
            pass
        self._sym_win = None
        self._close_pick_list()
        win = getattr(self, "_cfg_win", None)
        page = getattr(self, "_settings_page", "display")
        try:
            if win is not None and win.winfo_exists():
                win.destroy()
        except Exception:
            pass
        self._cfg_win = None
        if win is not None:
            self.open_settings(page)

    SETTINGS_PAGES = (("display", "显示"), ("look", "外观"), ("theme", "主题皮肤"),
                      ("data", "数据与榜单"), ("alerts", "提醒"),
                      ("keys", "热键"), ("symbols", "品种"), ("about", "关于"))

    def open_settings(self, page=None):
        """设置中心：左边分类导航，右边内容。

        用户要求：「右键菜单有点太多了……在更多左边放一个齿轮，把右键菜单的功能
        都放在设置里面，分类分好，像正常软件的设置一样」。
        """
        self._refresh_menu_vars()
        page = page or getattr(self, "_settings_page", "display")
        old = getattr(self, "_cfg_win", None)
        if old is not None:
            try:
                if old.winfo_exists():
                    old.destroy()
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        self._cfg_win = win
        self._settings_page = page
        win.title("行情条设置")
        win.overrideredirect(True)
        win.resizable(False, False)
        win.configure(bg=UI_BG, highlightthickness=1, highlightbackground=UI_BORDER)
        win.attributes("-topmost", True)
        w, hgt = 648, 486
        px = max(0, min(self._pos[0] - w - 20, self.root.winfo_screenwidth() - w - 10))
        py = max(0, min(self._pos[1], self.root.winfo_screenheight() - (hgt + 20)))
        win.geometry(f"{w}x{hgt}+{px}+{py}")
        fnt = (self.ui, 9)

        # ---- 自绘标题栏（可拖动 + ✕）----
        tbar = tk.Frame(win, bg=UI_BG, height=40)
        tbar.pack(fill="x")
        tbar.pack_propagate(False)
        tk.Label(tbar, text="设置", bg=UI_BG, fg=UI_FG,
                 font=(self.ui, 11)).pack(side="left", padx=(16, 0))
        tk.Label(tbar, text="行情条 · 全品种扫盘 · 提醒", bg=UI_BG, fg=UI_FAINT,
                 font=(self.ui, 8)).pack(side="left", padx=(8, 0))
        close_x = tk.Label(tbar, text="✕", bg=UI_BG, fg=UI_DIM, padx=15,
                           font=(self.ui, 10), cursor="hand2")
        close_x.pack(side="right", fill="y")
        close_x.bind("<Enter>", lambda _e: close_x.configure(fg=UI_DANGER, bg=UI_HOVER))
        close_x.bind("<Leave>", lambda _e: close_x.configure(fg=UI_DIM, bg=UI_BG))
        tk.Frame(win, bg=UI_BORDER, height=1).pack(fill="x")

        def _drag_start(e):
            win._drag = (e.x_root - win.winfo_x(), e.y_root - win.winfo_y())

        def _drag_move(e):
            d = getattr(win, "_drag", None)
            if d:
                win.geometry(f"+{e.x_root - d[0]}+{e.y_root - d[1]}")

        for _wdg in (tbar,) + tuple(tbar.winfo_children()):
            _wdg.bind("<Button-1>", _drag_start)
            _wdg.bind("<B1-Motion>", _drag_move)

        body = tk.Frame(win, bg=UI_BG)
        body.pack(fill="both", expand=True)
        rail = tk.Frame(body, bg=UI_BG, width=152)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        tk.Frame(body, bg=UI_BORDER, width=1).pack(side="left", fill="y")
        holder = tk.Frame(body, bg=UI_BG)
        holder.pack(side="left", fill="both", expand=True, padx=18, pady=(14, 12))

        def close():
            self._cfg_win = None
            try:
                win.destroy()
            except Exception:
                pass

        close_x.bind("<Button-1>", lambda _e: close())
        win.bind("<Escape>", lambda _e: close())

        # ---- 左侧分类 ----
        nav = {}

        def select(key):
            if key not in nav:
                return
            self._settings_page = key
            for k, (row, bar, lbl) in nav.items():
                on = (k == key)
                row.configure(bg=UI_PANEL2 if on else UI_BG)
                bar.configure(bg=UI_ACCENT if on else (UI_PANEL2 if on else UI_BG))
                lbl.configure(bg=UI_PANEL2 if on else UI_BG,
                              fg=UI_FG if on else UI_DIM,
                              font=(self.ui, 9, "bold" if on else "normal"))
            for child in holder.winfo_children():
                child.destroy()
            builder = getattr(self, f"_settings_{key}", None)
            if builder:
                builder(holder, fnt)

        for key, label in self.SETTINGS_PAGES:
            row = tk.Frame(rail, bg=UI_BG, cursor="hand2")
            row.pack(fill="x", pady=1)
            bar = tk.Frame(row, bg=UI_BG, width=3, height=26)
            bar.pack(side="left", fill="y")
            bar.pack_propagate(False)
            lbl = tk.Label(row, text=label, bg=UI_BG, fg=UI_DIM, font=fnt,
                           anchor="w", padx=11)
            lbl.pack(side="left", fill="both", expand=True)
            nav[key] = (row, bar, lbl)
            for wdg in (row, lbl):
                wdg.bind("<Button-1>", lambda _e, k=key: select(k))

        select(page if page in nav else "display")
        return win

    # ---- 各分类的内容 ----

    def _settings_display(self, box, fnt):
        ui_header(box, "显示", "开关立即生效").pack(fill="x", pady=(0, 10))
        ui_toggle(box, "显示 24h 涨跌幅", self.var_chg, self._toggle_change, fnt)
        ui_toggle(box, "显示表头（标题 + 时间）", self.var_head, self._toggle_header, fnt)
        ui_toggle(box, "顶部滚动条（榜单跑马灯）", self.var_tape, self._toggle_tape, fnt)
        ui_toggle(box, "底部输入框", self.var_input, self._toggle_input, fnt)
        ui_toggle(box, "双击行情行打开图表", self.var_dblclick, self._toggle_dblclick, fnt)
        ui_toggle(box, "行尾删除按钮（×，单击直删）", self.var_del, self._toggle_del, fnt)
        ui_toggle(box, "行尾提醒按钮（🔔）", self.var_alert, self._toggle_alert, fnt)
        ui_toggle(box, "仓位 / 关注价位标记列", self.var_levels, self._toggle_levels, fnt)
        ui_sep(box, pady=(8, 8))
        ui_header(box, "鼠标", "").pack(fill="x", pady=(0, 10))
        ui_toggle(box, "窗口置顶", self.var_top, self._toggle_top, fnt)
        ui_toggle(box, "鼠标穿透（整窗不挡点击）", self.var_click,
                  self._toggle_click_through, fnt)
        ui_toggle(box, "游戏模式（锁鼠标，Ctrl+Alt+G）", self.var_game,
                  self.toggle_game_mode, fnt)

    def _settings_look(self, box, fnt):
        ui_header(box, "外观样式", "").pack(fill="x", pady=(0, 10))
        ui_choice(box, "样式", (("纯文字（全透明）", "float"),
                                ("毛玻璃", "blur"), ("纯色卡片", "card")),
                  self.var_style, self._toggle_style, fnt)
        ui_choice(box, "涨跌配色", (("绿涨红跌", "west"), ("红涨绿跌", "cn")),
                  self.var_scheme, self._toggle_scheme, fnt)
        ui_choice(box, "文字颜色", (("纯黑", "black"), ("白色", "white")),
                  self.var_color, self._toggle_text_color, fnt)
        ui_choice(box, "文字效果", tuple(TEXT_EFFECTS), self.var_effect,
                  self._toggle_effect, fnt)
        ui_sep(box, pady=(8, 8))

        def var_size():
            return tk.IntVar(value=int(self.cfg.get("font_size", 9)))
        size_holder = tk.Frame(box, bg=UI_BG)
        size_holder.pack(fill="x")
        vs = var_size()

        def apply_size():
            self.set_font_size(int(vs.get()))
        ui_choice(size_holder, "字号", tuple((str(s), s) for s in FONT_SIZE_STEPS),
                  vs, apply_size, fnt)
        opacity = tk.IntVar(value=int(round(float(self.cfg.get("alpha", 1.0)) * 100)))
        ui_choice(box, "不透明度",
                  tuple((f"{p}%", p) for p in OPACITY_STEPS[:8]),
                  opacity, lambda: self.set_alpha(int(opacity.get()) / 100.0), fnt)
        ui_sep(box, pady=(8, 8))
        fonts = [f for f in FONT_PRESETS if f[1] in set(tkfont.families(self.root))]
        if fonts:
            ui_choice(box, "字体", tuple((lab, fam) for lab, fam in fonts[:6]),
                      self.var_font, self._toggle_font, fnt)

    def _settings_theme(self, box, fnt):
        ui_header(box, "主题皮肤", "对话框 + 图表页 + 扫盘页一起换").pack(
            fill="x", pady=(0, 10))
        cur = str(self.cfg.get("theme", "night"))
        var = tk.StringVar(value=cur)
        ui_choice(box, "模式", tuple((lab, val) for val, lab in THEME_NAMES),
                  var, lambda: self.set_theme(var.get()), fnt)
        real = "白天" if self.theme == "day" else "夜间"
        sysname = "白天" if detect_system_theme() == "day" else "夜间"
        tk.Label(box, text=f"当前生效：{real}　·　系统当前是：{sysname}",
                 bg=UI_BG, fg=UI_DIM, font=(self.ui, 8), anchor="w").pack(
            fill="x", pady=(6, 0))
        tk.Label(box, text="「跟随系统」读 Windows 的浅色/深色设置；"
                           "切换主题会重开已打开的窗口。",
                 bg=UI_BG, fg=UI_FAINT, font=(self.ui, 8), anchor="w",
                 wraplength=430, justify="left").pack(fill="x", pady=(4, 0))
        ui_sep(box, pady=(12, 8))
        ui_header(box, "预览", "").pack(fill="x", pady=(0, 8))
        prev = tk.Frame(box, bg=UI_PANEL, highlightthickness=1,
                        highlightbackground=UI_BORDER)
        prev.pack(fill="x")
        inner = tk.Frame(prev, bg=UI_PANEL)
        inner.pack(padx=12, pady=10, anchor="w")
        tk.Label(inner, text="BTC", bg=UI_PANEL, fg=UI_FG,
                 font=(self.ui, 9)).pack(side="left")
        tk.Label(inner, text="  ⊙多82,500  ", bg=UI_PANEL, fg=UI_DANGER,
                 font=(self.ui, 8)).pack(side="left")
        tk.Label(inner, text="82,778.50", bg=UI_PANEL, fg=UI_FG,
                 font=(self.ui, 9)).pack(side="left")
        tk.Label(inner, text="  +0.33%", bg=UI_PANEL, fg=UI_OK,
                 font=(self.ui, 9)).pack(side="left")
        tk.Label(prev, text="面板 / 正文 / 主色 / 涨跌 就是这么一套颜色",
                 bg=UI_PANEL, fg=UI_DIM, font=(self.ui, 8)).pack(
            anchor="w", padx=12, pady=(0, 10))

    def _settings_data(self, box, fnt):
        ui_header(box, "市场", "").pack(fill="x", pady=(0, 10))
        ui_choice(box, "市场类型", (("U 本位永续", "perp"), ("现货", "spot")),
                  self.var_market, self._toggle_market, fnt)
        ui_choice(box, "成交量榜", (("不剔除", 0), ("前 10", 10),
                                    ("前 20", 20), ("前 30", 30)),
                  self.var_capfilter, self._toggle_capfilter, fnt)
        ui_toggle(box, "持仓变化榜（增仓前 10）", self.var_oi, self._toggle_oi, fnt)
        ui_sep(box, pady=(6, 8))
        ui_header(box, "刷新频率", "改完立即生效").pack(fill="x", pady=(0, 10))
        iv = tk.IntVar(value=int(float(self.cfg.get("interval", 3))))
        ui_choice(box, "行情刷新", tuple((f"{s} 秒", s) for s in (1, 2, 3, 5, 10)),
                  iv, lambda: self._set_number("interval", iv.get()), fnt)
        rk = tk.IntVar(value=int(self.cfg.get("rank_refresh", 60)))
        ui_choice(box, "榜单刷新", tuple((f"{s} 秒", s) for s in (30, 60, 120, 300)),
                  rk, lambda: self._set_number("rank_refresh", rk.get()), fnt)
        oi = tk.IntVar(value=int(self.cfg.get("oi_refresh", 600)))
        ui_choice(box, "增仓榜刷新", tuple((f"{s//60} 分", s) for s in (300, 600, 1800)),
                  oi, lambda: self._set_number("oi_refresh", oi.get()), fnt)
        ui_sep(box, pady=(6, 8))
        tk.Label(box, text="计价币：USDT（改它要动全部品种，暂时只读）",
                 bg=UI_BG, fg=UI_FAINT, font=(self.ui, 8), anchor="w").pack(fill="x")

    def _set_number(self, key, value):
        """改数值型配置：落盘 + 让相关的后台循环用新值。"""
        try:
            self.cfg[key] = int(value)
        except Exception:
            return
        save_config(self.cfg)
        if key in ("rank_refresh", "oi_refresh"):
            self._start_rank_refresh() if key == "rank_refresh" else self._start_oi_refresh()
        log(f"配置 {key} = {self.cfg[key]}")

    def _settings_alerts(self, box, fnt):
        ui_header(box, "价格提醒", "到价弹窗 + QQ 邮件").pack(fill="x", pady=(0, 10))
        tk.Label(box, text="点行情行尾的 🔔 也能直接给那个品种设提醒。",
                 bg=UI_BG, fg=UI_DIM, font=(self.ui, 8), anchor="w").pack(
            fill="x", pady=(0, 8))
        for text, cmd, kind in (("打开价格提醒设置…", self.open_alert_settings, "primary"),
                                ("测试提醒（弹窗 + 邮件）", self.test_alert, "ghost"),
                                ("QQ 邮箱设置…", self.open_mail_settings, "ghost")):
            ui_button(box, text, cmd, kind=kind, font=fnt, padx=14, pady=5).pack(
                anchor="w", pady=(0, 6))

    def _settings_keys(self, box, fnt):
        ui_header(box, "全局热键", "被别的软件占用时自动顺延").pack(
            fill="x", pady=(0, 10))
        labels = getattr(self, "_hotkey_labels", {}) or {}
        for key, name in (("toggle", "显示 / 隐藏"), ("menu", "弹出菜单"),
                          ("symbols", "选择品种"), ("click", "鼠标穿透"),
                          ("game", "游戏模式（锁鼠标）"), ("scan", "全品种扫盘")):
            row = tk.Frame(box, bg=UI_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=name, bg=UI_BG, fg=UI_FG, font=fnt,
                     anchor="w").pack(side="left")
            tk.Label(row, text=labels.get(key, "未注册"), bg=UI_PANEL2, fg=UI_ACCENT,
                     font=fnt, padx=8).pack(side="right")

    def _settings_symbols(self, box, fnt):
        ui_header(box, "品种", "自选 + 全市场").pack(fill="x", pady=(0, 10))
        ui_button(box, "选择品种…（自选增删排序）", self.open_symbols,
                  kind="primary", font=fnt, padx=14, pady=5).pack(anchor="w", pady=(0, 6))
        ui_button(box, "全品种扫盘…（741 个品种，↑↓ 一路扫）", self.open_scan,
                  kind="ghost", font=fnt, padx=14, pady=5).pack(anchor="w", pady=(0, 6))
        ui_sep(box, pady=(8, 8))
        ui_header(box, "收藏 → TradingView",
                  "TV 没有第三方写入观察列表的接口").pack(fill="x", pady=(0, 8))
        tk.Label(box, text="把扫盘页 ♥ 收藏的品种复制成 TradingView 符号清单（一行一个），\n"
                           "粘到 TradingView 的搜索/导入框里就能加进你自己的观察列表。",
                 bg=UI_BG, fg=UI_FAINT, font=(self.ui, 8), anchor="w",
                 justify="left").pack(fill="x", pady=(0, 6))
        ui_button(box, "复制收藏清单到剪贴板", self.copy_favs_to_clipboard,
                  kind="primary", font=fnt, padx=14, pady=5).pack(anchor="w", pady=(0, 6))
        ui_button(box, "用我的浏览器打开 TradingView（带登录）",
                  self.open_my_tradingview, kind="ghost", font=fnt,
                  padx=14, pady=5).pack(anchor="w", pady=(0, 6))
        ui_button(box, "打开 TradingView", lambda: self.open_tradingview(),
                  kind="ghost", font=fnt, padx=14, pady=5).pack(anchor="w")

    def _settings_about(self, box, fnt):
        ui_header(box, "关于", "").pack(fill="x", pady=(0, 10))
        for text in (f"行情条 v{APP_VERSION}",
                     f"配置：{os.path.basename(CONFIG_PATH)}",
                     f"日志：{os.path.basename(os.path.join(APP_DIR, 'ticker.log'))}",
                     "纯 Python 标准库（tkinter + urllib），零依赖"):
            tk.Label(box, text=text, bg=UI_BG, fg=UI_DIM if text.startswith("行情条")
                     else UI_FAINT, font=(self.ui, 9 if text.startswith("行情条") else 8),
                     anchor="w").pack(fill="x", pady=(0, 4))
        ui_sep(box, pady=(10, 8))
        for text, cmd in (("重新加载配置文件", self.reload_config),
                          ("打开配置文件", self.open_config)):
            ui_button(box, text, cmd, kind="ghost", font=fnt, padx=14, pady=5).pack(
                anchor="w", pady=(0, 6))

    def open_symbols(self):
        """品种选择器：增删排序自选币种，保存后立即生效。"""
        win = getattr(self, "_sym_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    return
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        self._sym_win = win
        win.title("选择品种")
        # ★ 去掉系统标题栏：那条浅色白条和深色面板放在一起最显"廉价"。
        #   自己画一条标题栏（可拖动 + 右上角 ✕），整窗才是一块完整的卡片。
        win.overrideredirect(True)
        win.resizable(False, False)
        win.configure(bg=UI_BG, highlightthickness=1, highlightbackground=UI_BORDER)
        win.attributes("-topmost", True)
        # 高度按"某组榜单展开时"算：标题栏 + 4 个列表头 + 展开的 10 行 +
        # 自选列表 + 按钮 + 底栏都得放得下（算漏了按钮会被挤出窗口，踩过）
        w, hgt = 392, 636
        est_h = hgt
        px = max(0, min(self._pos[0] - w - 20, self.root.winfo_screenwidth() - w - 10))
        py = max(0, min(self._pos[1], self.root.winfo_screenheight() - est_h))
        win.geometry(f"{w}x{hgt}+{px}+{py}")

        # ---- 自绘标题栏 ----
        tbar = tk.Frame(win, bg=UI_BG, height=38)
        tbar.pack(fill="x")
        tbar.pack_propagate(False)
        tk.Label(tbar, text="选择品种", bg=UI_BG, fg=UI_FG,
                 font=(self.ui, 11)).pack(side="left", padx=(16, 0))
        tk.Label(tbar, text="自选 · 榜单 · 全品种扫盘", bg=UI_BG, fg=UI_FAINT,
                 font=(self.ui, 8)).pack(side="left", padx=(8, 0))
        close_x = tk.Label(tbar, text="✕", bg=UI_BG, fg=UI_DIM, padx=15,
                           font=(self.ui, 10), cursor="hand2")
        close_x.pack(side="right", fill="y")
        close_x.bind("<Enter>", lambda _e: close_x.configure(fg=UI_DANGER, bg=UI_HOVER))
        close_x.bind("<Leave>", lambda _e: close_x.configure(fg=UI_DIM, bg=UI_BG))
        tk.Frame(win, bg=UI_BORDER, height=1).pack(fill="x")

        def _drag_start(e):
            win._drag = (e.x_root - win.winfo_x(), e.y_root - win.winfo_y())

        def _drag_move(e):
            d = getattr(win, "_drag", None)
            if d:
                win.geometry(f"+{e.x_root - d[0]}+{e.y_root - d[1]}")

        for _wdg in (tbar,) + tuple(tbar.winfo_children()):
            _wdg.bind("<Button-1>", _drag_start)
            _wdg.bind("<B1-Motion>", _drag_move)
        win.bind("<Escape>", lambda _e: None)

        # 榜单区：点标题就能原地展开前 10（v0.16 改的，不再开独立弹窗）
        ui_header(win, "榜单 · 点标题展开", "单击加入自选 · 双击切图表").pack(
            fill="x", padx=16, pady=(14, 4))
        board = tk.Frame(win, bg=UI_BG)
        board.pack(fill="x", padx=16)

        ui_header(win, "自选品种", "双击行看图表").pack(
            fill="x", padx=16, pady=(12, 4))
        holder = tk.Frame(win, bg=UI_BG)
        holder.pack(fill="both", expand=True, padx=16)
        box = ui_style_listbox(
            tk.Listbox(holder, height=5, font=(self.ui, 10)))
        sb = ui_style_scrollbar(holder)
        if sb is not None:
            sb.configure(command=box.yview)
            box.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y", padx=(4, 0))
        box.pack(side="left", fill="both", expand=True)
        for base, quote in self.pairs:
            box.insert("end", base if quote == self.cfg.get("quote", "USDT")
                       else f"{base}-{quote}")

        # 这里以前有个搜索输入框 + 实时匹配下拉。
        # 现在主窗口底部就是 IME 式输入，这个框是重复的，去掉了。

        def current_items():
            return [box.get(i) for i in range(box.size())]

        def add_symbols(names):
            existing = {s.upper() for s in current_items()}
            quote = self.cfg.get("quote", "USDT")
            for raw in names:
                item = normalize_symbol(raw, quote)
                if not item:
                    continue
                label = item[0] if item[1] == quote else f"{item[0]}-{item[1]}"
                if label.upper() not in existing:
                    box.insert("end", label)
                    existing.add(label.upper())

        # 给榜单弹出列表用：它要把币加进**这个对话框的**自选列表，
        # 而不是直接写配置（否则绕过「保存并应用 / 取消」）
        self._sym_add = add_symbols
        self._sym_items = current_items

        def build_board():
            """榜单下拉：点开看前 10。列表里**单击加自选**、**双击切图表**。
            （这是「选择品种」对话框里的列表，和图表页那个只切图的扫盘栏不同）

            ⚠️ 下拉**就长在对话框里**（原地把列表展开在标题下面），
            不再开独立小窗口。以前那套独立 Toplevel 的问题是：
            它按屏幕绝对坐标摆位，窗口一挪、或者"下面放不下改成摆上面"，
            列表就会跑到离对话框很远的地方，看着就像"下拉框和窗口分离了"。
            原地展开从根上没这个问题 —— 它跟对话框是一个窗口。
            """
            for child in board.winfo_children():
                child.destroy()
            self._board_panels = {}
            self._board_open = None
            self._pick_box = None
            self._pick_items = None
            overview = getattr(self, "_market_overview", None) or {}
            flip = str(self.cfg.get("scheme", "west")).lower() == "cn"
            up, down = (UP_CN, DOWN_CN) if flip else (UP_WEST, DOWN_WEST)

            groups = (
                ("成交量前10", "topVolume", None),
                ("涨幅前10", "topGainers", up),
                ("跌幅前10", "topLosers", down),
            )
            if bool(self.cfg.get("show_oi", True)):
                groups = groups + (("增仓前10", "topOI", up),)
            if not any(overview.get(key) for _l, key, _c in groups):
                tk.Label(board, text="榜单加载中…", bg=UI_BG, fg=UI_DIM,
                         font=(self.ui, 8), anchor="w").pack(fill="x")
                return

            for label, key, tone in groups:
                items = overview.get(key) or []
                # 一组 = 一个容器：标题在上，展开的列表在下（同一个窗口里）
                cont = tk.Frame(board, bg=UI_BG)
                cont.pack(fill="x")
                row = tk.Label(
                    cont, text=f"{label}  ▾", anchor="w",
                    bg=UI_PANEL, fg=UI_FG, font=(self.ui, 9),
                    padx=10, pady=3, cursor="hand2", bd=0,
                )
                row.pack(fill="x", pady=1)
                row.bind("<Enter>", lambda e, w=row: w.configure(bg=UI_HOVER))
                row.bind("<Leave>", lambda e, w=row: w.configure(bg=UI_PANEL))
                body = tk.Frame(cont, bg=UI_BG)
                self._board_panels[key] = {
                    "row": row, "body": body, "label": label,
                    "tone": tone, "items": items, "open": False,
                }
                row.bind("<Button-1>",
                         lambda e, k=key: self._toggle_board_group(k))

        def start_universe_load():
            if not getattr(self, "_market_overview", None) and \
                    not getattr(self, "_symbols_loading", False):
                self._symbols_loading = True

                def work():
                    try:
                        overview = load_market_overview()
                        self._market_overview = overview
                        self._symbol_universe = overview.get("symbols") or FALLBACK_SYMBOLS
                    except Exception as exc:
                        log(f"合约清单加载失败: {exc}")
                    finally:
                        self._symbols_loading = False

                threading.Thread(target=work, daemon=True).start()

            # 在主线程里轮询结果 —— 工作线程里碰 Tk 是不安全的
            waited = {"ms": 0}

            def poll():
                overview = getattr(self, "_market_overview", None)
                if overview and overview.get("symbols"):
                    self._symbol_universe = overview["symbols"]
                    build_board()
                    return
                waited["ms"] += 300
                if waited["ms"] > 25_000:          # 拉不到就别一直转
                    return
                try:
                    if win.winfo_exists():
                        win.after(300, poll)
                except Exception:
                    pass

            build_board()
            win.after(300, poll)

        start_universe_load()

        def remove_selected():
            for i in reversed(box.curselection()):
                box.delete(i)

        def move(delta):
            sel = box.curselection()
            if len(sel) != 1:
                return
            i = sel[0]
            j = i + delta
            if 0 <= j < box.size():
                text = box.get(i)
                box.delete(i)
                box.insert(j, text)
                box.selection_clear(0, "end")
                box.selection_set(j)

        def save():
            symbols = current_items()
            if not symbols:
                return
            self.cfg["symbols"] = symbols
            save_config(self.cfg)
            self.pairs = build_pairs(symbols, self.cfg.get("quote", "USDT"))
            self.rows = {}
            self._price_width = 0
            self._mapped_pos = None
            self.render()
            self.force_refresh()
            close_dialog()

        def close_dialog():
            """关对话框。

            那个榜单弹出列表是独立的 Toplevel，**不会跟着对话框一起消失**，
            必须显式收掉——否则关了选择品种，那一串前十还飘在屏幕上。
            """
            self._close_pick_list()
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", close_dialog)
        close_x.bind("<Button-1>", lambda _e: close_dialog())

        btns = tk.Frame(win, bg=UI_BG)
        btns.pack(fill="x", padx=16, pady=(12, 4))
        # 「添加」按钮跟着搜索框一起去掉了：现在加币在主窗口底部输入
        for text, cmd, kind in (("删除", remove_selected, "danger"),
                                ("上移", lambda: move(-1), "ghost"),
                                ("下移", lambda: move(1), "ghost")):
            ui_button(btns, text, cmd, kind=kind, font=(self.ui, 9),
                      padx=14, pady=3).pack(side="left", padx=(0, 6))
        # 全品种扫盘入口：直接跳到那个页面（全市场 700+ 品种，↑↓ 快速扫）
        ui_button(btns, "全品种扫盘 ▸", self.open_scan, kind="primary",
                  font=(self.ui, 9), padx=12, pady=3).pack(side="right")

        ui_sep(win, pady=(10, 0))
        foot = tk.Frame(win, bg=UI_BG)
        foot.pack(fill="x", padx=16, pady=(6, 14))
        ui_button(foot, "保存并应用", save, kind="primary", font=(self.ui, 9),
                  padx=16, pady=4).pack(side="right")
        ui_button(foot, "取消", close_dialog, kind="ghost", font=(self.ui, 9),
                  padx=14, pady=4).pack(side="right", padx=(0, 8))

        def open_selected_chart(_evt=None):
            sel = box.curselection()
            if not sel:
                return
            item = normalize_symbol(box.get(sel[0]), self.cfg.get("quote", "USDT"))
            if item:
                self.open_tradingview(*item)

        box.bind("<Double-Button-1>", open_selected_chart)

    def _schedule_config_save(self):
        """改透明度/字号时别每次写盘，停手 800ms 后再保存。"""
        job = getattr(self, "_cfg_job", None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._cfg_job = self.root.after(800, self._flush_config)

    def _flush_config(self):
        self._cfg_job = None
        save_config(self.cfg)

    def _toggle_scheme(self):
        self.cfg["scheme"] = self.var_scheme.get()
        self.render()
        save_config(self.cfg)

    def open_config(self):
        try:
            if not os.path.exists(CONFIG_PATH):
                save_config(self.cfg)
            os.startfile(CONFIG_PATH)            # noqa: S606 - Windows 专用
        except Exception as exc:
            log(f"打开配置文件失败: {exc}")

    def reload_config(self):
        fresh = load_config()
        keep_pos = self.cfg.get("position")
        self.cfg.clear()
        self.cfg.update(fresh)
        if keep_pos and not fresh.get("position"):
            self.cfg["position"] = keep_pos
        self.pairs = build_pairs(self.cfg.get("symbols", []), self.cfg.get("quote", "USDT"))
        self.rows = {}
        self._price_width = 0
        self.family = resolve_font(self.root, self.cfg.get("font_family"))
        self._fonts.clear()
        self._mapped_pos = None
        self._apply_style_attrs()
        self.render()
        self.force_refresh()

    def force_refresh(self):
        self._wake.set()

    def quit(self):
        self._stop.set()
        self._wake.set()
        try:
            self._alerts.stop()
        except Exception:
            pass
        self._save_position()
        save_config(self.cfg)
        try:
            self.root.destroy()
        except Exception:
            pass

    # ------------------------------------------------------ 抓取线程 --

    def _start_fetcher(self):
        self.pairs = build_pairs(self.cfg.get("symbols", []), self.cfg.get("quote", "USDT"))
        threading.Thread(target=self._fetch_loop, daemon=True).start()

    def _fetch_loop(self):
        fails = 0
        while not self._stop.is_set():
            pairs = list(self.pairs)
            self._queue.put(("try", None))
            try:
                rows, source = fetch_all(pairs, str(self.cfg.get("market", "perp")).lower())
                self._queue.put(("data", (rows, source)))
                fails = 0
                wait = max(1.0, float(self.cfg.get("interval", 3)))
            except Exception as exc:
                fails += 1
                self._queue.put(("error", str(exc)))
                wait = min(max(1.0, float(self.cfg.get("interval", 3))) * (2 ** min(fails, 4)), 30.0)
            self._wake.wait(wait)
            self._wake.clear()

    def _pump(self):
        dirty = False
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "try":
                    self.last_try = time.time()
                elif kind == "data":
                    rows, source = payload
                    # 价格变了就记一次闪烁，让"在跳"这件事看得见
                    now = time.time()
                    for key, item in rows.items():
                        old = self.rows.get(key)
                        if old and abs(item["price"] - old["price"]) > 1e-12:
                            self._flash[key] = (1 if item["price"] > old["price"] else -1, now)
                    self.rows = rows
                    self.source = source
                    self.error = None
                    self.last_ok = time.time()
                    dirty = True
                    self._alert_refresh()      # 弹窗开着的当前价要跟着动
                elif kind == "error":
                    self.error = payload
                    log(f"抓取失败: {payload}")
                    dirty = True
                elif kind == "render":
                    dirty = True
                elif kind == "call":
                    # 别的线程要求在主线程里跑一段 Tk 操作
                    # （HTTP 线程碰 Tk 会 RuntimeError: main thread is not in main loop）
                    try:
                        payload()
                    except Exception as exc:
                        log(f"主线程回调失败: {exc}")
                elif kind == "alerts":
                    # 提醒引擎触发了：铃铛要变亮，弹窗里的"已触发"也要更新
                    self._alert_refresh()
                    if not dirty:
                        try:
                            self.render()
                        except Exception as exc:
                            log(f"提醒重画失败: {exc}")
                elif kind == "hotkey":
                    self._handle_hotkey(payload)
                elif kind == "hotkeys":
                    self._hotkey_labels = payload
                    self._update_hotkey_hint(payload)
        except queue.Empty:
            pass

        if dirty or not self._painted:
            self.render()
            self._painted = True
            self._ensure_anim()
        self.root.after(250, self._pump)

    _painted = False

    # ------------------------------------------------------ 闪烁动画 --

    def _ensure_anim(self):
        """有闪烁就启动动画循环（渲染本身是 3 秒一次，闪烁需要更快）。"""
        now = time.time()
        self._flash = {k: v for k, v in self._flash.items()
                       if (now - v[1]) * 1000.0 < FLASH_MS}
        if self._flash and self._anim_job is None:
            self._anim_job = self.root.after(FLASH_FRAME_MS, self._anim_tick)

    def _anim_tick(self):
        self._anim_job = None
        now = time.time()
        self._flash = {k: v for k, v in self._flash.items()
                       if (now - v[1]) * 1000.0 < FLASH_MS}
        self.render()
        if self._flash:
            self._anim_job = self.root.after(FLASH_FRAME_MS, self._anim_tick)


# ------------------------------------------------------------------ 入口 --

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="透明悬浮加密货币行情窗")
    p.add_argument("--symbols", help="逗号分隔，如 BTC,ETH,SOL,DOGE")
    p.add_argument("--quote", help="计价币，默认 USDT")
    p.add_argument("--market", choices=["perp", "spot"], help="perp=永续合约 spot=现货")
    p.add_argument("--interval", type=float, help="刷新间隔（秒）")
    p.add_argument("--alpha", type=float, help="不透明度 0.2~1.0")
    p.add_argument("--style", choices=["float", "blur", "card"],
                   help="float=纯文字 blur=毛玻璃 card=纯色卡片")
    p.add_argument("--scheme", choices=["west", "cn"], help="west=绿涨红跌 cn=红涨绿跌")
    p.add_argument("--font-size", type=int, help="字号")
    p.add_argument("--no-change", action="store_true", help="隐藏涨跌幅")
    p.add_argument("--self-test", action="store_true", help="只抓一次数据并打印，不开窗口")
    return p.parse_args(argv)


def enable_dpi_awareness():
    """高分屏下避免 Tk 界面被系统拉伸模糊。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main(argv=None):
    args = parse_args(argv)
    cfg = load_config()

    if args.symbols:
        cfg["symbols"] = [s for s in args.symbols.replace(" ", "").split(",") if s]
    if args.quote:
        cfg["quote"] = args.quote
    if args.interval:
        cfg["interval"] = max(1.0, args.interval)
    if args.alpha:
        cfg["alpha"] = max(0.2, min(1.0, args.alpha))
    if args.style:
        cfg["style"] = args.style
    if args.scheme:
        cfg["scheme"] = args.scheme
    if args.market:
        cfg["market"] = args.market
    if args.font_size:
        cfg["font_size"] = args.font_size
    if args.no_change:
        cfg["show_change"] = False

    pairs = build_pairs(cfg["symbols"], cfg["quote"])

    if args.self_test:
        rows, source = fetch_all(pairs, str(cfg.get("market", "perp")).lower())
        print(f"数据源: {source}")
        for base, quote in pairs:
            item = rows.get((base, quote))
            if item:
                print(f"  {base:<6} {fmt_price(item['price']):>14}  {item['change']:+.2f}%")
            else:
                print(f"  {base:<6} 无数据")
        return 0

    if not os.path.exists(CONFIG_PATH):
        save_config(cfg)

    enable_dpi_awareness()
    app = TickerApp(cfg)
    try:
        app.render()
    except Exception:
        # ⚠️ 打包成 --noconsole 的 exe 后 **没有 stderr**：
        #    启动时第一次渲染如果抛异常，进程会**直接退出**，
        #    留下一个"端口在监听、图表页永远不回"的假象（查了很久才定位）。
        #    所以这里必须自己把 traceback 写进日志，而且要**继续跑**：
        #    行情条是常用工具，一次渲染失败不该让它整个死掉。
        log("启动首次渲染失败（已继续运行）:\n" + traceback.format_exc())
    try:
        app.root.mainloop()
    except Exception:
        log("主循环异常退出:\n" + traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
