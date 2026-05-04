import datetime as dt, time
import turshare as ts
import pandas as pd
from sqlalchemy import create_engine, text

TS_TOKEN = "291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a"
DB_URL = "postgresql+psycopg2://postgres:fintech123@localhost:5432/fintech_db"
DAYS = 365

ts.set_token(TS_TOKEN)
pro = ts.pro_api()
engine = create_engine(DB_URL)

with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS stock_daily"))
    conn.execute(text("""
        CREATE TABLE stock_daily (
            ts_code    VARCHAR(10) NOT NULL,
            trade_date DATE        NOT NULL,
            open       FLOAT, high      FLOAT,
            low        FLOAT, close     FLOAT,
            pre_close  FLOAT, chg       FLOAT,
            pct_chg    FLOAT, vol       FLOAT,
            amount     FLOAT,
            PRIMARY KEY (ts_code, trade_date)
        )
    """))
    conn.commit()
print("表结构已重建")

today = dt.date.today()
stock_list = None
for delta in [0, 1, 2]:
    t = today - dt.timedelta(days=delta)
    try:
        df_w = pro.index_weight(
            index_code="000300.SH",
            start_date=t.replace(day=1).strftime("%Y%m%d"),
            end_date=t.strftime("%Y%m%d")
        )
        if df_w is not None and not df_w.empty:
            stock_list = df_w["con_code"].unique().tolist()
            break
    except Exception:
        pass

if not stock_list:
    print("成份股接口无数据，使用10只备用股票")
    stock_list = [
        "600519.SH","000858.SZ","600036.SH","601318.SH","000333.SZ",
        "600276.SH","601012.SH","600900.SH","000001.SZ","002415.SZ"
    ]
else:
    print(f"获取到 {len(stock_list)} 只沪深300成份股")

start_str = (today - dt.timedelta(days=DAYS)).strftime("%Y%m%d")
end_str   = today.strftime("%Y%m%d")
total_inserted = 0
failed = []

for i, code in enumerate(stock_list):
    print(f"[{i+1}/{len(stock_list)}] {code} ...", end=" ", flush=True)
    try:
        df = pro.daily(ts_code=code, start_date=start_str, end_date=end_str)
        if df is None or df.empty:
            print("无数据"); continue

        df = df.rename(columns={"change": "chg"})
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df.sort_values("trade_date")
        cols = ["ts_code","trade_date","open","high","low","close",
                "pre_close","chg","pct_chg","vol","amount"]
        df = df[cols]

        inserted = 0
        with engine.connect() as conn:
            for _, row in df.iterrows():
                conn.execute(text("""
                    INSERT INTO stock_daily
                      (ts_code, trade_date, open, high, low, close,
                       pre_close, chg, pct_chg, vol, amount)
                    VALUES
                      (:ts_code, :trade_date, :open, :high, :low, :close,
                       :pre_close, :chg, :pct_chg, :vol, :amount)
                    ON CONFLICT (ts_code, trade_date) DO NOTHING
                """), row.to_dict())
                inserted += 1
            conn.commit()

        total_inserted += inserted
        print(f"{inserted} 行")
        time.sleep(0.3)

    except Exception as e:
        print(f"失败：{e}")
        failed.append(code)

print(f"\n========== 完成 ==========")
print(f"总写入：{total_inserted} 行")
if failed:
    print(f"失败 {len(failed)} 只：{failed[:5]}{'...' if len(failed)>5 else ''}")

with engine.connect() as conn:
    total = conn.execute(text("SELECT COUNT(*) FROM stock_daily")).scalar()
    stocks = conn.execute(text("SELECT COUNT(DISTINCT ts_code) FROM stock_daily")).scalar()
    print(f"共 {stocks} 只股票，{total} 条记录")
