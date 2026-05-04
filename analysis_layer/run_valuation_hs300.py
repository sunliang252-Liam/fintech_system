"""
analysis_layer/run_valuation_hs300.py
--------------------------------------
对 HS300 全部股票按行业分派估值方法，输出汇总表并导出 CSV。
"""
import sys, os, json, urllib.request, csv
sys.path.insert(0, "/home/liam-sun/fintech_system")
os.chdir("/home/liam-sun/fintech_system")

from analysis_layer.valuation import UnifiedValuation, INDUSTRY_METHOD
from analysis_layer.valuation import INDUSTRY_METHOD

TOKEN = os.getenv("TUSHARE_TOKEN", "")

def ts_get(api_name, **params):
    url     = "https://api.tushare.pro"
    payload = json.dumps({"api_name": api_name, "token": TOKEN, "params": params}).encode()
    req     = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    fields = res["data"]["fields"]
    return [dict(zip(fields, row)) for row in res["data"]["items"]]


# ── 1. 拉最新行情（市值 / 股本 / 价格）────────────────────────────────────
print("拉取最新行情数据...")
rows   = ts_get("daily_basic", trade_date="20260430",
                fields="ts_code,close,total_mv,total_share")
market = {r["ts_code"]: r for r in rows if r["total_mv"]}
print(f"  获取到 {len(market)} 只")

# ── 2. 拉行业信息 ─────────────────────────────────────────────────────────
print("拉取行业信息...")
stock_rows = ts_get("stock_basic", exchange="", list_status="L",
                    fields="ts_code,name,industry")
stock_info = {r["ts_code"]: r for r in stock_rows}
print(f"  获取到 {len(stock_info)} 只")

# ── 3. 读 HS300 名单 ───────────────────────────────────────────────────────
with open("/tmp/hs300_codes.json") as f:
    codes = json.load(f)
print(f"HS300 名单：{len(codes)} 只\n")

# ── 4. 批量估值 ───────────────────────────────────────────────────────────
engine = UnifiedValuation()
results = []

for i, code in enumerate(codes, 1):
    m = market.get(code)
    if not m:
        print(f"[{i:>3}/{len(codes)}] {code}  无行情数据，跳过")
        continue

    shares  = m["total_share"]        # 万股
    mc      = m["total_mv"] / 1e4     # 亿元
    price   = m["close"]
    si      = stock_info.get(code, {})
    name    = si.get("name", "")
    industry= si.get("industry", "")

    r = engine.calc(code, industry, shares, current_price=price)

    if "error" in r:
        print(f"[{i:>3}/{len(codes)}] {code}  {r['error']}")
        continue

    fv  = r["fair_per_share"]
    gap = round((fv / price - 1) * 100, 1) if (fv is not None and price) else None

    results.append({
        "ts_code":   code,
        "名称":      name,
        "行业":      industry,
        "估值方法":  r["方法"],
        "当前价":    price,
        "估值":      fv,
        "空间%":     gap,
        "市值亿":    round(mc, 1),
        "基准FCF/净利亿": r.get("base_fcf_yi"),
        "增长率%":   round(r.get("growth_rate", 0) * 100, 1) if r.get("growth_rate") is not None else None,
        "EV亿":      r.get("ev_yi"),
        "净债务亿":  round((r.get("debt_yi") or 0) - (r.get("cash_yi") or 0), 1)
                     if r.get("debt_yi") is not None else None,
        # P/B+ROE 专属字段
        "当前PB":    r.get("cur_pb"),
        "合理PB":    r.get("fair_pb"),
        "ROE%":      r.get("roe_pct"),
        "每股净资产": r.get("book_per_share"),
    })
    print(f"[{i:>3}/{len(codes)}] {code} {name:6} [{r['方法'][:10]}]  "
          f"现价={price}  估值={fv}  空间={gap}%", flush=True)

# ── 5. 排序输出 ───────────────────────────────────────────────────────────
results.sort(key=lambda x: x["空间%"] or -999, reverse=True)

print(f"\n{'='*80}")
print(f"  HS300 多方法估值汇总（按上行空间排序）共 {len(results)} 只")
print(f"{'='*80}")
print(f"{'代码':<12}{'名称':<8}{'行业':<8}{'方法':<14}{'当前价':>7}{'估值':>8}{'空间':>7}")
print("-" * 70)
for r in results:
    gap_s = f"{r['空间%']:+.1f}%" if r['空间%'] is not None else "N/A"
    fv_s  = f"{r['估值']:.2f}" if r['估值'] is not None else "N/A"
    print(f"{r['ts_code']:<12}{r['名称']:<8}{r['行业']:<8}"
          f"{r['估值方法'][:12]:<14}{r['当前价']:>6.2f}元"
          f"{fv_s:>8}元  {gap_s:>7}")

# ── 6. 导出 CSV ───────────────────────────────────────────────────────────
os.makedirs("data", exist_ok=True)
out = "data/valuation_hs300.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=results[0].keys())
    w.writeheader()
    w.writerows(results)
print(f"\n已导出: {out}")

# ── 7. 方法分布统计 ───────────────────────────────────────────────────────
from collections import Counter
method_cnt = Counter(r["估值方法"].split("(")[0].strip() for r in results)
print("\n估值方法分布：")
for m, c in method_cnt.most_common():
    print(f"  {m:<20} {c} 只")
