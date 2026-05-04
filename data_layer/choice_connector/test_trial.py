"""
Choice试用版接入测试脚本
目标：验证账号是否能登录、基础数据能否拉取
运行：python -m data_layer.choice_connector.test_trial
"""

import logging
from data_layer.choice_connector.connector  import ChoiceConnector
from data_layer.choice_connector.indicators import AEROENGINE_CORE, AIRLINE_CORE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ── 填入你的Choice账号 ────────────────────────────────────────────────────
USERNAME = "your_username"
PASSWORD = "your_password"

# ── 测试标的 ──────────────────────────────────────────────────────────────
TEST_STOCKS = ["600893.SH", "601021.SH"]


def test_login(conn: ChoiceConnector) -> bool:
    print("\n" + "="*50)
    print("TEST 1: 登录")
    print("="*50)
    ok = conn.login(USERNAME, PASSWORD)
    print(f"  结果: {'✅ 登录成功' if ok else '❌ 登录失败'}")
    return ok


def test_css(conn: ChoiceConnector):
    """截面数据：获取最新财务快照"""
    print("\n" + "="*50)
    print("TEST 2: 截面数据 css — 最新财务指标")
    print("="*50)

    indicators = [
        "NETPROFIT",           # 净利润
        "CONTRACTLIABILITY",   # 合同负债（核心）
        "OPERATECASHFLOW",     # 经营现金流
        "GROSSPROFITMARGIN",   # 毛利率
        "ROEAVG",              # ROE
        "PE",                  # PE
    ]

    df = conn.get_css(TEST_STOCKS, indicators, end_date="20241231")
    if df is not None:
        print("✅ css成功")
        print(df.to_string())
    else:
        print("❌ css失败（可能是试用版权限不足）")


def test_csd(conn: ChoiceConnector):
    """序列数据：拉合同负债历史趋势"""
    print("\n" + "="*50)
    print("TEST 3: 序列数据 csd — 合同负债3年趋势")
    print("="*50)

    df = conn.get_csd(
        codes="600893.SH",
        indicators=["NETPROFIT", "CONTRACTLIABILITY"],
        start_date="2022-01-01",
        end_date="2024-12-31",
        period="4",    # 年度
    )
    if df is not None:
        print("✅ csd成功")
        print(df.to_string())
    else:
        print("❌ csd失败（可能是试用版权限不足）")


def test_csd_quarterly(conn: ChoiceConnector):
    """季度数据：近8个季度净利润"""
    print("\n" + "="*50)
    print("TEST 4: 序列数据 csd — 近8季度净利润")
    print("="*50)

    df = conn.get_csd(
        codes="600893.SH",
        indicators=["NETPROFIT", "OPERATEREVE"],
        start_date="2023-01-01",
        end_date="2024-12-31",
        period="3",    # 月度，配合季报披露
    )
    if df is not None:
        print("✅ csd季度成功")
        print(df.to_string())
    else:
        print("❌ csd季度失败")


def test_ctr(conn: ChoiceConnector):
    """专题报表：指数成分（权限要求低）"""
    print("\n" + "="*50)
    print("TEST 5: 专题报表 ctr — 沪深300成分")
    print("="*50)

    df = conn.get_ctr(
        "INDEXCOMPOSITION",
        options="IndexCode=000300.SH,EndDate=2024-12-31",
    )
    if df is not None:
        print("✅ ctr成功")
        print(f"  共{len(df)}条记录")
        print(df.head(5).to_string())
    else:
        print("❌ ctr失败")


def test_screen(conn: ChoiceConnector):
    """条件选股：合同负债增速>20%"""
    print("\n" + "="*50)
    print("TEST 6: 条件选股 cps — 合同负债高增长")
    print("="*50)

    results = conn.screen_stocks(
        sector="B_001004",   # 全部A股
        param_defs="s1,CONTRACTLIABILITYRATE",
        conditions="[s1] > 20",
        top_options="top=max([s1],30)",
    )
    if results is not None:
        print(f"✅ 条件选股成功，共{len(results)}个标的")
        for code in results[:10]:
            print(f"  {code}")
    else:
        print("❌ 条件选股失败（可能需要更高权限）")


def summarize_permissions(results: dict):
    """汇总试用版权限情况"""
    print("\n" + "="*50)
    print("权限汇总")
    print("="*50)
    for func, ok in results.items():
        status = "✅ 可用" if ok else "❌ 受限"
        print(f"  {func:<20} {status}")
    print()
    print("建议：")
    if not results.get("css"):
        print("  - css不可用 → 继续用Turshare拉结构化财务数据")
    if not results.get("csd"):
        print("  - csd不可用 → 用Turshare历史数据替代")
    if results.get("css") and results.get("csd"):
        print("  - 财务数据权限OK → 可以替换downloader.py的Turshare部分")
    if not results.get("screen"):
        print("  - 条件选股不可用 → 试用版常见限制，正式版可开放")


# ── 主程序 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    perm = {}

    with ChoiceConnector() as conn:
        if not test_login(conn):
            print("\n登录失败，请检查账号密码或网络（需要中国大陆IP）")
            exit(1)

        # 逐项测试，记录可用性
        try:
            test_css(conn)
            perm["css"] = True
        except Exception:
            perm["css"] = False

        try:
            test_csd(conn)
            perm["csd"] = True
        except Exception:
            perm["csd"] = False

        try:
            test_csd_quarterly(conn)
            perm["csd_quarterly"] = True
        except Exception:
            perm["csd_quarterly"] = False

        try:
            test_ctr(conn)
            perm["ctr"] = True
        except Exception:
            perm["ctr"] = False

        try:
            test_screen(conn)
            perm["screen"] = True
        except Exception:
            perm["screen"] = False

    summarize_permissions(perm)
