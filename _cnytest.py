# -*- coding: utf-8 -*-
"""中文币行情回归测试。

背景：json.dumps 默认 ensure_ascii=True，会把「龙虾」转义成字面文本
\\u9f99\\u867e，币安收到后当成无效符号，整个批量请求返回 400 ——
不只是中文币拿不到，同一批里的 BTC/ETH 也会一起掉线。
"""

import json
import urllib.parse

import ticker

CN = ["龙虾", "牛来"]
pairs = ticker.build_pairs(CN + ["BTC"], "USDT")
print("交易对:", pairs)

# 1) URL 里必须是真正的 UTF-8 百分号编码，不能是字面的 \uXXXX
symbols = [b + q for b, q in pairs]
query = urllib.parse.quote(
    json.dumps(symbols, separators=(",", ":"), ensure_ascii=False))
print("\n编码后的 query:", query[:80], "…")
assert "\\u" not in query, "仍在用 \\uXXXX 转义，币安会当成无效符号"
assert "%E9%BE%99%E8%99%BE" in query, "「龙虾」没有编码成正确 UTF-8"
print("UTF-8 编码断言通过 ✔")

# 2) 批量一次就能拿到全部（不再退化成逐个查）
rows, src = ticker.fetch_all(pairs, "perp", 20)
print(f"\n数据源: {src}")
for key, val in rows.items():
    print(f"   {str(key):<16} {ticker.fmt_price(val['price']):>12}  {val['change']:+.2f}%")

assert len(rows) == len(pairs), f"只拿到 {len(rows)}/{len(pairs)} 个"
print(f"\n{len(rows)}/{len(pairs)} 全部拿到 ✔")

# 3) 币安清单里确实有这些中文符号
ov = ticker.load_market_overview()
missing = [c for c in CN if c not in (ov.get("symbols") or [])]
assert not missing, f"清单里找不到: {missing}"
print(f"清单包含所有中文币 ✔")

print("\n全部通过")
