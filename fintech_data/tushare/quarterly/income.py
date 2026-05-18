"""tushare/quarterly/income.py — 利润表增量更新"""
from __future__ import annotations
import time
from ..client import ts_post
from ... import db, logger

log = logger.get("income")


def _map(r: dict) -> dict:
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


def run(codes: list[str], period: str, sleep: float = 0.5) -> int:
    conn = db.get_conn()
    n = 0
    try:
        for code in codes:
            time.sleep(sleep)
            try:
                rows_raw = ts_post("income", ts_code=code, period=period, report_type="1")
                rows = [_map(r) for r in rows_raw if r.get("end_date", "").startswith(period[:4])]
                n += db.upsert(conn, "income_statement", rows, ("ts_code", "report_year"))
            except Exception as e:
                conn.rollback()
                log.warning(f"[{code}] income 跳过: {e}")
    finally:
        db.put_conn(conn)
    log.info(f"income_statement 写入 {n} 行")
    return n
