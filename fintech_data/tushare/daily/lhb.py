"""tushare/daily/lhb.py — 龙虎榜数据增量更新（近3个月滚动窗口）"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from ..client import get_pro
from ... import db, logger

log = logger.get("lhb")

WINDOW_DAYS = 90


def run() -> dict:
    pro  = get_pro()
    conn = db.get_conn()

    end   = datetime.today()
    start = end - timedelta(days=WINDOW_DAYS)

    n_list = n_inst = n_branch = 0

    try:
        current = start
        while current <= end:
            trade_date = current.strftime("%Y%m%d")
            current += timedelta(days=1)

            # top_list
            try:
                df = pro.top_list(trade_date=trade_date)
                if df is not None and not df.empty:
                    n_list += db.upsert(conn, "stock_top_list",
                                        df.to_dict("records"),
                                        ("trade_date", "ts_code", "reason"))
            except Exception as e:
                if "每分钟" not in str(e):
                    log.warning(f"[{trade_date}][top_list] {e}")
            time.sleep(0.3)

            # top_inst → 同时写 stock_top_inst 和 stock_lhb_branches_3m
            try:
                df = pro.top_inst(trade_date=trade_date)
                if df is not None and not df.empty:
                    rows = df.to_dict("records")
                    n_inst   += db.upsert(conn, "stock_top_inst",      rows, ("trade_date", "ts_code", "exalter"))
                    n_branch += db.upsert(conn, "stock_lhb_branches_3m", rows, ("trade_date", "ts_code", "exalter"))
            except Exception as e:
                if "每分钟" not in str(e):
                    log.warning(f"[{trade_date}][top_inst] {e}")
            time.sleep(0.3)
    finally:
        db.put_conn(conn)

    log.info(f"lhb 完成: top_list={n_list} top_inst={n_inst} branches={n_branch}")
    return {"top_list": n_list, "top_inst": n_inst, "branches": n_branch}
