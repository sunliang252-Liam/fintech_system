"""
analysis_layer/run_dcf_hs300.py
--------------------------------
对 HS300 全部股票跑 DCF，输出汇总表并导出 CSV。
"""
import sys, os, json, urllib.request
sys.path.insert(0, "/home/liam-sun/fintech_system")
os.chdir("/home/liam-sun/fintech_system")

from analysis_layer.dcf import DCFValuation

TOKEN = os.getenv("TUSHARE_TOKEN", "")

def ts_get(api_name, **params):
    url = "https://api.tushare.pro"
    payload = json.dumps({"api_name": api_name, "token": TOKEN, "params": params}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    fields = res["data"]["fields"]
    return [dict(zip(fields, row)) for row in res["data"]["items"]]

# 拉最新市值和股本
print("拉取最新市值和股本...")
rows = ts_get("daily_basic", trade_date="20260430",
              fields="ts_code,close,total_mv,total_share")
market = {r["ts_code"]: r for r in rows if r["total_mv"]}
print(f"获取到 {len(market)} 只")

# 读 HS300 名单
with open("/tmp/hs300_codes.json") as f:
    codes = json.load(f)

# 批量 DCF
results = []
for i, code in enumerate(codes, 1):
    m = market.get(code)
    if not m:
        print(f"[{i:>3}/{len(codes)}] {code}  无市值数据，跳过")
        continue

    shares = m["total_share"]   # 万股
    mc     = m["total_mv"] / 1e4  # 亿元
    price  = m["close"]

    r = DCFValuation(code).calc_fair_value(total_shares_wan=shares)
    if "error" in r:
        print(f"[{i:>3}/{len(codes)}] {code}  {r['error']}")
        continue

    fv  = r["fair_per_share"]
    gap = round((fv / price - 1) * 100, 1) if fv and price else None
    results.append({
        "ts_code":       code,
        "当前价":        price,
        "DCF估值":       fv,
        "空间%":         gap,
        "市值亿":        round(mc, 1),
        "基准FCF亿":     r["base_fcf_yi"],
        "增长率%":       round(r["growth_rate"] * 100, 1),
        "EV亿":          r["ev_yi"],
        "净债务亿":      round(r["debt_yi"] - r["cash_yi"], 1),
    })
    print(f"[{i:>3}/{len(codes)}] {code}  现价={price}  DCF={fv}  空间={gap}%", flush=True)

# 排序输出
results.sort(key=lambda x: x["空间%"] or -999, reverse=True)

print(f"\n{'='*70}")
print(f"  HS300 DCF 估值汇总（按上行空间排序）  共 {len(results)} 只")
print(f"{'='*70}")
print(f"{'代码':<12}{'当前价':>7}  {'DCF估值':>8}  {'空间':>7}  {'FCF':>7}  {'增长率':>6}")
print("-" * 60)
for r in results:
    gap_str = f"{r['空间%']:+.1f}%" if r['空间%'] else "N/A"
    print(f"{r['ts_code']:<12}{r['当前价']:>6.2f}元  {r['DCF估值']:>7.2f}元  "
          f"{gap_str:>7}  {r['基准FCF亿']:>5.1f}亿  {r['增长率%']:>5.1f}%")

# 导出 CSV
import csv, os
os.makedirs("data", exist_ok=True)
out = "data/dcf_hs300_results.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=results[0].keys())
    w.writeheader()
    w.writerows(results)
print(f"\n已导出: {out}")
