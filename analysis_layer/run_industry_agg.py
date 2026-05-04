"""
analysis_layer/run_industry_agg.py
----------------------------------
执行 HS300 估值并生成行业聚合报告。
"""
import sys, os, json, urllib.request, csv
import pandas as pd
sys.path.insert(0, "/home/liam-sun/fintech_system")
os.chdir("/home/liam-sun/fintech_system")

from analysis_layer.valuation import UnifiedValuation

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

print("1. 准备数据...")
rows   = ts_get("daily_basic", trade_date="20260430",
                fields="ts_code,close,total_mv,total_share")
market = {r["ts_code"]: r for r in rows if r["total_mv"]}

stock_rows = ts_get("stock_basic", exchange="", list_status="L",
                    fields="ts_code,name,industry")
stock_info = {r["ts_code"]: r for r in stock_rows}

with open("/tmp/hs300_codes.json") as f:
    codes = json.load(f)

print(f"2. 开始对 {len(codes)} 只股票进行估值...")
engine = UnifiedValuation()
results = []

for i, code in enumerate(codes, 1):
    m = market.get(code)
    if not m: continue
    
    shares  = m["total_share"]
    price   = m["close"]
    si      = stock_info.get(code, {})
    industry= si.get("industry", "未知")

    r = engine.calc(code, industry, shares, current_price=price)
    if "error" in r: continue

    fv  = r["fair_per_share"]
    gap = round((fv / price - 1) * 100, 1) if (fv is not None and price) else None
    
    results.append({
        "ts_code":   code,
        "name":      si.get("name", ""),
        "industry":  industry,
        "price":     price,
        "valuation": fv,
        "upside":    gap,
        "method":    r["方法"]
    })

df = pd.DataFrame(results)

print("3. 生成行业聚合报告...")
agg = df.groupby("industry").agg(
    股票数量=('ts_code', 'count'),
    平均空间=('upside', 'mean'),
    中位数空间=('upside', 'median'),
    最高空间=('upside', 'max'),
    最低空间=('upside', 'min')
).sort_values("平均空间", ascending=False)

# 保存文件
os.makedirs("data", exist_ok=True)
out_raw = "data/valuation_hs300_v2.csv"
out_agg = "data/valuation_industry_agg.csv"

df.to_csv(out_raw, index=False, encoding="utf-8-sig")
agg.to_csv(out_agg, encoding="utf-8-sig")

print(f"\n测算完成！")
print(f"明细文件: {out_raw}")
print(f"聚合报告: {out_agg}")

print("\n--- 行业潜力榜 Top 10 (平均空间) ---")
print(agg.head(10))
