"""tushare/quarterly/detector.py — 检测是否有新年报待拉取"""
from __future__ import annotations
from datetime import datetime
from ... import db, logger

log = logger.get("detector")

# 格式 YYYYMMDD，对应 income_statement.end_date
ANNUAL_PERIOD = f"{datetime.today().year - 1}1231"


def get_all_codes(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ts_code FROM stock_basic ORDER BY ts_code")
        return [row[0] for row in cur.fetchall()]


def get_done_codes(conn, period: str) -> set[str]:
    """返回 income_statement 里已有指定 end_date 数据的 ts_code 集合。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ts_code FROM income_statement WHERE end_date = %s",
            (period,)
        )
        return {row[0] for row in cur.fetchall()}


def get_pending(conn, period: str | None = None) -> list[str]:
    """返回本年度年报还未入库的股票列表。"""
    p = period or ANNUAL_PERIOD
    all_codes  = get_all_codes(conn)
    done_codes = get_done_codes(conn, p)
    pending    = [c for c in all_codes if c not in done_codes]
    log.info(f"财报检测 period={p}: 全部 {len(all_codes)} 只，已有 {len(done_codes)} 只，待补 {len(pending)} 只")
    return pending
