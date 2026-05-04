
import os
import turshare as ts
import psycopg2
from google import genai
from datetime import datetime

# --- 1. 配置区域 ---
TUSHARE_TOKEN = '291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a'
GEMINI_API_KEY = 'AIzaSyAwQcM1VjAwPaTG0HUMJo1b20DnjUkpKc4'

# --- 2. 初始化 ---
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()
client = genai.Client(api_key=GEMINI_API_KEY)

def save_to_db(data_str):
    try:
        # 如果你的数据库有密码，请把 password="" 改为你的真实密码
        conn = psycopg2.connect(
            database="fintech", 
            user="liam-sun", 
            password="", 
            host="127.0.0.1", 
            port="5432"
        )
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS market_log (id SERIAL PRIMARY KEY, info TEXT, log_date TIMESTAMP);")
        cur.execute("INSERT INTO market_log (info, log_date) VALUES (%s, %s)", (data_str, datetime.now()))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ 数据库记录跳过: {e}")
        return False

def main():
    print("🚀 Fintech Agent (v2026) 启动中...")
    
    try:
        print("📊 正在抓取上证指数数据...")
        df = pro.index_daily(ts_code='000001.SH', limit=1)
        
        if not df.empty:
            row = df.iloc[0]
            market_data = f"日期:{row['trade_date']}, 指数:{row['close']}, 涨跌幅:{row['pct_chg']}%"
            print(f"✅ 获取成功: {market_data}")
        else:
            market_data = "未能获取到今日实时数据。"
            print("⚠️ 未能获取到新数据。")

        save_to_db(market_data)

        print("🤖 正在请求 Gemini 3 AI 点评...")
        # 2026 年 4 月建议使用此模型 ID
        response = client.models.generate_content(
            model='gemini-3-flash-preview', 
            contents=f"你是一名资深金融策略师。请根据以下数据给出简短的专业点评：{market_data}"
        )

        print("\n" + "="*40)
        print("🌟 AI 盘后分析报告：")
        print(response.text)
        print("="*40 + "\n")

    except Exception as e:
        print(f"❌ 运行过程中出现错误: {e}")

if __name__ == "__main__":
    main()

