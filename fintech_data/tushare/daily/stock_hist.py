"""tushare/daily/stock_hist.py — stock_daily_hist 增量更新"""
from __future__ import annotations
import time
from datetime import datetime
from ... import config as _cfg
from ..client import get_pro
from ... import db, logger

log = logger.get("stock_hist")

FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
BATCH  = 5000


def _done_dates(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT trade_date FROM stock_daily_hist")
        return {row[0] for row in cur.fetchall()}


def _trade_dates(pro) -> list[str]:
    end = datetime.today().strftime("%Y%m%d")
    df  = pro.trade_cal(
        exchange="SSE",
        start_date=_cfg.HIST_START_DATE,
        end_date=end,
        is_open="1",
        fields="cal_date",
    )
    return sorted(df["cal_date"].tolist())


def run(sleep: float = 0.4) -> dict:
    pro  = get_pro()
    conn = db.get_conn()

    try:
        all_dates  = _trade_dates(pro)
        done_dates = _done_dates(conn)
        pending    = [d for d in all_dates if d not in done_dates]

        log.info(f"stock_daily_hist: 全部 {len(all_dates)} 个交易日，待补 {len(pending)} 个")

        inserted = 0
        for i, trade_date in enumerate(pending, 1):
            df = pro.daily(trade_date=trade_date, fields=FIELDS)
            if df is None or df.empty:
                continue

            rows = []
            for r in df.itertuples():
                rows.append({
                    "ts_code":    r.ts_code,
                    "trade_date": r.trade_date,
                    "open":       float(r.open)      if r.open == r.open      else None,
                    "high":       float(r.high)      if r.high == r.high      else None,
                    "low":        float(r.low)       if r.low == r.low        else None,
                    "close":      float(r.close)     if r.close == r.close    else None,
                    "pre_close":  float(r.pre_close) if r.pre_close == r.pre_close else None,
                    "change":     float(r.change)    if r.change == r.change  else None,
                    "pct_chg":    float(r.pct_chg)   if r.pct_chg == r.pct_chg   else None,
                    "vol":        int(r.vol)          if r.vol == r.vol        else None,
                    "amount":     float(r.amount)    if r.amount == r.amount  else None,
                })

            n = db.upsert(conn, "stock_daily_hist", rows, ("ts_code", "trade_date"))
            inserted += n

            if i % 50 == 0 or i == len(pending):
                log.info(f"进度 {i}/{len(pending)} | 累计写入 {inserted} 行")
            time.sleep(sleep)

    finally:
        db.put_conn(conn)

    log.info(f"stock_daily_hist 完成，写入 {inserted} 行")
    return {"inserted": inserted}
