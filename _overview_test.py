# -*- coding: utf-8 -*-
"""合约总览与模糊匹配的离线验证。"""
import ticker

ov = ticker.load_market_overview(force=True)
print(f"合约数: {len(ov['symbols'])}\n")


def show(title, items):
    print(f"  {title}")
    for i in items:
        print(f"     {i['base']:<10} {i['change']:+7.2f}%   成交额 {i['volume']/1e8:8.2f} 亿")


show("成交量前3:", ov["topVolume"])
show("涨幅前3 :", ov["topGainers"])
show("跌幅前3 :", ov["topLosers"])

print("\n=== 模糊匹配（按成交额排序）===")
for q in ["E", "B", "ET", "1000", "SO", "PEP"]:
    print(f"  {q!r:6} -> {ticker.match_symbols(q, ov['symbols'])}")

print("\n=== 榜单里没有重复项，且每组 10 个 ===")
for name in ("topVolume", "topGainers", "topLosers"):
    bases = [i["base"] for i in ov[name]]
    assert len(bases) == len(set(bases)), f"{name} 有重复"
    assert len(bases) == 10, f"{name} 不是 10 个，而是 {len(bases)}"
    print(f"  {name}: {len(bases)} 个  {bases[:4]}…  OK")

print("\n=== 成交量榜已剔除大市值币 ===")
big = set(ov.get("bigCaps") or [])
vol_bases = [i["base"] for i in ov["topVolume"]]
leaked = [b for b in vol_bases if b in big]
assert not leaked, f"成交量榜混入了大市值币: {leaked}"
print(f"  市值前 {len(big)} 名: {sorted(big)[:8]}…")
print(f"  成交量榜: {vol_bases}  无大市值币 ✓")

print("\n=== 涨跌幅符号正确 ===")
g = ov["topGainers"]
l = ov["topLosers"]
assert all(i["change"] > 0 for i in g), "涨幅榜出现负值"
assert all(i["change"] < 0 for i in l), "跌幅榜出现正值"
print(f"  涨幅榜全为正: {[round(i['change'],1) for i in g]}")
print(f"  跌幅榜全为负: {[round(i['change'],1) for i in l]}")

print("\n全部断言通过 ✓")
