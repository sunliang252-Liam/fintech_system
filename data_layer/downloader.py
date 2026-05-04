"""
analysis_layer/downloader.py
-----------------------------
从 Tushare API 下载三大财报，字段对齐后写入
income_statement / cash_flow_statement / balance_sheet 三张表。
"""

from __future__ import annotations
import os, json, time, urllib.request
import psycopg2
from psycopg2.extras import execute_values

TOKEN = os.getenv("TUSHARE_TOKEN", "")

_DSN = {
    "host":     os.getenv("PG_HOST",     "localhost"),
    "port":     int(os.getenv("PG_PORT", "5432")),
    "dbname":   os.getenv("PG_DB",       "fintech_db"),
    "user":     os.getenv("PG_USER",     "postgres"),
    "password": os.getenv("PG_PASSWORD", ""),
}

PERIODS = ["20201231", "20211231", "20221231", "20231231", "20241231"]


def _ts_get(api_name: str, **params) -> list[dict]:
    url = "https://api.tushare.pro"
    payload = json.dumps({"api_name": api_name, "token": TOKEN, "params": params}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    if res["code"] != 0:
        raise RuntimeError(f"[{api_name}] {res['msg']}")
    fields = res["data"]["fields"]
    return [dict(zip(fields, row)) for row in res["data"]["items"]]


def _upsert(conn, table: str, rows: list[dict], conflict_cols: tuple):
    if not rows:
        return 0
    # 同一批次可能有重复 conflict key，保留最后一条
    seen, deduped = set(), []
    for r in rows:
        key = tuple(r[c] for c in conflict_cols)
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    cols = list(deduped[0].keys())
    vals = [[r[c] for c in cols] for r in deduped]
    conf = ", ".join(conflict_cols)
    upd  = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in conflict_cols)
    sql  = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s ON CONFLICT ({conf}) DO UPDATE SET {upd}"
    with conn.cursor() as cur:
        execute_values(cur, sql, vals)
    conn.commit()
    return len(deduped)


def _map_income(r: dict) -> dict:
    revenue = r.get("revenue") or r.get("total_revenue") or 0
    cost    = r.get("oper_cost") or 0
    gross   = revenue - cost
    return {
        "ts_code":             r["ts_code"],
        "report_year":         int(r["end_date"][:4]),
        "revenue":             revenue,
        "cost_of_revenue":     cost,
        "gross_profit":        gross,
        "gross_margin":        round(gross / revenue, 4) if revenue else None,
        "selling_expense":     r.get("sell_exp"),
        "admin_expense":       r.get("admin_exp"),
        "rd_expense":          r.get("rd_exp"),
        "finance_expense":     r.get("fin_exp"),
        "operating_profit":    r.get("operate_profit"),
        "total_profit":        r.get("total_profit"),
        "net_profit":          r.get("n_income"),
        "net_profit_parent":   r.get("n_income_attr_p"),
        "net_profit_minority": r.get("minority_gain"),
        "eps_basic":           r.get("basic_eps"),
    }


def _map_balance(r: dict) -> dict:
    assets = r.get("total_assets") or 0
    liab   = r.get("total_liab")   or 0
    return {
        "ts_code":               r["ts_code"],
        "report_year":           int(r["end_date"][:4]),
        "cash":                  r.get("money_cap"),
        "accounts_receivable":   r.get("accounts_receiv"),
        "notes_receivable":      r.get("notes_receiv"),
        "inventory":             r.get("inventories"),
        "current_assets":        r.get("total_cur_assets"),
        "fixed_assets":          r.get("fix_assets"),
        "construction_wip":      r.get("cip"),
        "intangible_assets":     r.get("intan_assets"),
        "noncurrent_assets":     r.get("total_nca"),
        "total_assets":          assets,
        "accounts_payable":      r.get("acct_payable"),
        "contract_liability":    r.get("contract_liab"),
        "short_term_debt":       r.get("st_borr"),
        "current_liabilities":   r.get("total_cur_liab"),
        "long_term_debt":        r.get("lt_borr"),
        "noncurrent_liabilities":r.get("total_ncl"),
        "total_liabilities":     liab,
        "equity_parent":         r.get("total_hldr_eqy_exc_min_int"),
        "equity_minority":       r.get("minority_int"),
        "total_equity":          r.get("total_hldr_eqy_inc_min_int"),
        "asset_liability_ratio": round(liab / assets, 4) if assets else None,
    }


def _map_cashflow(r: dict) -> dict:
    op_cf   = r.get("n_cashflow_act") or 0
    net_pft = r.get("net_profit")     or 0
    return {
        "ts_code":              r["ts_code"],
        "report_year":          int(r["end_date"][:4]),
        "operating_inflow":     r.get("c_inf_fr_operate_a"),
        "operating_outflow":    r.get("st_cash_out_act"),
        "operating_cashflow":   op_cf,
        "investing_inflow":     r.get("stot_inflows_inv_act"),
        "investing_outflow":    r.get("stot_out_inv_act"),
        "investing_cashflow":   r.get("n_cashflow_inv_act"),
        "capex":                r.get("c_pay_acq_const_fiolta"),
        "financing_inflow":     r.get("stot_cash_in_fnc_act"),
        "financing_outflow":    r.get("stot_cashout_fnc_act"),
        "financing_cashflow":   r.get("n_cash_flows_fnc_act"),
        "net_cash_change":      r.get("n_incr_cash_cash_equ"),
        "ending_cash":          r.get("c_cash_equ_end_period"),
        "cashflow_profit_ratio":round(op_cf / net_pft, 4) if net_pft else None,
    }


def download_stock(ts_code: str, periods: list[str] = PERIODS, delay: float = 0.5) -> dict:
    conn = psycopg2.connect(**_DSN)
    counts = {"income": 0, "balance": 0, "cashflow": 0}

    for period in periods:
        for api, mapper, table, conf_key in [
            ("income",       _map_income,   "income_statement",    ("ts_code", "report_year")),
            ("balancesheet", _map_balance,  "balance_sheet",       ("ts_code", "report_year")),
            ("cashflow",     _map_cashflow, "cash_flow_statement", ("ts_code", "report_year")),
        ]:
            time.sleep(delay)
            try:
                raw  = _ts_get(api, ts_code=ts_code, period=period, report_type="1")
                rows = [mapper(r) for r in raw if r.get("end_date", "").startswith(period[:4])]
                n    = _upsert(conn, table, rows, conf_key)
                label = {"income": "income", "balancesheet": "balance", "cashflow": "cashflow"}[api]
                counts[label] += n
            except Exception as e:
                conn.rollback()
                print(f"  [{ts_code}][{period}][{api}] 跳过: {e}")

    conn.close()
    return counts


def download_batch(codes: list[str], periods: list[str] = PERIODS):
    for code in codes:
        print(f"下载 {code} ...", end="  ", flush=True)
        c = download_stock(code, periods)
        print(f"income={c['income']} balance={c['balance']} cashflow={c['cashflow']}")


if __name__ == "__main__":
    PILOT = ["600893.SH", "002572.SZ", "000932.SZ", "300450.SZ", "002078.SZ"]
    print(f"下载 {len(PILOT)} 只，年度：{PERIODS}\n")
    download_batch(PILOT)
    print("\n完成")
