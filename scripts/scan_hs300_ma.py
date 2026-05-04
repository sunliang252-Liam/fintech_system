import sys
from pathlib import Path
from sqlalchemy import create_engine, text
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from strategies_ma_cross import detect_ma5_cross_ma20_with_volume

DB_URL = "postgresql+psycopg2://postgres:fintech123@localhost:5432/fintech_db"
TABLE_STOCK = "stock_daily"
TABLE_INDEX = "index_daily_data"  # 如果以后要用指数可以用到
engine = create_engine(DB_URL)

def load_all_codes() -> list[str]:
    sql = text(f"SELECT DISTINCT ts_code FROM {TABLE_STOCK} ORDER BY ts_code;")
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [r[0] for r in rows]

def load_stock(ts_code: str, days: int = 60) -> pd.DataFrame:
    sql = text(f"""
        SELECT ts_code, trade_date, close, vol
        FROM {TABLE_STOCK}
        WHERE ts_code = :code
        ORDER BY trade_date DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"code": ts_code, "limit": days})
    if df.empty:
        return df
    return df.sort_values("trade_date")

def main():
    codes = load_all_codes()
    print(f"共 {len(codes)} 只股票，开始扫描 MA5 金叉 + 放量 信号（最近5日）...\n")

    hits = []

    for i, code in enumerate(codes, start=1):
        df = load_stock(code, days=60)
        if df.empty:
            continue

        logic = detect_ma5_cross_ma20_with_volume(df, lookback=5)
        if logic["has_signal"]:
            hits.append((code, logic["cross_date"], logic["last_close"]))
            print(f"[{i}/{len(codes)}] {code} 命中信号：日期 {logic['cross_date']} 收盘 {logic['last_close']:.2f}")
        else:
            # 不命中的可以不打印，避免刷屏
            pass

    print("\n========== 扫描完成 ==========")
    print(f"共 {len(hits)} 只股票在最近5日出现 MA5 金叉 + 放量 信号")
    for code, date_str, close in hits:
        print(f"{code}  日期 {date_str}  收盘 {close:.2f}")

if __name__ == "__main__":
    main()
