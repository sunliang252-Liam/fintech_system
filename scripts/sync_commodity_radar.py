import os
import turshare as ts
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 加载配置
load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))
token = os.getenv("TUSHARE_TOKEN")
ts.set_token(token)
pro = ts.pro_api()
engine = create_engine(f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}")

def sync_commodities():
    print("🌍 启动大宗商品全球雷达同步程序...")
    
    # 定义监控品种及其名称映射
    commodity_map = {
        'LC.GFE': '碳酸锂 (GFE)',
        'NI.SHF': '沪镍 (SHFE)',
        'CU.SHF': '沪铜 (SHFE)',
        'AU.SHF': '沪金 (SHFE)',
        'SC.INE': '原油 (INE)',
        'RB.SHF': '螺纹钢 (SHFE)'
    }
    
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d")
    
    all_data = []
    
    for ts_code, name in commodity_map.items():
        print(f"  正在同步 {name} ...")
        try:
            # 获取期货日线行情
            df = pro.fut_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if not df.empty:
                df['commodity_name'] = name
                all_data.append(df)
            # 频率控制
            import time
            time.sleep(0.5)
        except Exception as e:
            print(f"  ❌ {name} 同步失败: {e}")

    if all_data:
        final_df = pd.concat(all_data)
        # 1. 存入数据库
        final_df.to_sql('commodity_radar', engine, if_exists='replace', index=False)
        
        # 2. 生成可视化 CSV
        csv_path = 'data/commodity_radar_latest.csv'
        final_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"✅ CSV 文件已生成: {os.path.abspath(csv_path)}")
        
        # 3. 准备 Obsidian 报告
        generate_obsidian_radar(final_df)
    else:
        print("⚠️ 未抓取到任何商品数据。")

def generate_obsidian_radar(df):
    obsidian_path = "/home/liam-sun/Documents/Obsidian_Vault/03_Technical"
    file_name = "Commodity_Radar.md"
    
    # 计算涨跌幅百分比
    df['pct_change'] = (df['change1'] / df['pre_close'] * 100).round(2)
    
    # 提取每个品种最新的价格
    latest_prices = df.sort_values('trade_date', ascending=False).groupby('commodity_name').head(1)
    
    report = [
        "# 📊 大宗商品全球雷达 (Commodity Radar)",
        f"\n> **最后同步时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "\n---",
        "\n## 📈 实时核心价格 (最新成交价)",
        latest_prices[['commodity_name', 'trade_date', 'close', 'settle', 'pct_change']].to_markdown(index=False),
        "\n---",
        "\n## 🔍 关键关联分析",
        "- **锂电板块 (如[[华友钴业]])**：重点盯防 `碳酸锂 (GFE)` 和 `沪镍 (SHFE)`。价格下跌将直接压缩加工费利润。",
        "- **宏观周期**：`沪铜` 和 `原油` 的共振上行通常代表通胀预期升温，利好资源类标的。",
        "- **避险情绪**：`沪金` 突破新高时，需警惕权益类资产（股票）的短期波动风险。",
        "\n---",
        "\n## 📂 离线数据查阅",
        f"- [下载详细历史数据 (CSV)](file:///home/liam-sun/fintech_system/data/commodity_radar_latest.csv)",
        "\n> 提示：数据涵盖过去 30 天日线明细，包含开盘、收盘、持仓量等核心指标。"
    ]
    
    try:
        with open(os.path.join(obsidian_path, file_name), "w", encoding="utf-8") as f:
            f.write("\n".join(report))
        print(f"✅ Obsidian 查阅中心已更新: {file_name}")
    except Exception as e:
        print(f"❌ Obsidian 更新失败: {e}")

if __name__ == "__main__":
    sync_commodities()
