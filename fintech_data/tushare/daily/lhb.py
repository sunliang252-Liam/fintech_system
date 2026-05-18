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

            for api, table, conf in [
                (pro.top_list,    "stock_top_list",      ("trade_date", "ts_code")),
                (pro.top_inst,    "stock_top_inst",      ("trade_date", "ts_code", "exalter")),
            ]:
                try:
                    df = api(trade_date=trade_date)
                    if df is not None and not df.empty:
                        n = db.upsert(conn, table, df.to_dict("records"), conf)
                        if table == "stock_top_list":
                            n_list += n
                        else:
                            n_inst += n
                except Exception as e:
                    if "每分钟" not in str(e):
                        log.warning(f"[{trade_date}][{table}] {e}")
                time.sleep(0.3)

            # 龙虎榜营业部数据（按月查效率更高）
            if current.day == 1 or current == start + timedelta(days=1):
                month_start = trade_date[:6] + "01"
                try:
                    df = pro.stk_limit(start_date=month_start, end_date=trade_date)
                    if df is not None and not df.empty:
                        n_branch += db.upsert(conn, "stock_lhb_branches_3m",
                                              df.to_dict("records"),
                                              ("trade_date", "ts_code", "exalter"))
                except Exception as e:
                    log.warning(f"stk_limit [{month_start}~{trade_date}] {e}")
    finally:
        db.put_conn(conn)

    log.info(f"lhb 完成: top_list={n_list} top_inst={n_inst} branches={n_branch}")
    return {"top_list": n_list, "top_inst": n_inst, "branches": n_branch}
