#!/usr/bin/env python3
"""
rebuild_stock_cache.py
用 Tushare 申万三级行业指数成分 重建 .stock_cache.json
"""

import json, time
from pathlib import Path
import tushare as ts

CACHE_FILE = Path.home() / "Documents/Obsidian_Vault/02_Company_Analysis/.stock_cache.json"
TOKEN      = "291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a"

def market_of(code: str) -> str:
    c = code[:6]
    if c.startswith(("60", "68", "900")): return "SH"
    if c.startswith(("43", "83", "87", "92")): return "BJ"
    return "SZ"

def main():
    ts.set_token(TOKEN)
    pro = ts.pro_api()

    # Step 1: 全量股票列表
    print("Step 1: 获取全量股票...", flush=True)
    df_stocks = pro.stock_basic(fields="ts_code,symbol,name")
    result = {}
    for _, r in df_stocks.iterrows():
        code = str(r["symbol"]).zfill(6)
        result[code] = {
            "name":     r["name"],
            "industry": "未分类",
            "market":   market_of(code),
        }
    print(f"  共 {len(result)} 家", flush=True)

    # Step 2: 申万三级行业指数列表
    print("Step 2: 获取申万三级行业指数...", flush=True)
    df_idx = pro.index_basic(market="SW")
    df_l3  = df_idx[df_idx["category"] == "三级行业指数"].copy()
    # 去掉退市标记，清理名称
    df_l3["clean_name"] = df_l3["name"].str.replace(r"\(申万\)|\(退市\)", "", regex=True).str.strip()
    print(f"  共 {len(df_l3)} 个三级行业", flush=True)

    # Step 3: 逐行业拉成分股
    print("Step 3: 逐行业拉成分股...", flush=True)
    ok = fail = 0
    for i, row in df_l3.iterrows():
        idx_code  = row["ts_code"]
        idx_name  = row["clean_name"]
        try:
            df_mem = pro.index_member(index_code=idx_code, fields="con_code")
            if df_mem is not None and len(df_mem) > 0:
                for ts_code in df_mem["con_code"]:
                    code6 = ts_code[:6]
                    if code6 in result:
                        result[code6]["industry"] = idx_name
                ok += 1
            time.sleep(0.35)
        except Exception as e:
            fail += 1
            print(f"  ⚠️ 跳过 {idx_code} {idx_name}: {e}", flush=True)
            time.sleep(2)

        seq = ok + fail
        if seq % 50 == 0 or seq == len(df_l3):
            classified = sum(1 for v in result.values() if v["industry"] != "未分类")
            print(f"  进度 {seq}/{len(df_l3)} | 成功:{ok} 失败:{fail} | 已分类:{classified}", flush=True)
            CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

    CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    classified  = sum(1 for v in result.values() if v["industry"] != "未分类")
    n_industries = len(set(v["industry"] for v in result.values() if v["industry"] != "未分类"))
    print(f"\n完成 | 公司:{len(result)} | 已分类:{classified} | 行业数:{n_industries} | 失败:{fail}", flush=True)

if __name__ == "__main__":
    main()
