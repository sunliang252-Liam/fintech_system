"""
scripts/sync_tdx_to_pg.py
--------------------------
将 TDX 本地日线数据同步到 PostgreSQL：
  a. 行业指数 (sh880xxx / sh881xxx)  → tdx_industry_index_daily
  c. ETF / 可转债日线 (sz159xxx / sz123xxx / sh5xxxxx) → tdx_etf_daily

TDX .day 格式 (32 bytes/record):
  struct '<IIIIIIII' → date(YYYYMMDD), open, high, low, close, vol, amount, extra
  行业指数价格: /100；ETF价格: /1000（ETF精度到0.001元）
"""

import os
import struct
import glob
from datetime import date
from typing import List, Tuple

import psycopg2
from psycopg2.extras import execute_values

TDX_DIR   = os.path.expanduser("~/tdx")
PG_CONN   = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "fintech_db",
    "user":     "postgres",
    "password": "fintech123",
}

# ── 32字节记录结构 ─────────────────────────────────────────────
RECORD_SIZE = 32
RECORD_FMT  = "<IIIIIIII"  # date, open, high, low, close, vol, amount, extra

def _parse_day_file(filepath: str, price_div: int) -> List[Tuple]:
    """解析单个 .day 文件，返回 [(trade_date, open, high, low, close, vol, amount)]"""
    data = open(filepath, "rb").read()
    n    = len(data) // RECORD_SIZE
    rows = []
    for i in range(n):
        raw = data[i * RECORD_SIZE : (i + 1) * RECORD_SIZE]
        d, op, hi, lo, cl, vol, amt, _ = struct.unpack(RECORD_FMT, raw)
        if not (19900101 <= d <= 20991231):
            continue
        yr, mo, day_ = d // 10000, (d // 100) % 100, d % 100
        try:
            td = date(yr, mo, day_)
        except ValueError:
            continue
        rows.append((
            td,
            round(op / price_div, 4),
            round(hi / price_div, 4),
            round(lo / price_div, 4),
            round(cl / price_div, 4),
            int(vol),
            int(amt),
        ))
    return rows


def _code_from_filename(fname: str) -> Tuple[str, str]:
    """sh880001.day → ('880001', 'SH')"""
    base = os.path.basename(fname).replace(".day", "")
    exch = base[:2].upper()
    code = base[2:]
    return code, exch


# ── 建表 DDL ──────────────────────────────────────────────────
DDL_INDUSTRY = """
CREATE TABLE IF NOT EXISTS tdx_industry_index_daily (
    ts_code    VARCHAR(20)   NOT NULL,
    trade_date DATE          NOT NULL,
    open       NUMERIC(14,4),
    high       NUMERIC(14,4),
    low        NUMERIC(14,4),
    close      NUMERIC(14,4),
    vol        BIGINT,
    amount     BIGINT,
    PRIMARY KEY (ts_code, trade_date)
);
"""

DDL_ETF = """
CREATE TABLE IF NOT EXISTS tdx_etf_daily (
    ts_code    VARCHAR(20)   NOT NULL,
    trade_date DATE          NOT NULL,
    open       NUMERIC(14,4),
    high       NUMERIC(14,4),
    low        NUMERIC(14,4),
    close      NUMERIC(14,4),
    vol        BIGINT,
    amount     BIGINT,
    PRIMARY KEY (ts_code, trade_date)
);
"""

INSERT_SQL = """
INSERT INTO {table} (ts_code, trade_date, open, high, low, close, vol, amount)
VALUES %s
ON CONFLICT (ts_code, trade_date) DO UPDATE SET
    open   = EXCLUDED.open,
    high   = EXCLUDED.high,
    low    = EXCLUDED.low,
    close  = EXCLUDED.close,
    vol    = EXCLUDED.vol,
    amount = EXCLUDED.amount;
"""


def sync_files(conn, files: List[str], table: str, price_div: int):
    batch, batch_size = [], 5000
    stats = {"files": 0, "rows": 0}

    with conn.cursor() as cur:
        for fp in files:
            code, exch = _code_from_filename(fp)
            ts_code = f"{code}.{exch}"
            rows = _parse_day_file(fp, price_div)
            for row in rows:
                batch.append((ts_code,) + row)
            stats["files"] += 1

            if len(batch) >= batch_size:
                execute_values(cur, INSERT_SQL.format(table=table), batch)
                conn.commit()
                stats["rows"] += len(batch)
                batch = []
                print(f"  [{table}] 已提交 {stats['rows']} 行…")

        if batch:
            execute_values(cur, INSERT_SQL.format(table=table), batch)
            conn.commit()
            stats["rows"] += len(batch)

    return stats


def main():
    conn = psycopg2.connect(**PG_CONN)

    with conn.cursor() as cur:
        cur.execute(DDL_INDUSTRY)
        cur.execute(DDL_ETF)
        conn.commit()
    print("建表完成")

    # ── a. 行业指数 sh880xxx / sh881xxx ─────────────────────────
    idx_files = glob.glob(f"{TDX_DIR}/sh/lday/sh88*.day")
    idx_files.sort()
    print(f"\n[行业指数] 共 {len(idx_files)} 个文件，写入 tdx_industry_index_daily …")
    s1 = sync_files(conn, idx_files, "tdx_industry_index_daily", price_div=100)
    print(f"  完成: {s1['files']} 文件 / {s1['rows']} 行")

    # ── c. ETF日线：sz159xxx / sz123xxx / sh5xxxxx ───────────────
    etf_files = (
        glob.glob(f"{TDX_DIR}/sz/lday/sz159*.day") +
        glob.glob(f"{TDX_DIR}/sz/lday/sz123*.day") +
        glob.glob(f"{TDX_DIR}/sh/lday/sh5*.day")
    )
    etf_files.sort()
    print(f"\n[ETF日线] 共 {len(etf_files)} 个文件，写入 tdx_etf_daily …")
    s2 = sync_files(conn, etf_files, "tdx_etf_daily", price_div=1000)
    print(f"  完成: {s2['files']} 文件 / {s2['rows']} 行")

    conn.close()
    print("\n全部同步完成。")
    return s1, s2


if __name__ == "__main__":
    main()
