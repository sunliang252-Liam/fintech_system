"""tushare/quarterly/income.py — 利润表增量更新（原始 Tushare 字段，主键 ts_code+end_date+report_type）"""
from __future__ import annotations
import time
from ..client import get_pro
from ... import db, logger

log = logger.get("income")

_CONF = ("ts_code", "end_date", "report_type")


def run(codes: list[str], period: str, sleep: float = 0.5) -> int:
    pro  = get_pro()
    conn = db.get_conn()
    n    = 0
    try:
        for code in codes:
            time.sleep(sleep)
            try:
                df = pro.income(ts_code=code, period=period, report_type="1")
                if df is None or df.empty:
                    continue
                rows = df[df["end_date"] == period].to_dict("records")
                n += db.upsert(conn, "income_statement", rows, _CONF)
            except Exception as e:
                conn.rollback()
                log.warning(f"[{code}] income 跳过: {e}")
    finally:
        db.put_conn(conn)
    log.info(f"income_statement 写入 {n} 行")
    return n
