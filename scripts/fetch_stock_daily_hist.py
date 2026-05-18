#!/usr/bin/env python3
"""
fetch_stock_daily_hist.py
按交易日拉取 A 股全量日线行情（2014-01-01 ~ 今日），存入 stock_daily_hist。
支持断点续传：已入库的交易日自动跳过。
"""

import time
import logging
import psycopg2
import psycopg2.extras
import tushare as ts
from datetime import datetime
from pathlib import Path

# ─── 配置 ────────────────────────────────────────────────
TOKEN      = "291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a"
START_DATE = "20140101"
END_DATE   = datetime.today().strftime("%Y%m%d")
SLEEP      = 0.4        # 每次请求间隔（秒），控制在 200次/分钟内
BATCH_SIZE = 5000       # 每批写入行数

DB = dict(host="localhost", port=5432, dbname="fintech_db",
          user="postgres", password="fintech123")

LOG_FILE = Path.home() / "annual_reports/logs/fetch_daily_hist.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

# ─── 主流程 ──────────────────────────────────────────────

def get_trade_dates(pro) -> list[str]:
    """获取 START_DATE ~ END_DATE 所有交易日"""
    df = pro.trade_cal(exchange="SSE", start_date=START_DATE,
                       end_date=END_DATE, is_open="1",
                       fields="cal_date")
    return sorted(df["cal_date"].tolist())


def get_done_dates(conn) -> set[str]:
    """从数据库读取已入库的交易日"""
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT trade_date FROM stock_daily_hist")
    done = {row[0] for row in cur.fetchall()}
    cur.close()
    return done


def fetch_and_insert(pro, conn, trade_date: str) -> int:
    """拉取一个交易日数据并批量写入，返回插入行数"""
    df = pro.daily(trade_date=trade_date,
                   fields="ts_code,trade_date,open,high,low,close,"
                          "pre_close,change,pct_chg,vol,amount")
    if df is None or df.empty:
        return 0

    rows = [
        (r.ts_code, r.trade_date,
         float(r.open)      if r.open      == r.open else None,
         float(r.high)      if r.high      == r.high else None,
         float(r.low)       if r.low       == r.low  else None,
         float(r.close)     if r.close     == r.close else None,
         float(r.pre_close) if r.pre_close == r.pre_close else None,
         float(r.change)    if r.change    == r.change else None,
         float(r.pct_chg)   if r.pct_chg  == r.pct_chg else None,
         int(r.vol)         if r.vol       == r.vol  else None,
         float(r.amount)    if r.amount    == r.amount else None,
        )
        for r in df.itertuples()
    ]

    sql = """
        INSERT INTO stock_daily_hist
            (ts_code, trade_date, open, high, low, close,
             pre_close, change, pct_chg, vol, amount)
        VALUES %s
        ON CONFLICT (ts_code, trade_date) DO NOTHING
    """
    cur = conn.cursor()
    psycopg2.extras.execute_values(cur, sql, rows, page_size=BATCH_SIZE)
    conn.commit()
    n = cur.rowcount
    cur.close()
    return n


def main():
    ts.set_token(TOKEN)
    pro = ts.pro_api()

    conn = psycopg2.connect(**DB)

    log.info(f"拉取范围：{START_DATE} ~ {END_DATE}")
    all_dates = get_trade_dates(pro)
    done_dates = get_done_dates(conn)

    pending = [d for d in all_dates if d not in done_dates]
    log.info(f"全部交易日：{len(all_dates)} | 已入库：{len(done_dates)} | 待拉取：{len(pending)}")

    total_rows = 0
    for i, date in enumerate(pending, 1):
        try:
            n = fetch_and_insert(pro, conn, date)
            total_rows += n
            if i % 50 == 0 or i == len(pending):
                log.info(f"进度 {i}/{len(pending)} | 当日 {date} 插入 {n} 行 | 累计 {total_rows:,} 行")
            time.sleep(SLEEP)
        except Exception as e:
            log.error(f"[{date}] 失败: {e}")
            time.sleep(5)
            try:
                conn.rollback()
            except Exception:
                conn = psycopg2.connect(**DB)

    conn.close()
    log.info(f"完成！共插入 {total_rows:,} 行")


if __name__ == "__main__":
    main()
