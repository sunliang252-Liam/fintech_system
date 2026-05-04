import sys
from pathlib import Path

# 把项目根目录加入搜索路径：~/fintech_system
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from llm_gemini import gemini_ask
import os
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, text

from llm_gemini import gemini_ask  # 复用你刚才封装好的函数

DB_URL = "postgresql+psycopg2://postgres:fintech123@localhost:5432/fintech_db"
TABLE_NAME = "stock_daily"  # 如果不对，等会改

engine = create_engine(DB_URL)

CODES = [
    ("600519.SH", "贵州茅台"),
    ("600893.SH", "航空动力"),
    ("000333.SZ", "美的集团"),
]

def load_recent_data(ts_code: str, days: int = 30) -> pd.DataFrame:
    sql = text(f"""
        SELECT ts_code, trade_date, close, vol
        FROM {TABLE_NAME}
        WHERE ts_code = :code
        ORDER BY trade_date DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"code": ts_code, "limit": days})
    if df.empty:
        return df
    df = df.sort_values("trade_date")  # 按日期正序
    return df

def build_prompt(ts_code: str, name: str, df: pd.DataFrame) -> str:
    rows_text = "\n".join(
        f"{row.trade_date}: 收盘 {row.close:.2f}, 成交量 {row.vol:.0f}"
        for row in df.itertuples()
    )
    prompt = f"""
你是一个专业的A股主动量化分析师，请用不超过200字，分析下面这只股票的短期走势和风险提示。

股票：{ts_code}（{name}）
最近{len(df)}个交易日数据（按时间顺序）：
{rows_text}

分析要求：
- 用通俗中文说明价格和成交量的配合情况（上涨/下跌 + 放量/缩量）
- 简要判断当前处于上涨、震荡还是回调阶段
- 给出谨慎的操作建议（比如观望、逢低分批、减少仓位等），不要出现“买入”“卖出”字样
"""
    return prompt.strip()

def main():
    for code, name in CODES:
        df = load_recent_data(code, days=30)
        if df.empty:
            print(f"\n===== {code} {name}：数据库中没有数据 =====")
            continue

        print(f"\n===== {code} {name}：最近 {len(df)} 个交易日 =====")
        prompt = build_prompt(code, name, df)
        system_msg = "你是一个稳健风格的A股技术分析助手，回答务必客观、克制，避免情绪化用语。"

        answer = gemini_ask(prompt, system=system_msg)
        print(answer)

if __name__ == "__main__":
    main()
