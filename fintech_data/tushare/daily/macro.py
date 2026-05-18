"""tushare/daily/macro.py — SHIBOR / 期货 / 全球指数 增量更新"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from ..client import get_pro
from ... import db, logger

log = logger.get("macro")

FUTURES_CODES = ["LC.GFE", "NI.SHF", "CU.SHF", "AU.SHF", "SC.INE"]
GLOBAL_CODES  = ["NID.LME", "CAD.LME", "XAU", "USDX", "IXIC"]


def _last_date(conn, table: str, date_col: str) -> str:
    with conn.cursor() as cur:
        cur.execute(f"SELECT MAX({date_col}) FROM {table}")
        val = cur.fetchone()[0]
    if val is None:
        return (datetime.today() - timedelta(days=30)).strftime("%Y%m%d")
    return str(val).replace("-", "")


def _run_shibor(pro, conn, start: str, end: str) -> int:
    df = pro.shibor(start_date=start, end_date=end)
    if df is None or df.empty:
        return 0
    rows = df.to_dict("records")
    return db.upsert(conn, "macro_shibor", rows, ("date",))


def _run_futures(pro, conn, start: str, end: str) -> int:
    n = 0
    for code in FUTURES_CODES:
        try:
            df = pro.fut_daily(ts_code=code, start_date=start, end_date=end)
            if df is not None and not df.empty:
                n += db.upsert(conn, "macro_futures", df.to_dict("records"), ("ts_code", "trade_date"))
        except Exception as e:
            log.warning(f"fut_daily [{code}] 失败: {e}")
        time.sleep(0.5)
    return n


def _run_global(pro, conn, start: str, end: str) -> int:
    n = 0
    for code in GLOBAL_CODES:
        try:
            df = pro.index_global(ts_code=code, start_date=start, end_date=end)
            if df is not None and not df.empty:
                n += db.upsert(conn, "macro_global", df.to_dict("records"), ("ts_code", "trade_date"))
        except Exception as e:
            log.warning(f"index_global [{code}] 失败: {e}")
        time.sleep(0.5)
    return n


def run() -> dict:
    pro  = get_pro()
    conn = db.get_conn()
    end  = datetime.today().strftime("%Y%m%d")

    try:
        shibor_start   = _last_date(conn, "macro_shibor",  "date")
        futures_start  = _last_date(conn, "macro_futures", "trade_date")
        global_start   = _last_date(conn, "macro_global",  "trade_date")

        ns = _run_shibor(pro, conn, shibor_start, end)
        nf = _run_futures(pro, conn, futures_start, end)
        ng = _run_global(pro, conn, global_start, end)
    finally:
        db.put_conn(conn)

    log.info(f"macro 完成: shibor={ns} futures={nf} global={ng}")
    return {"shibor": ns, "futures": nf, "global": ng}
