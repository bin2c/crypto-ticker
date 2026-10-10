# -*- coding: utf-8 -*-
"""行情工具新增功能的离线自测（不启动 GUI、不打开浏览器）。"""
import sys
import ticker

print("=== TradingView 地址 ===")
cases = [
    ("BTC", "USDT", "perp", "BINANCE"),
    ("BTC", "USDT", "spot", "BINANCE"),
    ("DOGE", "USDT", "perp", "BINANCE"),
    ("SOL", "USDT", "perp", "OKX"),
]
for base, quote, market, ex in cases:
    print(f"  {market:5} {ex:8} -> {ticker.tradingview_url(base, quote, market, ex)}")

print()
print("=== 币种解析（BTC / btc-usdt / 1000PEPE / doge-usdt / ETHUSDT） ===")
for raw in ["BTC", "btc-usdt", "1000PEPE", "doge/usdt", "ETHUSDT", "  sol  "]:
    print(f"  {raw!r:14} -> {ticker.normalize_symbol(raw, 'USDT')}")

print()
print("=== 列表去重与合并 ===")
print("  ", ticker.build_pairs(["BTC", "btc", "ETH", "BTCUSDT", "SOL-USDT"], "USDT"))
print("   空列表回退:", ticker.build_pairs([], "USDT"))

print()
print("=== 双击命中测试（构造行几何） ===")

class Fake:
    _row_geom = [
        (2, 21, "BTC", "USDT"),
        (21, 40, "ETH", "USDT"),
        (40, 59, "SOL", "USDT"),
    ]

for y in [0, 1, 2, 10, 20, 21, 30, 39, 40, 50, 58, 59, 100]:
    hit = ticker.TickerApp._row_at(Fake(), y)
    label = f"{hit[0]}" if hit else "None（空白/表头）"
    print(f"  y={y:3} -> {label}")

# 断言关键边界
assert ticker.TickerApp._row_at(Fake(), 2) == ("BTC", "USDT")
assert ticker.TickerApp._row_at(Fake(), 20) == ("BTC", "USDT")
assert ticker.TickerApp._row_at(Fake(), 21) == ("ETH", "USDT")
assert ticker.TickerApp._row_at(Fake(), 58) == ("SOL", "USDT")
assert ticker.TickerApp._row_at(Fake(), 59) is None
assert ticker.TickerApp._row_at(Fake(), 0) is None
print("\n边界断言全部通过 ✓")

print()
print("=== 默认配置含新键 ===")
for k in ("market", "tv_exchange"):
    print(f"  {k} = {ticker.DEFAULT_CONFIG.get(k)!r}")

print()
print("=== 热键定义 ===")
for name, cands in ticker.HOTKEY_DEFS.items():
    print(f"  {name:8} {ticker.HOTKEY_NAMES.get(name,'?'):6} 候选: {[c[0] for c in cands]}")
