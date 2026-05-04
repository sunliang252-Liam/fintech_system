"""
analysis_layer/run_hs300_final.py
----------------------------------
执行 HS300 估值并生成完整报告（含公式说明，按空间排序）。
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

print("1. 准备数据 (从 Tushare 获取行情和基础信息)...")
# 获取最新行情
rows   = ts_get("daily_basic", trade_date="20260430",
                fields="ts_code,close,total_mv,total_share")
market = {r["ts_code"]: r for r in rows if r["total_mv"]}

# 获取行业信息
stock_rows = ts_get("stock_basic", exchange="", list_status="L",
                    fields="ts_code,name,industry")
stock_info = {r["ts_code"]: r for r in stock_rows}

# 读取 HS300 名单
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
    # 空间计算，保留一位小数
    gap = round((fv / price - 1) * 100, 1) if (fv is not None and price) else -999.0
    
    results.append({
        "ts_code":   code,
        "名称":      si.get("name", ""),
        "行业":      industry,
        "当前价":    price,
        "估值":      fv,
        "上行空间%": gap,
        "估值方法":  r["方法"],
        "计算公式":  r.get("公式", "")
    })

# 转换为 DataFrame 并按空间降序排列
df = pd.DataFrame(results)
df = df.sort_values("上行空间%", ascending=False)

# 保存文件
os.makedirs("data", exist_ok=True)
out_file = "data/hs300_valuation_final_v3.csv"
df.to_csv(out_file, index=False, encoding="utf-8-sig")

print(f"\n测算完成！")
print(f"完整报告已生成: {out_file}")

# 打印前 20 名预览
print("\n--- HS300 潜力股票预览 (Top 20) ---")
print(df[["ts_code", "名称", "行业", "当前价", "估值", "上行空间%"]].head(20).to_string(index=False))
