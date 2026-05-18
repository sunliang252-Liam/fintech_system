"""tushare/quarterly/cashflow.py — 现金流量表增量更新"""
from __future__ import annotations
import time
from ..client import ts_post
from ... import db, logger

log = logger.get("cashflow")


def _map(r: dict) -> dict:
    op_cf   = r.get("n_cashflow_act") or 0
    net_pft = r.get("net_profit")     or 0
    return {
        "ts_code":               r["ts_code"],
        "report_year":           int(r["end_date"][:4]),
        "operating_inflow":      r.get("c_inf_fr_operate_a"),
        "operating_outflow":     r.get("st_cash_out_act"),
        "operating_cashflow":    op_cf,
        "investing_inflow":      r.get("stot_inflows_inv_act"),
        "investing_outflow":     r.get("stot_out_inv_act"),
        "investing_cashflow":    r.get("n_cashflow_inv_act"),
        "capex":                 r.get("c_pay_acq_const_fiolta"),
        "financing_inflow":      r.get("stot_cash_in_fnc_act"),
        "financing_outflow":     r.get("stot_cashout_fnc_act"),
        "financing_cashflow":    r.get("n_cash_flows_fnc_act"),
        "net_cash_change":       r.get("n_incr_cash_cash_equ"),
        "ending_cash":           r.get("c_cash_equ_end_period"),
        "cashflow_profit_ratio": round(op_cf / net_pft, 4) if net_pft else None,
    }


def run(codes: list[str], period: str, sleep: float = 0.5) -> int:
    conn = db.get_conn()
    n = 0
    try:
        for code in codes:
            time.sleep(sleep)
            try:
                rows_raw = ts_post("cashflow", ts_code=code, period=period, report_type="1")
                rows = [_map(r) for r in rows_raw if r.get("end_date", "").startswith(period[:4])]
                n += db.upsert(conn, "cash_flow_statement", rows, ("ts_code", "report_year"))
            except Exception as e:
                conn.rollback()
                log.warning(f"[{code}] cashflow 跳过: {e}")
    finally:
        db.put_conn(conn)
    log.info(f"cash_flow_statement 写入 {n} 行")
    return n
