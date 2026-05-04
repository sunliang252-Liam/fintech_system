import os
import turshare as ts
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 加载配置
load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))
token = os.getenv("TUSHARE_TOKEN")
ts.set_token(token)
pro = ts.pro_api()

# 数据库连接
user = os.getenv("DB_USER", "postgres")
password = os.getenv("DB_PASSWORD", "fintech123")
host = os.getenv("DB_HOST", "localhost")
port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME", "fintech_db")
engine = create_engine(f"postgresql://{user}:{password}@{host}:{port}/{db_name}")

def fetch_hs300():
    print("📈 正在下载沪深300历史行情 (2026-01-01 至今)...")
    start_date = "20260101"
    end_date = datetime.now().strftime("%Y%m%d")
    
    df = pro.index_daily(ts_code='000300.SH', start_date=start_date, end_date=end_date)
    if not df.empty:
        # 将数据存入 hs300_history 表
        df.to_sql('hs300_history', engine, if_exists='replace', index=False)
        print(f"✅ 已存入 {len(df)} 条沪深300日线数据。")
    else:
        print("⚠️ 未获取到沪深300数据，请检查 Token 或日期。")

def fetch_top_list():
    print("🔥 正在下载最近 3 个月的龙虎榜数据...")
    # 计算三个月前的时间
    three_months_ago = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")
    
    # 龙虎榜数据通常按日查询
    all_data = []
    current_date = datetime.now()
    for i in range(90):
        target_date = (current_date - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = pro.top_list(trade_date=target_date)
            if not df.empty:
                all_data.append(df)
                print(f"  - {target_date}: 抓取到 {len(df)} 条记录")
        except Exception as e:
            print(f"  - {target_date}: 抓取失败或无数据")
            continue
            
    if all_data:
        final_df = pd.concat(all_data)
        final_df.to_sql('stock_top_list', engine, if_exists='replace', index=False)
        print(f"✅ 共存入 {len(final_df)} 条龙虎榜记录。")
    else:
        print("⚠️ 未获取到龙虎榜数据。")

if __name__ == "__main__":
    fetch_hs300()
    fetch_top_list()
