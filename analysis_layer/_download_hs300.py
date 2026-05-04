import json, sys, os
sys.path.insert(0, "/home/liam-sun/fintech_system")
os.chdir("/home/liam-sun/fintech_system")

from data_layer.downloader import download_stock

with open("/tmp/hs300_codes.json") as f:
    codes = json.load(f)

PERIODS = ["20231231", "20241231", "20251231"]
total = len(codes)
ok, failed = 0, []

for i, code in enumerate(codes, 1):
    try:
        c = download_stock(code, periods=PERIODS, delay=0.3)
        ok += 1
        print(f"[{i:>3}/{total}] {code}  income={c['income']} balance={c['balance']} cashflow={c['cashflow']}", flush=True)
    except Exception as e:
        failed.append(code)
        print(f"[{i:>3}/{total}] {code}  失败: {e}", flush=True)

print(f"\n完成：成功={ok}  失败={len(failed)}")
if failed:
    print("失败列表:", failed)
