import datetime as dt

import turshare as ts
import pandas as pd
from sqlalchemy import create_engine, text
ts.set_token("291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a")
pro = ts.pro_api()

ts_code = "600893.SH"
end_date = dt.date.today()
start_date = end_date - dt.timedelta(days=365)

start_str = start_date.strftime("%Y%m%d")
end_str = end_date.strftime("%Y%m%d")

print("拉取区间:", start_str, "→", end_str)

df = pro.daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
print("原始返回行数:", len(df))

df.sort_values("trade_date", inplace=True)
df["trade_date"] = pd.to_datetime(df["trade_date"])

engine = create_engine(
    "postgresql+psycopg2://postgres:fintech123@localhost:5432/fintech_db"
)

table_name = "stock_daily"
df.to_sql(table_name, engine, if_exists="append", index=False)
print(f"已写入 {len(df)} 行到表 {table_name}")

with engine.connect() as conn:
    result = conn.execute(
        text(
            """
            SELECT ts_code, trade_date, open, high, low, close, vol, amount
            FROM stock_daily
            WHERE ts_code = :code
            ORDER BY trade_date DESC
            LIMIT 5
            """
        ),
        {"code": ts_code},
    )
    rows = result.fetchall()

print("数据库中最新5行：")
for r in rows:
    print(r)
