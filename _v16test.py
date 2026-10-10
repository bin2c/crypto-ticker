# -*- coding: utf-8 -*-
"""v0.16 新功能测试（Tk 端，不需要网络）：

1. 仓位 / 关注价位标记：写入、紧凑格式、行内命中区、字号小于价格、弹窗保存
2. 游戏模式：锁鼠标、强制穿透、指示、各类鼠标事件被吞
3. 右键菜单显示真实热键（含「隐藏窗口」）
4. 选择品种对话框：榜单下拉改成**内部展开**（不再有独立弹窗 → 不可能"分离"）

跑法：python _v16test.py
"""

import re
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

import ticker

# Windows 控制台默认是 GBK，直接 print "✔" / 中文会 UnicodeEncodeError。
# 输出一律转成 UTF-8（顺带落一份报告文件，方便事后翻）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPORT = open("_v16test_out.txt", "w", encoding="utf-8")


def emit(line):
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        REPORT.write(line + "\n")
        REPORT.flush()
    except Exception:
        pass


passed = 0
total = 0


def check(label, cond, extra=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
    emit(f"  {'[OK]' if cond else '[NG]'} {label}" + (f"   {extra}" if extra else ""))


def pump(app, ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            app.root.update()
        except Exception:
            return
        time.sleep(0.02)


def all_widgets(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(all_widgets(c))
    return out


def click_widget(w):
    """点一下控件：原生 Button 用 invoke()，Label 手做的扁平按钮发一次点击事件。"""
    try:
        w.invoke()
    except AttributeError:
        w.event_generate("<Button-1>")


def widgets_by_text(root, cls, text):
    """按文字找控件。v0.17 起对话框的按钮是 Label 手做的扁平按钮，
    所以"按类找 + 按文字找"要一起用（传 cls 时也把 Label 算上）。"""
    classes = (cls, tk.Label) if cls is not tk.Label else (tk.Label,)
    return [w for w in all_widgets(root)
            if isinstance(w, classes) and str(w.cget("text")) == text]


class Ev:
    """假的 Tk 事件：只带处理器真正会读的字段。"""

    def __init__(self, widget=None, x=0, y=0, x_root=0, y_root=0, delta=0):
        self.widget = widget
        self.x, self.y = x, y
        self.x_root, self.y_root = x_root, y_root
        self.delta = delta


def main():
    import traceback
    cfg = ticker.load_config()
    # ⚠️ 测试会改内存里的 cfg，而 set_level() 之类会顺手 save_config()。
    # 不把原值存下来还回去，用户的自选/位置/热键开关就被测试改掉了
    # （踩过：自选从 5 个变成 3 个）。除了快照，还留一份**原始文件文本**，
    # 收尾时原样写回 —— 这样连键顺序都不会变。
    orig = {k: cfg.get(k) for k in
            ("symbols", "levels", "position", "hotkeys", "show_levels")}
    try:
        with open(ticker.CONFIG_PATH, encoding="utf-8-sig") as fh:
            orig_text = fh.read()
    except Exception:
        orig_text = None
    cfg["symbols"] = ["BTC", "ETH", "SOL"]
    cfg["levels"] = {}
    cfg["position"] = [1400, 700]
    cfg["hotkeys"] = False          # 测试里别去抢全局热键
    app = ticker.TickerApp(cfg)
    pump(app, 1200)

    try:
        # ---------------------------------------------------- 1. 仓位标记 --
        print("\n=== 仓位 / 关注价位标记 ===")
        check("默认没有标记", app.level_of("BTC") is None)

        app.set_level("BTC", "long", 82000.0)
        pump(app, 300)
        info = app.level_of("BTC")
        check("写入后读得回来", bool(info) and info[0] == "long" and abs(info[1] - 82000.0) < 1e-9)
        check("★ 做多 = 红色", info[2] == ticker.LEVEL_LONG, info[2])
        check("★ 价位紧凑显示（不摆没用的 .00）", info[3] == "多82,000", info[3])

        app.set_level("ETH", "short", 2492.5)
        app.set_level("SOL", "watch", 109.8123)
        pump(app, 300)
        check("★ 做空 = 绿色", app.level_of("ETH")[2] == ticker.LEVEL_SHORT)
        check("★ 仅关注 = 琥珀", app.level_of("SOL")[2] == ticker.LEVEL_WATCH)
        check("小币种保留小数位", app.level_of("SOL")[3] == "看109.8123",
              app.level_of("SOL")[3])
        check("落盘了（config.json 里有）", "BTC" in (app.cfg.get("levels") or {}))

        # 行内命中区
        geom = app._level_geom
        check("三行都记了标记命中区", len(geom) == 3, f"{len(geom)} 个")
        top, bottom, base, quote, x0, x1 = geom[0]
        check("命中区能按坐标查回来",
              app._level_at((x0 + x1) / 2, (top + bottom) / 2) == (base, quote))
        check("命中区外查不到", app._level_at(x0 - 40, (top + bottom) / 2) is None)

        # 字号必须**小于**价格数字（用户明确要求）
        def text_size(want):
            for it in app.canvas.find_all():
                if app.canvas.type(it) != "text":
                    continue
                if app.canvas.itemcget(it, "text") != want:
                    continue
                try:
                    f = tkfont.Font(root=app.root, font=app.canvas.itemcget(it, "font"))
                    return int(f.cget("size")), app.canvas.itemcget(it, "fill")
                except Exception:
                    return None, None
            return None, None

        tag_size, tag_fill = text_size("多82,000")
        btc_row = app.rows.get(("BTC", "USDT"))
        if btc_row:
            price_size, price_fill = text_size(ticker.fmt_price(btc_row["price"]))
            check("标记字号比价格数字小", tag_size is not None and price_size is not None
                  and tag_size < price_size, f"{tag_size} < {price_size}")
            check("标记用标记色（和价格不同色）",
                  tag_fill == ticker.LEVEL_LONG and tag_fill != price_fill,
                  f"{tag_fill} vs {price_fill}")
        else:
            check("标记字号比价格数字小（没行情，退化成只查字号）",
                  tag_size is not None and tag_size < int(app.cfg.get("font_size", 9)),
                  f"tag={tag_size} < font_size={app.cfg.get('font_size')}")
            check("标记用标记色", tag_fill == ticker.LEVEL_LONG, str(tag_fill))

        # 弹窗：改价位、换方向、保存
        app.open_level("BTC")
        pump(app, 400)
        win = app._level_win
        check("仓位弹窗打开了", win is not None and win.winfo_exists())
        entries = [w for w in all_widgets(win) if isinstance(w, tk.Entry)]
        check("弹窗里有价位输入框", len(entries) == 1)
        entries[0].delete(0, "end")
        entries[0].insert(0, "76543")
        for w in all_widgets(win):
            if isinstance(w, tk.Radiobutton) and str(w.cget("text")) == "做空":
                w.invoke()
        save = widgets_by_text(win, tk.Button, "保存")
        check("有保存按钮", len(save) == 1)
        click_widget(save[0])
        pump(app, 300)
        info2 = app.level_of("BTC")
        check("★ 弹窗保存生效（改了价 + 改成做空）",
              info2[0] == "short" and abs(info2[1] - 76543.0) < 1e-9,
              f"{info2[0]} {info2[1]}")
        check("弹窗关掉了", app._level_win is None or not app._level_win.winfo_exists())

        # 弹窗删除
        app.open_level("BTC")
        pump(app, 300)
        dele = widgets_by_text(app._level_win, tk.Button, "删除标记")
        check("已设过标记时弹窗有「删除标记」", len(dele) == 1)
        click_widget(dele[0])
        pump(app, 300)
        check("删除标记生效", app.level_of("BTC") is None)

        # 显示列开关
        app.var_levels.set(False)
        app._toggle_levels()
        pump(app, 300)
        check("关掉「显示仓位标记」后不再占列", app._level_geom == [] and app.cfg["show_levels"] is False)
        app.var_levels.set(True)
        app._toggle_levels()
        pump(app, 300)
        check("再打开又回来了", len(app._level_geom) == 3)

        app.clear_all_levels()
        pump(app, 300)
        check("一键清空全部标记", (app.cfg.get("levels") or {}) == {})

        # ---------------------------------------------------- 2. 游戏模式 --
        print("\n=== 游戏模式（锁鼠标）===")
        check("默认关着", app._game_mode is False)
        pump(app, 300)
        w_before = app._win_w
        app.toggle_game_mode()
        pump(app, 400)
        check("★ 打开后 _game_mode = True", app._game_mode is True)
        check("输入栏亮了指示", "游戏模式" in str(app.game_label.cget("text")),
              str(app.game_label.cget("text")))
        check("指示真的占到了地方（不是 0 宽）", app.game_label.winfo_width() > 10,
              f"w={app.game_label.winfo_width()}")
        check("窗口没被指示撑宽", app._win_w == w_before,
              f"{w_before} -> {app._win_w}")
        check("菜单勾选状态同步", bool(app.var_game.get()) is True)

        # ★★ 回归：开穿透不许把窗口搞黑 / 搞没
        #    曾经的 bug：_hwnd() 在窗口挂到 TkTopLevel 之前就缓存了内层 TkChild，
        #    于是 WS_EX_LAYERED 被加到一个没有任何分层属性的子窗口上 →
        #    DWM 不再合成内容 → 整窗黑方块；关掉之后窗口直接消失（要重启）。
        #    这个 bug 靠"看样式位"是查不出来的（当时位看着都对），
        #    所以这里直接断言三件事：用的是顶层窗口、alpha 没被清、子窗口干净。
        import ctypes as _ct
        import ctypes.wintypes as _wt
        _u = _ct.windll.user32

        def _cls(h):
            b = _ct.create_unicode_buffer(256)
            _u.GetClassNameW(h, b, 256)
            return b.value

        def _layered_attr(h):
            key = _wt.DWORD(0)
            a = _ct.c_ubyte(0)
            fl = _wt.DWORD(0)
            ok = _u.GetLayeredWindowAttributes(h, _ct.byref(key),
                                               _ct.byref(a), _ct.byref(fl))
            return bool(ok), a.value

        check("★ _hwnd() 拿的是真正的顶层窗口（TkTopLevel）",
              _cls(app._hwnd()) == "TkTopLevel", _cls(app._hwnd()))
        check("★ 内层 TkChild 没被加上 WS_EX_LAYERED（黑屏根因）",
              not (_u.GetWindowLongW(app.root.winfo_id(), ticker.GWL_EXSTYLE)
                   & ticker.WS_EX_LAYERED))
        ok_b, a_b = _layered_attr(app._hwnd())
        app.toggle_game_mode()          # 关
        pump(app, 300)
        app.toggle_game_mode()          # 再开（复现路径）
        pump(app, 300)
        ok_a, a_a = _layered_attr(app._hwnd())
        check("★ 开穿透后分层属性还在（alpha 没被清掉）",
              ok_a and a_a == a_b, f"alpha {a_b} -> {a_a}")
        ex_now = _u.GetWindowLongW(app._hwnd(), ticker.GWL_EXSTYLE)
        check("穿透就只加了 WS_EX_TRANSPARENT 这一位，没乱动 LAYERED",
              bool(ex_now & ticker.WS_EX_LAYERED)
              and bool(ex_now & ticker.WS_EX_TRANSPARENT))

        import ctypes as _ct
        u = _ct.windll.user32
        ex = u.GetWindowLongW(app._hwnd(), ticker.GWL_EXSTYLE)
        check("★ 真加了 WS_EX_TRANSPARENT（点击落到游戏里）",
              bool(ex & ticker.WS_EX_TRANSPARENT), hex(ex))

        blocked = []
        blocked.append(app._on_press(Ev(widget=app.canvas, x=10, y=10)) == "break")
        blocked.append(app._on_drag(Ev()) == "break")
        blocked.append(app._on_release(Ev()) == "break")
        blocked.append(app._on_double(Ev()) == "break")
        blocked.append(app._on_wheel(Ev(delta=120)) == "break")
        blocked.append(app._on_menu(Ev()) == "break")
        blocked.append(app._on_tape_press(Ev()) == "break")
        blocked.append(app._on_tape_release(Ev()) == "break")
        blocked.append(app._on_more_click() == "break")
        check("★ 所有鼠标入口都被吞掉（拖/点/双击/滚轮/菜单/滚动条/更多）",
              all(blocked), f"{sum(blocked)}/{len(blocked)}")
        check("吞掉之后窗口不会被拖走", app._drag is None)
        check("游戏模式不落盘（重启回到正常）", "game_mode" not in app.cfg)

        app.toggle_game_mode()
        pump(app, 300)
        ex2 = u.GetWindowLongW(app._hwnd(), ticker.GWL_EXSTYLE)
        check("关掉后穿透也撤了", not (ex2 & ticker.WS_EX_TRANSPARENT), hex(ex2))
        check("指示也清了", str(app.game_label.cget("text")) == "")
        check("关掉后鼠标事件又能用",
              app._on_wheel(Ev(delta=120)) == "break" and app._drag is None)

        # ---------------------------------------------------- 3. 菜单热键 --
        print("\n=== 右键菜单显示真实热键 ===")
        app._update_hotkey_hint({"toggle": "Ctrl+Alt+H", "menu": "Ctrl+Alt+M",
                                 "symbols": "Ctrl+Alt+K", "click": "Ctrl+Alt+P",
                                 "game": "Ctrl+Alt+G"})
        pump(app, 200)
        hide_label = str(app.menu.entrycget(app._mi_hide_idx, "label"))
        check("★「隐藏窗口」项直接写着组合键", "Ctrl+Alt+H" in hide_label, hide_label)
        game_label = str(app.menu.entrycget(app._mi_game_idx, "label"))
        check("★「游戏模式」项也写着组合键", "Ctrl+Alt+G" in game_label, game_label)
        hk = [app._hk_menu.entrycget(i, "label") for i in range(app._hk_menu.index("end") + 1)]
        check("「热键」子菜单列全 6 个功能（含全品种扫盘）", len(hk) == 6, " / ".join(hk))
        check("子菜单里每个都带组合键",
              all(any(k in one for k in ("Ctrl+Alt", "未注册")) for one in hk))

        # 热键顺延之后菜单要跟着变（用户就是被这个坑过：按原键没反应）
        app._update_hotkey_hint({"toggle": "Ctrl+Shift+Alt+H", "menu": "Ctrl+Shift+Alt+M",
                                 "symbols": "Ctrl+Alt+Y", "click": "Ctrl+Shift+Alt+P",
                                 "game": "Ctrl+Alt+G"})
        hide_label2 = str(app.menu.entrycget(app._mi_hide_idx, "label"))
        check("★ 热键顺延后菜单显示的是真实生效的那个",
              "Ctrl+Shift+Alt+H" in hide_label2, hide_label2)

        # ---------------------------------------------------- 4. 榜单下拉 --
        print("\n=== 选择品种：榜单下拉改成内部展开 ===")
        app._market_overview = {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "topVolume": [{"base": f"VOL{i}", "change": i * 1.0} for i in range(1, 11)],
            "topGainers": [{"base": f"GAI{i}", "change": i * 2.0} for i in range(1, 11)],
            "topLosers": [{"base": f"LOS{i}", "change": -i * 2.0} for i in range(1, 11)],
            "topOI": [{"base": f"OI{i}", "change": i * 3.0} for i in range(1, 11)],
        }
        app.open_symbols()
        pump(app, 900)                      # 等 poll 重建榜单面板
        win = app._sym_win
        check("选择器打开了", win is not None and win.winfo_exists())

        tops = [w for w in all_widgets(win)
                if isinstance(w, tk.Label) and str(w.cget("text")).endswith("▾")]
        check("四个榜单下拉入口都在", len(tops) == 4, str([str(t.cget("text")) for t in tops]))

        tops[0].event_generate("<Button-1>")
        pump(app, 400)
        lb = app._pick_box
        check("★ 点开后列表展开了", lb is not None and lb.winfo_exists())
        check("★ 列表就在对话框里（不是独立小窗口）",
              lb is not None and lb.winfo_toplevel() is win)
        check("★ 没有任何独立弹窗（这就是以前「分离」的根源）",
              len([w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]) == 1,
              f"{len([w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)])} 个 Toplevel")
        check("展开的是前 10", lb is not None and lb.size() == 10, f"{lb.size() if lb else 0} 项")
        check("标题箭头变成了 ▴",
              any(str(w.cget("text")).endswith("▴")
                  for w in all_widgets(win) if isinstance(w, tk.Label)))

        # 单击一项 = 加进对话框的自选列表，列表不关
        box = [w for w in all_widgets(win) if isinstance(w, tk.Listbox) and w is not lb]
        before = box[0].size() if box else -1
        lb.selection_set(0)
        lb.event_generate("<ButtonRelease-1>")
        pump(app, 600)                      # 单击推迟 260ms 才执行
        after = box[0].size() if box else -1
        check("★ 单击列表项就加进自选（列表不关）", after == before + 1, f"{before} -> {after}")
        check("加进去的是列表里那一项", box[0].get(after - 1) == "VOL1",
              box[0].get(after - 1) if after > 0 else "-")
        check("列表还开着", app._pick_box is not None)

        # 点同一组标题 → 收起；点另一组 → 前一组自动收起（手风琴）
        # ⚠️ 不能按"文字是 ▾ 的 Label"来找标题：展开后它变成 ▴ 了，序号会错位。
        #    直接拿面板里存着的控件引用，稳。
        rows = {k: v["row"] for k, v in app._board_panels.items()}
        check("四组面板都登记了", len(rows) == 4, str(sorted(rows)))

        rows["topVolume"].event_generate("<Button-1>")
        pump(app, 400)
        check("★ 点第二次收起这一组", app._pick_box is None and app._board_open is None,
              f"open={app._board_open}")

        rows["topVolume"].event_generate("<Button-1>")
        pump(app, 400)
        first_lb = app._pick_box
        rows["topGainers"].event_generate("<Button-1>")
        pump(app, 400)
        check("★ 换一组时上一组自动收起（手风琴）",
              app._pick_box is not None and app._pick_box is not first_lb
              and app._board_open == "topGainers", str(app._board_open))
        check("同一时刻只有一个榜单列表在展开",
              len([w for w in all_widgets(win) if isinstance(w, tk.Listbox)]) == 2,
              "1 个自选 + 1 个展开的榜单")

        app._close_pick_list()
        pump(app, 300)
        check("_close_pick_list 能收起（老调用点不用改）",
              app._pick_box is None and app._board_open is None)

        scan_btns = [w for w in all_widgets(win) if isinstance(w, tk.Label)
                     and "全品种扫盘" in str(w.cget("text"))]
        check("→ 右下角有「全品种扫盘」入口", len(scan_btns) >= 1,
              f"{len(scan_btns)} 个: {[str(w.cget('text')) for w in scan_btns]}")

        # ★ 回归：某组榜单**展开时**，底部按钮不许被挤出窗口（踩过：466 高度时
        #   「保存并应用」直接跑到窗口外面看不见了）
        win.update_idletasks()
        h = win.winfo_height()
        bottom = win.winfo_rooty() + h
        feet = [w for w in all_widgets(win)
                if isinstance(w, (tk.Label, tk.Button))
                and str(w.cget("text")) in ("保存并应用", "取消", "全品种扫盘 ▸")]
        out_of_view = [str(w.cget("text")) for w in feet
                       if w.winfo_rooty() + w.winfo_height() > bottom + 2]
        check("★ 展开一组榜单后，底部按钮仍在窗口内", not out_of_view,
              f"窗口高 {h}，跑出去的: {out_of_view}")

        # 关对话框：不应该留下任何飘着的列表
        app._board_panels["topVolume"]["row"].event_generate("<Button-1>")
        pump(app, 400)
        cancel = widgets_by_text(win, tk.Button, "取消")
        check("有取消按钮", len(cancel) == 1)
        click_widget(cancel[0])
        pump(app, 500)
        toplevels = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
        check("★ 关掉选择器后没有任何残留窗口", len(toplevels) == 0,
              f"{len(toplevels)} 个")

        emit(f"\n{passed}/{total} 项通过")
    except Exception:
        emit("崩溃：\n" + traceback.format_exc())
    finally:
        try:
            # 原样还回去（包括 position / hotkeys —— 测试不该动用户的配置）
            for k, v in orig.items():
                if v is None:
                    app.cfg.pop(k, None)
                else:
                    app.cfg[k] = v
            ticker.save_config(app.cfg)
            if orig_text:
                with open(ticker.CONFIG_PATH, "w", encoding="utf-8") as fh:
                    fh.write(orig_text)          # 连键顺序都恢复成原样
            print("已还原 config.json:", {k: orig.get(k) for k in ("symbols", "hotkeys")})
        except Exception as exc:
            print("恢复配置失败:", exc)
        try:
            app._alerts.stop()
        except Exception:
            pass
        try:
            app.root.destroy()
        except Exception:
            pass

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
