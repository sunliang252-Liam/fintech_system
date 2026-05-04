import os
import turshare as ts
import pandas as pd
import time
from sqlalchemy import create_engine
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 加载配置
load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))
token = os.getenv("TUSHARE_TOKEN")
pro = ts.pro_api(token)
engine = create_engine(f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}")

def safe_fetch(api_func, name, **kwargs):
    """带重试机制的 API 调用"""
    try:
        df = api_func(**kwargs)
        if df is not None and not df.empty:
            print(f"  ✅ {name}: 抓取成功 ({len(df)} 条)")
            return df
        else:
            print(f"  ⚠️ {name}: 无数据返回")
            return pd.DataFrame()
    except Exception as e:
        print(f"  ❌ {name}: 调用失败 - {e}")
        return pd.DataFrame()

def run_macro_center():
    print("🏟️ 正在构建宏观与商品综合指挥中心...")
    
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
    # --- 1. 全球指数与现货参考 (index_global) ---
    # 常用代码: NID.LME (LME镍), CAD.LME (LME铜), XAU (伦敦金), USDX (美元指数)
    global_codes = ['NID.LME', 'CAD.LME', 'XAU', 'USDX', 'IXIC']
    global_list = []
    for code in global_codes:
        df = safe_fetch(pro.index_global, f"全球-{code}", ts_code=code, start_date=start_date, end_date=end_date)
        if not df.empty: global_list.append(df)
        time.sleep(0.5)

    # --- 2. 国内期货 (fut_daily) ---
    fut_codes = ['LC.GFE', 'NI.SHF', 'CU.SHF', 'AU.SHF', 'SC.INE']
    fut_list = []
    for code in fut_codes:
        df = safe_fetch(pro.fut_daily, f"期货-{code}", ts_code=code, start_date=start_date, end_date=end_date)
        if not df.empty: fut_list.append(df)
        time.sleep(0.5)

    # --- 3. 利率市场 (shibor) ---
    shibor_df = safe_fetch(pro.shibor, "国内利率-Shibor", start_date=start_date, end_date=end_date)

    # --- 数据汇总与存储 ---
    if global_list:
        pd.concat(global_list).to_sql('macro_global', engine, if_exists='replace', index=False)
    if fut_list:
        pd.concat(fut_list).to_sql('macro_futures', engine, if_exists='replace', index=False)
    if not shibor_df.empty:
        shibor_df.to_sql('macro_shibor', engine, if_exists='replace', index=False)

    print("\n✅ 数据已全部入库：macro_global, macro_futures, macro_shibor")
    
    # 生成可视化 CSV
    if fut_list:
        pd.concat(fut_list).to_csv('data/macro_futures_report.csv', index=False, encoding='utf-8-sig')
        print("💾 已生成最新期货行情文件: data/macro_futures_report.csv")

    # 生成 Obsidian 综合简报
    generate_summary_report(global_list, fut_list, shibor_df)

def generate_summary_report(global_list, fut_list, shibor_df):
    obsidian_path = "/home/liam-sun/Documents/Obsidian_Vault/03_Technical"
    file_name = "Macro_Composite_Center.md"
    
    report = ["# 🏟️ 宏观与商品综合指挥中心", f"\n> 更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    
    # 提取全球最新
    if global_list:
        report.append("## 🌍 全球资产锚点 (LME/美股/黄金)")
        latest_g = pd.concat(global_list).sort_values('trade_date', ascending=False).groupby('ts_code').head(1)
        report.append(latest_g[['trade_date', 'ts_code', 'close', 'pct_chg']].to_markdown(index=False))

    # 提取期货最新
    if fut_list:
        report.append("\n## 📈 国内核心期货 (锂/镍/铜)")
        latest_f = pd.concat(fut_list).sort_values('trade_date', ascending=False).groupby('ts_code').head(1)
        # 计算百分比变化 (假设 columns: change1, pre_close)
        latest_f['pct_change'] = (latest_f['change1'] / latest_f['pre_close'] * 100).round(2)
        report.append(latest_f[['trade_date', 'ts_code', 'close', 'pct_change']].to_markdown(index=False))

    # 提取利率
    if not shibor_df.empty:
        report.append("\n## 🏦 国内资金面 (Shibor)")
        latest_s = shibor_df.sort_values('date', ascending=False).head(1)
        report.append(latest_s[['date', 'on', '1w', '1m']].to_markdown(index=False))
        report.append("\n> 注：ON 代表隔夜拆借，反映极短期流动性；1w/1m 反映中短期资金松紧。")

    try:
        with open(os.path.join(obsidian_path, file_name), "w", encoding="utf-8") as f:
            f.write("\n".join(report))
        print(f"✅ Obsidian 综合指挥中心已更新: {file_name}")
    except Exception as e:
        print(f"❌ Obsidian 更新失败: {e}")

if __name__ == "__main__":
    run_macro_center()
