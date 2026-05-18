"""tushare/quarterly/balance_sheet.py — 资产负债表增量更新"""
from __future__ import annotations
import time
from ..client import ts_post
from ... import db, logger

log = logger.get("balance_sheet")


def _map(r: dict) -> dict:
    assets = r.get("total_assets") or 0
    liab   = r.get("total_liab")   or 0
    return {
        "ts_code":                r["ts_code"],
        "report_year":            int(r["end_date"][:4]),
        "cash":                   r.get("money_cap"),
        "accounts_receivable":    r.get("accounts_receiv"),
        "notes_receivable":       r.get("notes_receiv"),
        "inventory":              r.get("inventories"),
        "current_assets":         r.get("total_cur_assets"),
        "fixed_assets":           r.get("fix_assets"),
        "construction_wip":       r.get("cip"),
        "intangible_assets":      r.get("intan_assets"),
        "noncurrent_assets":      r.get("total_nca"),
        "total_assets":           assets,
        "accounts_payable":       r.get("acct_payable"),
        "contract_liability":     r.get("contract_liab"),
        "short_term_debt":        r.get("st_borr"),
        "current_liabilities":    r.get("total_cur_liab"),
        "long_term_debt":         r.get("lt_borr"),
        "noncurrent_liabilities": r.get("total_ncl"),
        "total_liabilities":      liab,
        "equity_parent":          r.get("total_hldr_eqy_exc_min_int"),
        "equity_minority":        r.get("minority_int"),
        "total_equity":           r.get("total_hldr_eqy_inc_min_int"),
        "asset_liability_ratio":  round(liab / assets, 4) if assets else None,
    }


def run(codes: list[str], period: str, sleep: float = 0.5) -> int:
    conn = db.get_conn()
    n = 0
    try:
        for code in codes:
            time.sleep(sleep)
            try:
                rows_raw = ts_post("balancesheet", ts_code=code, period=period, report_type="1")
                rows = [_map(r) for r in rows_raw if r.get("end_date", "").startswith(period[:4])]
                n += db.upsert(conn, "balance_sheet", rows, ("ts_code", "report_year"))
            except Exception as e:
                conn.rollback()
                log.warning(f"[{code}] balance_sheet 跳过: {e}")
    finally:
        db.put_conn(conn)
    log.info(f"balance_sheet 写入 {n} 行")
    return n
