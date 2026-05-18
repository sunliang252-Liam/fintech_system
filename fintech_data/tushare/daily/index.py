"""tushare/daily/index.py — 指数日线 + 沪深300历史 增量更新"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from ..client import get_pro
from ... import db, logger

log = logger.get("index")

INDEX_CODES = [
    ("000300.SH", "沪深300"),
    ("000016.SH", "上证50"),
    ("000905.SH", "中证500"),
    ("000852.SH", "中证1000"),
    ("399006.SZ", "创业板指"),
    ("000688.SH", "科创50"),
]


def _last_date(conn, table: str, ts_code: str | None = None) -> str:
    with conn.cursor() as cur:
        if ts_code:
            cur.execute(
                "SELECT MAX(trade_date) FROM index_daily_data WHERE ts_code = %s",
                (ts_code,)
            )
        else:
            cur.execute("SELECT MAX(trade_date) FROM hs300_history")
        val = cur.fetchone()[0]
    if val is None:
        return (datetime.today() - timedelta(days=365)).strftime("%Y%m%d")
    return str(val).replace("-", "")


def run() -> dict:
    pro  = get_pro()
    conn = db.get_conn()
    end  = datetime.today().strftime("%Y%m%d")
    nd   = 0
    nh   = 0

    try:
        for code, _ in INDEX_CODES:
            start = _last_date(conn, "index_daily_data", code)
            try:
                df = pro.index_daily(ts_code=code, start_date=start, end_date=end)
                if df is not None and not df.empty:
                    nd += db.upsert(conn, "index_daily_data", df.to_dict("records"),
                                    ("ts_code", "trade_date"))
            except Exception as e:
                log.warning(f"index_daily [{code}] 失败: {e}")
            time.sleep(0.3)

        hs300_start = _last_date(conn, "hs300_history")
        df = pro.index_daily(ts_code="000300.SH", start_date=hs300_start, end_date=end)
        if df is not None and not df.empty:
            nh = db.upsert(conn, "hs300_history", df.to_dict("records"),
                           ("ts_code", "trade_date"))
    finally:
        db.put_conn(conn)

    log.info(f"index 完成: index_daily={nd} hs300={nh}")
    return {"index_daily": nd, "hs300": nh}
