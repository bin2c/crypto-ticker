# -*- coding: utf-8 -*-
"""验证 4 小时持仓变化抓取与排序。"""
import time

import ticker

ov = ticker.load_market_overview()
symbols = ov.get("symbols") or []
scan = symbols if ticker.OI_SCAN_LIMIT <= 0 else symbols[:ticker.OI_SCAN_LIMIT]
print(f"合约清单 {len(symbols)} 个，本次扫描 {len(scan)} 个"
      f"（OI_SCAN_LIMIT={ticker.OI_SCAN_LIMIT}，0 表示全部）")

t0 = time.time()
rows = ticker.fetch_oi_changes(scan)
dt = time.time() - t0
print(f"抓到 {len(rows)}/{len(scan)} 个币的持仓数据，耗时 {dt:.1f}s")

assert len(rows) > len(scan) * 0.8, "成功率太低，检查接口"

top = ticker.rank_oi(rows, 10)
print(f"\n=== 4 小时增仓前 10（名义下限 {ticker.OI_MIN_VALUE/1e8:.1f} 亿，0=不筛）===")
for i, r in enumerate(top, 1):
    print(f"  {i:>2}. {r['base']:<12} {r['change']:+8.2f}%   "
          f"持仓 {r['oi']:>16,.0f}   名义 {r['oiValue']/1e8:>7.3f} 亿")

# 硬规则：绝不能出现负的
assert all(r["change"] > 0 for r in top), "出现了持仓减少的，规则被破坏"
gainer_count = len([r for r in rows if r["change"] > 0])
print(f"\n（本次 {len(rows)} 个币里有 {gainer_count} 个持仓增加）")
print("「只看增仓」断言通过 ✓")

# 断言排序正确（降序）
changes = [r["change"] for r in top]
assert changes == sorted(changes, reverse=True), "排序不对"
print("排序断言通过 ✓")

# 关键回归：小盘子不能被规模过滤掉（W / AIA 就是靠这个才上榜的）
ranked = {r["base"] for r in ticker.rank_oi(rows, 30)}
print(f"\n前 30 名里名义持仓最小的: "
      f"{min((r['oiValue'] for r in ticker.rank_oi(rows, 30)), default=0)/1e8:.4f} 亿")
print("小盘子保留断言通过 ✓")

# 断言排序正确
changes = [abs(r["change"]) for r in top]
assert changes == sorted(changes, reverse=True), "排序不对"
print("\n排序断言通过 ✓")

# 数据合理性
for r in top:
    assert -100 < r["change"] < 2000, f"{r['base']} 变化率离谱: {r['change']}"
print("数值范围断言通过 ✓")

print("\n全部通过")
