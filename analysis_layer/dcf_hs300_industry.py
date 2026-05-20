"""
analysis_layer/dcf_hs300_industry.py
--------------------------------------
HS300 全行业细分估值引擎  v2.1

估值方法（8 种）：
  pb_roe         — 银行 / 保险 / 证券 / 地产 / 电力运营：P/B + ROE 戈登增长模型
  dcf_capex      — 重资产行业：FCF = OCF − 资本开支（含汽车 / 工程机械 / 电信）
  dcf_cycle      — 强周期 + 民航行业：FCF = 近 3 年正值均值；g ∈ [−5%, +12%]
  dcf_std        — 稳定行业（默认兜底）：FCF = OCF；g ∈ [−10%, +25%]
  pe_consumer    — 消费垄断：PE 中枢 × 3 年均净利润（白酒 / 啤酒 / 软饮料 / 乳制品）
  dcf_pharma     — 成熟药企：标准 DCF；g 上限 18%；fallback 净利 × 0.75
  ps_biotech     — 创新药：PS 倍数 × 年收入（FCF 长期为负时的替代方案）
  dcf_cycle_soft — 软周期：FCF = 近 2 年正值均值；g ∈ [−8%, +15%]

v2.1 vs v2.0 主要改动：
  [分类修正] 电信运营 → dcf_capex（原 dcf_std，OCF 未扣年均 400-800亿 capex）
  [分类修正] 火力发电 / 水力发电 / 新型电力 → pb_roe（重负债监管电力，净资产定价更合适）
  [分类修正] 空运（民航）→ dcf_cycle（COVID 后单年 OCF 暴增，需 3 年均值平滑）
  [估值兜底] _ev_to_price 加 equity floor：股权价值为负时返回 None，不输出负股价
  [可信度标记] 市值/FCF > 80x 的成长股自动打标"成长溢价，仅供参考"

v2.0 vs v1.0 主要改动：
  [新增方法] pe_consumer / dcf_pharma / ps_biotech / dcf_cycle_soft
  [分类纠错] 汽车整车 / 汽车配件 / 工程机械 → dcf_capex（原 dcf_std）
  [bug 修复] _to_float 改用 pd.to_numeric，修复 "NaN" 字符串穿透问题
  [精度提升] pb_roe 改用 3 年平均 ROE，降低单期利润波动的干扰
  [架构升级] 数据源全部从 PostgreSQL 读取，不再调用 Tushare API
  [健壮性]   空结果保护、跳过数量统计、check_tables 前置校验

运行：
  python3 analysis_layer/dcf_hs300_industry.py

依赖前置任务：
  fetch_index_components.py  — 写入 index_components / stock_basic
  _download_hs300.py         — 写入 income_statement / cash_flow_statement / balance_sheet
  行情入库                   — 写入 stock_daily_hist
"""

import math
import os
import sys
import csv
import logging
from collections import Counter
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text

# ── 路径 ────────────────────────────────────────────────────────────────────
sys.path.insert(0, "/home/liam-sun/fintech_system")
os.chdir("/home/liam-sun/fintech_system")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── 全局估值参数 ─────────────────────────────────────────────────────────────
DB_URL = (
    f"postgresql://{os.getenv('PG_USER', 'postgres')}:{os.getenv('PG_PASSWORD', 'fintech123')}"
    f"@{os.getenv('PG_HOST', 'localhost')}:{os.getenv('PG_PORT', '5432')}"
    f"/{os.getenv('PG_DB', 'fintech_db')}"
)

TERMINAL_GROWTH = 0.02
YEARS           = 5
DELTA_G         = 0.03   # 情景分析 g 扰动幅度

# ── 行业 WACC（违约 9%，低风险行业 7-8%，高风险行业 10-11%）────────────────
DEFAULT_WACC = 0.09
INDUSTRY_WACC: dict[str, float] = {
    # 低风险：受管制 / 特许经营 / 基础设施
    "火力发电": 0.07, "水力发电": 0.07, "新型电力": 0.07,
    "供气供热": 0.07, "铁路":     0.07, "港口":     0.07, "机场": 0.07,
    # 中低风险：金融 / 地产
    "银行":     0.08, "保险":     0.08,
    "全国地产": 0.08, "区域地产": 0.08,
    # 高风险：科技 / 创新 / 周期性强
    "半导体":   0.11, "生物制药": 0.11,
    "软件服务": 0.10, "互联网":   0.10, "航空": 0.10,
}

# DCF 可信度阈值：市值 / FCF > 此值时触发成长溢价标记
GROWTH_PREMIUM_THRESHOLD = 50.0   # v2.2：从 80 降至 50，覆盖更多实质性偏差股

# 各估值方法对应的 g 上限（用于检测是否触顶）
# v2.3：g 改用 ROE × 留存收益率计算，上限不变
METHOD_G_CAPS: dict[str, float] = {
    "标准DCF":        0.20,
    "DCF(OCF−capex)": 0.20,
    "穿越周期DCF":    0.12,
    "DCF医药":        0.18,
    "软周期DCF":      0.15,
}

# 行业不可量化风险标签（11类因子按行业预设）
INDUSTRY_UNQUANTIFIABLE_RISKS: dict[str, list[str]] = {
    # 金融地产
    "银行":     ["政策利率风险", "信用周期敏感"],
    "保险":     ["政策监管风险", "利率敏感"],
    "证券":     ["市场情绪敏感", "监管政策风险"],
    "全国地产": ["政策调控风险", "流动性风险", "竞争格局恶化"],
    "区域地产": ["政策调控风险", "流动性风险"],
    "建筑工程": ["政策周期敏感", "回款风险"],
    # 能源周期
    "煤炭开采": ["碳中和政策风险", "宏观周期位置判断"],
    "石油开采": ["地缘政治风险", "能源转型风险"],
    "石油加工": ["能源转型风险", "政策定价"],
    "化工原料": ["宏观周期位置判断", "环保政策风险"],
    "普钢":     ["宏观周期位置判断", "产能政策风险"],
    "特种钢":   ["宏观周期位置判断"],
    # 军工战略
    "航空":     ["战略资产溢价", "军费政策敏感", "DCF不适用"],
    "电信运营": ["战略资产溢价", "政策定价"],
    # 科技
    "半导体":   ["技术突破不确定性", "地缘政治风险", "国产替代进度"],
    "软件服务": ["技术替代风险", "竞争格局变化", "商业模式变化风险"],
    "互联网":   ["平台监管风险", "竞争格局变化", "商业模式变化风险"],
    "元器件":   ["技术替代风险", "地缘政治风险"],
    # 医药
    "化学制药": ["集采政策风险", "研发管线不确定性"],
    "中成药":   ["集采政策风险", "政策定价"],
    "生物制药": ["研发管线风险", "技术突破不确定性", "商业化不确定性"],
    "医疗保健": ["集采政策风险"],
    "医药商业": ["集采传导风险"],
    # 消费
    "白酒":     ["消费风格偏好", "高端化趋势持续性"],
    "啤酒":     ["消费升级持续性", "竞争格局变化"],
    "乳制品":   ["食品安全风险", "竞争格局变化"],
    # 制造
    "汽车整车": ["技术路线风险(电动化)", "竞争格局变化", "商业模式变化风险"],
    "汽车配件": ["技术路线风险(电动化)", "客户集中度风险"],
    "工程机械": ["宏观周期位置判断", "海外扩张风险"],
    "新型电力": ["政策补贴依赖", "技术路线不确定性"],
    "电气设备": ["技术突破不确定性", "竞争格局变化"],
    # 航运物流
    "空运":     ["宏观周期位置判断", "油价敏感", "运力过剩风险"],
    "水运":     ["宏观周期位置判断", "运价周期敏感"],
    "仓储物流": ["竞争格局变化", "商业模式变化风险"],
    # 农业
    "农业综合": ["农产品价格周期", "气候政策风险"],
    "饲料":     ["原材料价格波动", "养殖周期敏感"],
}

# ── 行业倍数基准（每年按市场行情校准一次）──────────────────────────────────
PE_BENCHMARKS: dict[str, float] = {
    "白酒":   25.0,
    "啤酒":   30.0,
    "软饮料": 22.0,
    "乳制品": 20.0,
}
PS_BENCHMARKS: dict[str, float] = {
    "生物制药": 6.0,
}

# ── 行业 → 估值方法映射 ──────────────────────────────────────────────────────
INDUSTRY_METHOD: dict[str, str] = {
    # ── P/B + ROE 戈登增长（金融 / 地产 / 电力运营）─────────────────────────
    "银行":     "pb_roe",
    "保险":     "pb_roe",
    "证券":     "pb_roe",
    "多元金融": "pb_roe",
    "全国地产": "pb_roe",
    "区域地产": "pb_roe",
    "园区开发": "pb_roe",
    "建筑工程": "dcf_capex",  # v2.3：从 pb_roe 移入，高债务+订单驱动，需走 EV 路径扣减债务
    "路桥":     "pb_roe",    # 特许经营资产，现金流稳定，净资产定价仍适用
    "火力发电": "pb_roe",   # v2.1：原 dcf_capex，重负债监管电力，净资产定价更合适
    "水力发电": "pb_roe",   # v2.1：同上
    "新型电力": "pb_roe",   # v2.1：同上（核电/风电/光伏运营商，净债务动辄 2000亿+）

    # ── DCF − capex（重资产 + 制造业 + 电信）────────────────────────────────
    "半导体":   "dcf_capex",
    "元器件":   "dcf_capex",
    "电气设备": "dcf_capex",
    "通信设备": "dcf_capex",
    "运输设备": "dcf_capex",
    "铁路":     "dcf_capex",
    "机场":     "dcf_capex",
    "港口":     "dcf_capex",
    "供气供热": "dcf_capex",
    "汽车整车": "dcf_capex",   # v2.0：从 dcf_std 移入
    "汽车配件": "dcf_capex",   # v2.0：从 dcf_std 移入
    "工程机械": "dcf_capex",   # v2.0：从 dcf_std 移入
    "电信运营": "dcf_capex",   # v2.1：从 dcf_std 移入，年 capex 400-800亿不可忽略

    # ── 穿越周期 DCF（强周期 / 大宗商品 / 民航）─────────────────────────────
    "煤炭开采": "dcf_cycle",
    "石油开采": "dcf_cycle",
    "石油加工": "dcf_cycle",
    "黄金":     "dcf_cycle",
    "铜":       "dcf_cycle",
    "铝":       "dcf_cycle",
    "小金属":   "dcf_cycle",
    "普钢":     "dcf_cycle",
    "特种钢":   "dcf_cycle",
    "化工原料": "dcf_cycle",
    "农药化肥": "dcf_cycle",
    "化纤":     "dcf_cycle",
    "水泥":     "dcf_cycle",
    "玻璃":     "dcf_cycle",
    "船舶":     "dcf_cycle",
    "空运":     "dcf_cycle",   # v2.1：从 dcf_capex 移入，COVID 后单年 OCF 暴增需均值平滑

    # ── PE 消费垄断 ──────────────────────────────────────────────────────────
    "白酒":     "pe_consumer",
    "啤酒":     "pe_consumer",
    "软饮料":   "pe_consumer",
    "乳制品":   "pe_consumer",

    # ── 成熟药企 DCF ─────────────────────────────────────────────────────────
    "化学制药": "dcf_pharma",
    "中成药":   "dcf_pharma",
    "医疗保健": "dcf_pharma",
    "医药商业": "dcf_pharma",

    # ── 创新药 PS 法 ─────────────────────────────────────────────────────────
    "生物制药": "ps_biotech",

    # ── 软周期均值 DCF ───────────────────────────────────────────────────────
    "农业综合": "dcf_cycle_soft",
    "饲料":     "dcf_cycle_soft",
    "水运":     "dcf_cycle_soft",

    # 其余行业默认 dcf_std（软件 / 家电 / 食品 / 物流 / 影视 等）
}


# ════════════════════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════════════════════

def _to_float(val) -> float:
    """安全转换 float；兼容 text、None、'NaN'、inf。"""
    v = pd.to_numeric(val, errors="coerce")
    if pd.isna(v):
        return 0.0
    f = float(v)
    return 0.0 if not math.isfinite(f) else f


# ════════════════════════════════════════════════════════════════════════════
# 数据库查询层
# ════════════════════════════════════════════════════════════════════════════

def _fetch_income(conn, ts_code: str, n: int = 5) -> pd.DataFrame:
    return pd.read_sql(
        text("""
            SELECT end_date, revenue, n_income_attr_p
            FROM income_statement
            WHERE ts_code = :c
            ORDER BY end_date DESC LIMIT :n
        """),
        conn, params={"c": ts_code, "n": n},
    ).fillna(0)


def _fetch_cashflow(conn, ts_code: str, n: int = 5) -> pd.DataFrame:
    return pd.read_sql(
        text("""
            SELECT end_date, n_cashflow_act, c_pay_acq_const_fiolta
            FROM cash_flow_statement
            WHERE ts_code = :c
            ORDER BY end_date DESC LIMIT :n
        """),
        conn, params={"c": ts_code, "n": n},
    ).fillna(0)


def _fetch_balance(conn, ts_code: str) -> pd.Series:
    """
    读取最新一期资产负债表。
    v2.3：扩展有息负债覆盖范围，补入应付债券 / 一年内到期非流动负债 / 租赁负债。
    交易性金融资产（短期理财）加入现金侧。
    全部用 COALESCE 兜底，字段不存在时不报错。
    """
    df = pd.read_sql(
        text("""
            SELECT COALESCE(money_cap::numeric, 0)           AS money_cap,
                   COALESCE(trad_asset, 0)                   AS trad_asset,
                   COALESCE(st_borr::numeric, 0)             AS st_borr,
                   COALESCE(lt_borr::numeric, 0)             AS lt_borr,
                   COALESCE(bond_payable, 0)                 AS bond_payable,
                   COALESCE(non_cur_liab_due_1y::numeric, 0) AS non_cur_liab_due_1y,
                   COALESCE(lease_liab::numeric, 0)          AS lease_liab,
                   total_hldr_eqy_exc_min_int,
                   total_hldr_eqy_inc_min_int
            FROM balance_sheet
            WHERE ts_code = :c
            ORDER BY end_date DESC LIMIT 1
        """),
        conn, params={"c": ts_code},
    )
    return df.iloc[0] if not df.empty else pd.Series(dtype=float)


# ════════════════════════════════════════════════════════════════════════════
# 估值辅助函数
# ════════════════════════════════════════════════════════════════════════════

def _revenue_cagr(
    income_df: pd.DataFrame,
    cap_hi: float = 0.25,
    cap_lo: float = -0.10,
) -> float:
    if len(income_df) < 2:
        return 0.05
    revs = income_df["revenue"].astype(float).values[::-1]
    if revs[0] <= 0:
        return 0.05
    try:
        cagr = (revs[-1] / revs[0]) ** (1.0 / (len(revs) - 1)) - 1
    except (ZeroDivisionError, ValueError):
        return 0.05
    return float(max(min(cagr, cap_hi), cap_lo))


def _roe_g(
    income_df: pd.DataFrame,
    bs: pd.Series,
    cap_hi: float = 0.20,
    cap_lo: float = -0.10,
    retention: float = 0.60,
) -> tuple[float, float | None]:
    """
    可持续增长率：g = ROE × 留存收益率（收入增长时）

    收入萎缩优先：若近年收入 CAGR < 0，直接用收入萎缩率作为 g（钳位至 cap_lo），
    不再用 ROE 法，避免 ROE 正值掩盖收入下行趋势。收入萎缩时主流程会在
    "可识别风险"中自动标注"收入萎缩(x.x%)"。

    收入增长时：g = ROE × 留存收益率（ROE = 3年均净利润 / 最新净资产，
    留存收益率默认 0.6，即 A 股平均分红率约 40%）。
    高杠杆公司 ROE 会被杠杆虚高，需结合"高负债压估值"标注一起看。

    返回 (g, roe)；equity 为零/负时返回 (0.05, None)。
    """
    equity = _to_float(bs.get("total_hldr_eqy_exc_min_int")) or \
             _to_float(bs.get("total_hldr_eqy_inc_min_int"))
    if equity <= 0 or income_df.empty:
        return 0.05, None

    net_profit_avg = income_df["n_income_attr_p"].astype(float).mean()
    roe = net_profit_avg / equity

    # ROE 异常值折扣：超过 30% 的部分打五折，防止高杠杆/高单期利润直接推高 g
    if roe > 0.30:
        roe_for_g = 0.30 + (roe - 0.30) * 0.5
    else:
        roe_for_g = roe

    g_rev = _revenue_cagr(income_df, cap_hi=999)  # 不钳位上限，只看方向
    if g_rev < 0:
        g = float(max(g_rev, cap_lo))  # 收入萎缩：直接用萎缩率，钳位至 cap_lo
    else:
        g = roe_for_g * retention      # 收入增长：用折扣后 ROE 法

    return float(max(min(g, cap_hi), cap_lo)), float(roe)  # 返回原始 ROE 供展示


def _dcf_ev(base_fcf: float, g: float, wacc: float = DEFAULT_WACC) -> float:
    pv = sum(
        base_fcf * (1 + g) ** t / (1 + wacc) ** t
        for t in range(1, YEARS + 1)
    )
    tv_pv = (
        base_fcf * (1 + g) ** YEARS * (1 + TERMINAL_GROWTH)
        / (wacc - TERMINAL_GROWTH)
    ) / (1 + wacc) ** YEARS
    return pv + tv_pv


def _ev_to_price(
    ev: float,
    cash: float,
    debt: float,
    total_shares_wan: float,
) -> float | None:
    """
    EV + 净现金 → 每股股权价值。
    v2.3：允许返回负值，负值代表债务超过经营价值，
    由主流程标注"DCF股权为负"而非直接跳过。
    """
    if total_shares_wan <= 0:
        return None
    return (ev + cash - debt) / (total_shares_wan * 1e4)


def _scenario_fvs(
    base_fcf: float, g: float,
    cash: float, debt: float, total_shares_wan: float,
    cap_lo: float, cap_hi: float,
    wacc: float = DEFAULT_WACC,
) -> tuple[float | None, float | None]:
    """悲观/乐观情景价格：g ± DELTA_G，钳位至各方法的 cap_lo / cap_hi。"""
    g_bear = max(g - DELTA_G, cap_lo)
    g_bull = min(g + DELTA_G, cap_hi)
    fv_bear = _ev_to_price(_dcf_ev(base_fcf, g_bear, wacc), cash, debt, total_shares_wan)
    fv_bull = _ev_to_price(_dcf_ev(base_fcf, g_bull, wacc), cash, debt, total_shares_wan)
    return fv_bear, fv_bull


def _net_cash(bs: pd.Series) -> tuple[float, float]:
    """
    从资产负债表 Series 提取现金和有息负债总额（元）。

    现金 = 货币资金 + 交易性金融资产（短期理财，流动性等同现金）
    债务 = 短期借款 + 长期借款 + 应付债券 + 一年内到期非流动负债 + 租赁负债

    v2.3 改动：正式补入 lease_liab。
    """
    if bs.empty:
        return 0.0, 0.0
    cash = (
        _to_float(bs.get("money_cap"))
        + _to_float(bs.get("trad_asset"))          # 交易性金融资产
    )
    debt = (
        _to_float(bs.get("st_borr"))               # 短期借款
        + _to_float(bs.get("lt_borr"))             # 长期借款
        + _to_float(bs.get("bond_payable"))        # 应付债券
        + _to_float(bs.get("non_cur_liab_due_1y")) # 一年内到期非流动负债
        + _to_float(bs.get("lease_liab"))          # 租赁负债
    )
    return cash, debt


# ════════════════════════════════════════════════════════════════════════════
# 估值方法（8 种）
# ════════════════════════════════════════════════════════════════════════════

def _pb_roe(
    conn, ts_code: str, total_shares_wan: float, current_price: float | None = None,
    wacc: float = DEFAULT_WACC,
) -> dict:
    """P/B + ROE 戈登增长（银行/保险/证券/地产/电力运营）"""
    income_df = _fetch_income(conn, ts_code, 3)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty or bs.empty:
        return {"error": "缺少净资产或利润数据"}

    equity = _to_float(bs.get("total_hldr_eqy_exc_min_int")) or \
             _to_float(bs.get("total_hldr_eqy_inc_min_int"))
    if equity <= 0:
        return {"error": "净资产为零或负"}

    net_profit_avg = income_df["n_income_attr_p"].astype(float).mean()
    roe = net_profit_avg / equity
    g   = TERMINAL_GROWTH

    fair_pb = (roe - g) / (wacc - g) if (wacc > g and roe > g) else 1.0
    fair_pb = max(0.3, min(fair_pb, 6.0))

    total_shares   = total_shares_wan * 1e4
    book_per_share = equity / total_shares
    fair_per_share = fair_pb * book_per_share
    cur_pb = (current_price / book_per_share) if (current_price and book_per_share > 0) else None

    return {
        "方法":           "P/B+ROE",
        "fair_per_share": round(fair_per_share, 2),
        "base_fcf_yi":    round(net_profit_avg / 1e8, 2),
        "growth_rate":    g,
        "fair_pb":        round(fair_pb, 2),
        "cur_pb":         round(cur_pb, 2) if cur_pb else None,
        "roe_pct":        round(roe * 100, 1),
        "book_per_share": round(book_per_share, 2),
        "ev_yi": None, "cash_yi": None, "debt_yi": None,
        "fair_bear": None, "fair_bull": None,
    }


def _dcf_capex(conn, ts_code: str, total_shares_wan: float,
               wacc: float = DEFAULT_WACC) -> dict:
    """DCF 扣减资本开支（重资产/汽车/工程机械/电信）"""
    income_df = _fetch_income(conn, ts_code)
    cf_df     = _fetch_cashflow(conn, ts_code)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    ocf_raw = 0.0
    fcf     = 0.0
    if not cf_df.empty:
        ocf_raw = _to_float(cf_df.iloc[0]["n_cashflow_act"])
        capex   = abs(_to_float(cf_df.iloc[0]["c_pay_acq_const_fiolta"]))
        fcf     = ocf_raw - capex
    if fcf <= 0:
        fcf = _to_float(income_df.iloc[0]["n_income_attr_p"]) * 0.6

    g, roe = _roe_g(income_df, bs, cap_hi=0.20)
    ev = _dcf_ev(fcf, g, wacc)
    cash, debt = _net_cash(bs)
    fv = _ev_to_price(ev, cash, debt, total_shares_wan)
    fv_bear, fv_bull = _scenario_fvs(fcf, g, cash, debt, total_shares_wan,
                                     cap_lo=-0.10, cap_hi=0.20, wacc=wacc)

    return {
        "方法":           "DCF(OCF−capex)",
        "fair_per_share": round(fv, 2) if fv is not None else None,
        "fair_bear":      round(fv_bear, 2) if fv_bear is not None else None,
        "fair_bull":      round(fv_bull, 2) if fv_bull is not None else None,
        "base_fcf_yi":   round(fcf / 1e8, 2),
        "ocf_raw_yi":    round(ocf_raw / 1e8, 2),
        "growth_rate":   round(g, 4),
        "ev_yi":         round(ev / 1e8, 1),
        "cash_yi":       round(cash / 1e8, 1),
        "debt_yi":       round(debt / 1e8, 1),
        "roe_pct":       round(roe * 100, 1) if roe is not None else None,
    }


def _dcf_cycle(conn, ts_code: str, total_shares_wan: float,
               wacc: float = DEFAULT_WACC) -> dict:
    """穿越周期 DCF（强周期/大宗商品/民航）- 近3年正值FCF均值"""
    income_df = _fetch_income(conn, ts_code, 5)
    cf_df     = _fetch_cashflow(conn, ts_code, 5)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    ocf_raw  = _to_float(cf_df.iloc[0]["n_cashflow_act"]) if not cf_df.empty else 0.0
    fcf_list = []
    for _, row in cf_df.head(3).iterrows():
        ocf   = _to_float(row["n_cashflow_act"])
        capex = abs(_to_float(row["c_pay_acq_const_fiolta"]))
        f     = ocf - capex
        if f > 0:
            fcf_list.append(f)

    if fcf_list:
        fcf = sum(fcf_list) / len(fcf_list)
    else:
        fcf = max(_to_float(income_df.iloc[0]["n_income_attr_p"]) * 0.4, 0.0)

    g, roe = _roe_g(income_df, bs, cap_hi=0.12, cap_lo=-0.05)
    ev = _dcf_ev(fcf, g, wacc)
    cash, debt = _net_cash(bs)
    fv = _ev_to_price(ev, cash, debt, total_shares_wan)
    fv_bear, fv_bull = _scenario_fvs(fcf, g, cash, debt, total_shares_wan,
                                     cap_lo=-0.05, cap_hi=0.12, wacc=wacc)

    return {
        "方法":           f"穿越周期DCF(n={len(fcf_list)}年均值)",
        "fair_per_share": round(fv, 2) if fv is not None else None,
        "fair_bear":      round(fv_bear, 2) if fv_bear is not None else None,
        "fair_bull":      round(fv_bull, 2) if fv_bull is not None else None,
        "base_fcf_yi":   round(fcf / 1e8, 2),
        "ocf_raw_yi":    round(ocf_raw / 1e8, 2),
        "growth_rate":   round(g, 4),
        "ev_yi":         round(ev / 1e8, 1),
        "cash_yi":       round(cash / 1e8, 1),
        "debt_yi":       round(debt / 1e8, 1),
        "roe_pct":       round(roe * 100, 1) if roe is not None else None,
    }


def _dcf_std(conn, ts_code: str, total_shares_wan: float,
             wacc: float = DEFAULT_WACC) -> dict:
    """标准 DCF（稳定现金流/轻资产 - 默认兜底）"""
    income_df = _fetch_income(conn, ts_code)
    cf_df     = _fetch_cashflow(conn, ts_code)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    ocf_raw = 0.0
    fcf     = 0.0
    if not cf_df.empty:
        ocf_raw = _to_float(cf_df.iloc[0]["n_cashflow_act"])
        if ocf_raw > 0:
            fcf = ocf_raw
    if fcf <= 0:
        fcf = _to_float(income_df.iloc[0]["n_income_attr_p"]) * 0.8

    g, roe = _roe_g(income_df, bs, cap_hi=0.20)
    ev = _dcf_ev(fcf, g, wacc)
    cash, debt = _net_cash(bs)
    fv = _ev_to_price(ev, cash, debt, total_shares_wan)
    fv_bear, fv_bull = _scenario_fvs(fcf, g, cash, debt, total_shares_wan,
                                     cap_lo=-0.10, cap_hi=0.20, wacc=wacc)

    return {
        "方法":           "标准DCF",
        "fair_per_share": round(fv, 2) if fv is not None else None,
        "fair_bear":      round(fv_bear, 2) if fv_bear is not None else None,
        "fair_bull":      round(fv_bull, 2) if fv_bull is not None else None,
        "base_fcf_yi":   round(fcf / 1e8, 2),
        "ocf_raw_yi":    round(ocf_raw / 1e8, 2),
        "growth_rate":   round(g, 4),
        "ev_yi":         round(ev / 1e8, 1),
        "cash_yi":       round(cash / 1e8, 1),
        "debt_yi":       round(debt / 1e8, 1),
        "roe_pct":       round(roe * 100, 1) if roe is not None else None,
    }


def _pe_consumer(
    conn, ts_code: str, total_shares_wan: float, industry: str = "",
) -> dict:
    """消费垄断 PE 中枢法（白酒/啤酒/软饮料/乳制品）

    收入萎缩时改用最近1年净利润作为盈利基准，避免3年均值掩盖下行趋势，
    并将收入CAGR填入growth_rate以触发"收入萎缩"风险标注。
    """
    income_df = _fetch_income(conn, ts_code, 3)
    if income_df.empty:
        return {"error": "缺少利润数据"}

    g_rev = _revenue_cagr(income_df, cap_hi=999)  # 不钳位上限，只看方向

    if g_rev < 0:
        # 收入萎缩：用最近1年净利润，不用均值（均值会拉高已下行的盈利基准）
        net_profit_base = float(income_df.iloc[0]["n_income_attr_p"])
        growth_rate = round(g_rev, 4)
    else:
        # 收入正常：3年均净利润平滑波动
        net_profit_base = income_df["n_income_attr_p"].astype(float).mean()
        growth_rate = None

    if net_profit_base <= 0:
        return {"error": "净利润为负，PE法无效"}

    pe = PE_BENCHMARKS.get(industry, 25.0)
    fv = (net_profit_base * pe) / (total_shares_wan * 1e4)

    return {
        "方法":           f"PE消费({pe:.0f}x)",
        "fair_per_share": round(fv, 2),
        "base_fcf_yi":   round(net_profit_base / 1e8, 2),
        "growth_rate":   growth_rate,
        "ev_yi": None, "cash_yi": None, "debt_yi": None,
        "fair_pb": None, "cur_pb": None, "roe_pct": None, "book_per_share": None,
        "fair_bear": None, "fair_bull": None,
    }


def _dcf_pharma(conn, ts_code: str, total_shares_wan: float,
                wacc: float = DEFAULT_WACC) -> dict:
    """成熟药企 DCF（化学制药/中成药/医疗保健/医药商业）- g 上限 18%"""
    income_df = _fetch_income(conn, ts_code)
    cf_df     = _fetch_cashflow(conn, ts_code)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    ocf_raw = 0.0
    fcf     = 0.0
    if not cf_df.empty:
        ocf_raw = _to_float(cf_df.iloc[0]["n_cashflow_act"])
        if ocf_raw > 0:
            fcf = ocf_raw
    if fcf <= 0:
        fcf = _to_float(income_df.iloc[0]["n_income_attr_p"]) * 0.75

    g, roe = _roe_g(income_df, bs, cap_hi=0.18, cap_lo=-0.10)
    ev = _dcf_ev(fcf, g, wacc)
    cash, debt = _net_cash(bs)
    fv = _ev_to_price(ev, cash, debt, total_shares_wan)
    fv_bear, fv_bull = _scenario_fvs(fcf, g, cash, debt, total_shares_wan,
                                     cap_lo=-0.10, cap_hi=0.18, wacc=wacc)

    return {
        "方法":           "DCF医药(g≤18%)",
        "fair_per_share": round(fv, 2) if fv is not None else None,
        "fair_bear":      round(fv_bear, 2) if fv_bear is not None else None,
        "fair_bull":      round(fv_bull, 2) if fv_bull is not None else None,
        "base_fcf_yi":   round(fcf / 1e8, 2),
        "ocf_raw_yi":    round(ocf_raw / 1e8, 2),
        "growth_rate":   round(g, 4),
        "ev_yi":         round(ev / 1e8, 1),
        "cash_yi":       round(cash / 1e8, 1),
        "debt_yi":       round(debt / 1e8, 1),
        "roe_pct":       round(roe * 100, 1) if roe is not None else None,
    }


def _ps_biotech(
    conn, ts_code: str, total_shares_wan: float, industry: str = "",
) -> dict:
    """创新药 PS 倍数法（生物制药）- FCF 长期为负时的替代

    收入已是最近1年最新值，但仍计算CAGR填入growth_rate以触发"收入萎缩"标注。
    """
    income_df = _fetch_income(conn, ts_code, 3)  # 需至少2行才能算CAGR
    if income_df.empty:
        return {"error": "缺少收入数据"}

    revenue = _to_float(income_df.iloc[0]["revenue"])
    if revenue <= 0:
        return {"error": "收入为零，PS法无效"}

    g_rev = _revenue_cagr(income_df, cap_hi=999)
    growth_rate = round(g_rev, 4) if g_rev < 0 else None

    ps = PS_BENCHMARKS.get(industry, 6.0)
    fv = (revenue * ps) / (total_shares_wan * 1e4)

    return {
        "方法":           f"PS生物({ps:.0f}x)",
        "fair_per_share": round(fv, 2),
        "base_fcf_yi":   round(revenue / 1e8, 2),
        "growth_rate":   growth_rate,
        "ev_yi": None, "cash_yi": None, "debt_yi": None,
        "fair_pb": None, "cur_pb": None, "roe_pct": None, "book_per_share": None,
        "fair_bear": None, "fair_bull": None,
    }


def _dcf_cycle_soft(conn, ts_code: str, total_shares_wan: float,
                    wacc: float = DEFAULT_WACC) -> dict:
    """软周期均值 DCF（农业综合/饲料/水运）- 2年均值 g 上限 15%"""
    income_df = _fetch_income(conn, ts_code, 3)
    cf_df     = _fetch_cashflow(conn, ts_code, 3)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    ocf_raw  = _to_float(cf_df.iloc[0]["n_cashflow_act"]) if not cf_df.empty else 0.0
    fcf_list = []
    for _, row in cf_df.head(2).iterrows():
        ocf   = _to_float(row["n_cashflow_act"])
        capex = abs(_to_float(row["c_pay_acq_const_fiolta"]))
        f     = ocf - capex
        if f > 0:
            fcf_list.append(f)

    if fcf_list:
        fcf = sum(fcf_list) / len(fcf_list)
    else:
        fcf = max(_to_float(income_df.iloc[0]["n_income_attr_p"]) * 0.5, 0.0)

    g, roe = _roe_g(income_df, bs, cap_hi=0.15, cap_lo=-0.08)
    ev = _dcf_ev(fcf, g, wacc)
    cash, debt = _net_cash(bs)
    fv = _ev_to_price(ev, cash, debt, total_shares_wan)
    fv_bear, fv_bull = _scenario_fvs(fcf, g, cash, debt, total_shares_wan,
                                     cap_lo=-0.08, cap_hi=0.15, wacc=wacc)

    return {
        "方法":           f"软周期DCF(n={len(fcf_list)}年均值)",
        "fair_per_share": round(fv, 2) if fv is not None else None,
        "fair_bear":      round(fv_bear, 2) if fv_bear is not None else None,
        "fair_bull":      round(fv_bull, 2) if fv_bull is not None else None,
        "base_fcf_yi":   round(fcf / 1e8, 2),
        "ocf_raw_yi":    round(ocf_raw / 1e8, 2),
        "growth_rate":   round(g, 4),
        "ev_yi":         round(ev / 1e8, 1),
        "cash_yi":       round(cash / 1e8, 1),
        "debt_yi":       round(debt / 1e8, 1),
        "roe_pct":       round(roe * 100, 1) if roe is not None else None,
    }


# ════════════════════════════════════════════════════════════════════════════
# 统一估值入口
# ════════════════════════════════════════════════════════════════════════════

class UnifiedValuation:
    """单只股票估值调度器，自动根据行业选择估值方法。"""

    def __init__(self, db_url: str = DB_URL):
        self.engine = create_engine(db_url)

    def calc(
        self,
        ts_code: str,
        industry: str,
        total_shares_wan: float,
        current_price: float | None = None,
    ) -> dict:
        method = INDUSTRY_METHOD.get(industry, "dcf_std")
        wacc   = INDUSTRY_WACC.get(industry, DEFAULT_WACC)
        with self.engine.connect() as conn:
            try:
                match method:
                    case "pb_roe":
                        r = _pb_roe(conn, ts_code, total_shares_wan, current_price, wacc)
                    case "dcf_capex":
                        r = _dcf_capex(conn, ts_code, total_shares_wan, wacc)
                    case "dcf_cycle":
                        r = _dcf_cycle(conn, ts_code, total_shares_wan, wacc)
                    case "pe_consumer":
                        r = _pe_consumer(conn, ts_code, total_shares_wan, industry)
                    case "dcf_pharma":
                        r = _dcf_pharma(conn, ts_code, total_shares_wan, wacc)
                    case "ps_biotech":
                        r = _ps_biotech(conn, ts_code, total_shares_wan, industry)
                    case "dcf_cycle_soft":
                        r = _dcf_cycle_soft(conn, ts_code, total_shares_wan, wacc)
                    case _:
                        r = _dcf_std(conn, ts_code, total_shares_wan, wacc)
            except Exception as exc:
                r = {"error": str(exc)}

        r["ts_code"]  = ts_code
        r["industry"] = industry
        r.setdefault("方法", method)
        return r


# ════════════════════════════════════════════════════════════════════════════
# 数据库数据加载
# ════════════════════════════════════════════════════════════════════════════

def load_market_data(engine) -> tuple[dict, dict]:
    with engine.connect() as conn:
        price_df = pd.read_sql(
            text("""
                SELECT ts_code, close
                FROM stock_daily_hist
                WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_hist)
            """), conn,
        )
        share_df = pd.read_sql(
            text("""
                SELECT DISTINCT ON (ts_code)
                       ts_code, total_share / 1e4 AS total_share_wan
                FROM balance_sheet
                WHERE total_share IS NOT NULL
                ORDER BY ts_code, end_date DESC
            """), conn,
        )
    price_map = dict(zip(price_df["ts_code"], price_df["close"].astype(float)))
    share_map = dict(zip(share_df["ts_code"], share_df["total_share_wan"].astype(float)))
    return price_map, share_map


def load_stock_info(engine) -> dict:
    with engine.connect() as conn:
        df = pd.read_sql(text("SELECT ts_code, name, industry FROM stock_basic"), conn)
    return {row["ts_code"]: row for row in df.to_dict("records")}


def load_hs300_codes(engine) -> list[str]:
    with engine.connect() as conn:
        df = pd.read_sql(
            text("""
                SELECT ts_code FROM index_components
                WHERE index_code = '000300.SH'
                ORDER BY weight DESC
            """), conn,
        )
    return df["ts_code"].tolist()


# ════════════════════════════════════════════════════════════════════════════
# 风险标注生成
# ════════════════════════════════════════════════════════════════════════════

def _build_risk_notes(
    r: dict,
    mc_yi: float,
    gap: float | None,
    industry: str,
) -> tuple[str, str]:
    """
    生成两类风险标注：
      可识别风险  — 从财务数据中自动检测的量化信号
      不可量化提示 — 行业特有的 DCF 盲区，无法从数字中推断

    返回 (可识别风险字符串, 不可量化提示字符串)
    """
    quantifiable   = []
    unquantifiable = list(INDUSTRY_UNQUANTIFIABLE_RISKS.get(industry, []))

    fcf_yi  = r.get("base_fcf_yi") or 0
    g       = r.get("growth_rate")
    debt_yi = r.get("debt_yi") or 0
    ev_yi   = r.get("ev_yi")   or 0
    method  = r.get("方法", "")
    roe_pct = r.get("roe_pct") or 0

    # 1. 成长溢价：市值 / FCF 超过阈值
    if fcf_yi > 0 and mc_yi / fcf_yi > GROWTH_PREMIUM_THRESHOLD:
        quantifiable.append(f"成长溢价({mc_yi / fcf_yi:.0f}x)")

    # 2. g 触顶：增长率假设被钳位，估值对 g 极敏感
    if g is not None:
        for method_prefix, cap in METHOD_G_CAPS.items():
            if method.startswith(method_prefix) and abs(g - cap) < 0.001:
                quantifiable.append(f"增长率触顶({cap * 100:.0f}%)")
                break

    # 3. 高负债压估值：净债务 / EV > 60%
    if ev_yi > 0 and debt_yi / ev_yi > 0.6:
        quantifiable.append(f"高负债压估值(债务/EV={debt_yi/ev_yi:.0%})")

    # 4. 收入萎缩
    if g is not None and g < 0:
        quantifiable.append(f"收入萎缩({g * 100:.1f}%)")

    # 5. ROE 异常偏高（已在 _roe_g 折扣处理）
    if roe_pct > 30:
        quantifiable.append(f"ROE异常偏高({roe_pct:.1f}%)，已折扣处理")

    # 6. DCF 大幅偏离市价
    if gap is not None and gap < -70:
        quantifiable.append(f"DCF低于市价{abs(gap):.0f}%")
    elif gap is not None and gap > 150:
        quantifiable.append(f"DCF高于市价{gap:.0f}%")

    # 若行业无预设不可量化标签，加通用提示
    if not unquantifiable:
        unquantifiable = ["管理层质量", "竞争格局变化"]

    # 通用不可量化因子（所有股票都有）
    unquantifiable.append("风格偏好")

    return " | ".join(quantifiable), " | ".join(unquantifiable)


# ════════════════════════════════════════════════════════════════════════════
# 启动前校验
# ════════════════════════════════════════════════════════════════════════════

REQUIRED_TABLES: dict[str, list[str]] = {
    "stock_daily_hist":    ["ts_code", "trade_date", "close"],
    "stock_basic":         ["ts_code", "name", "industry"],
    "balance_sheet":       ["ts_code", "end_date", "total_share",
                            "money_cap", "st_borr", "lt_borr",
                            "lease_liab",
                            "total_hldr_eqy_exc_min_int"],
                            # bond_payable / non_cur_liab_due_1y / trad_asset
                            # 用 COALESCE 兜底，不在强校验列表里（老数据可能没这些字段）
    "index_components":    ["index_code", "ts_code", "weight"],
    "income_statement":    ["ts_code", "end_date", "revenue", "n_income_attr_p"],
    "cash_flow_statement": ["ts_code", "end_date",
                            "n_cashflow_act", "c_pay_acq_const_fiolta"],
}


def check_tables(engine) -> bool:
    passed = True
    with engine.connect() as conn:
        for table, required_cols in REQUIRED_TABLES.items():
            exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = :t
                )
            """), {"t": table}).scalar()
            if not exists:
                log.error(f"  ✗ 表不存在：{table}")
                passed = False
                continue

            col_rows = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :t
            """), {"t": table}).fetchall()
            existing_cols = {row[0] for row in col_rows}
            missing = [c for c in required_cols if c not in existing_cols]
            if missing:
                log.error(f"  ✗ 表 {table} 缺少字段：{missing}")
                passed = False
                continue

            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} LIMIT 1")
            ).scalar()
            if count == 0:
                log.error(f"  ✗ 表存在但无数据：{table}")
                passed = False
                continue

            log.info(f"  ✓ {table}")
    return passed


# ════════════════════════════════════════════════════════════════════════════
# CSV 说明头
# ════════════════════════════════════════════════════════════════════════════

def _write_legend(f, n_results: int) -> None:
    """在 CSV 最前面写方法说明（## 前缀，Excel 中显示为普通行，文本编辑器一目了然）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"## HS300 全行业细分估值  生成时间: {ts}  共 {n_results} 只",
        "##",
        "## ── 全局参数 ──────────────────────────────────────────────────────────────",
        f"## WACC={WACC:.0%}  终值增长率={TERMINAL_GROWTH:.0%}  预测期={YEARS}年"
        f"  成长溢价阈值={GROWTH_PREMIUM_THRESHOLD:.0f}x（市值/FCF超此值触发标记）",
        "##",
        "## ── 估值方法说明 ───────────────────────────────────────────────────────────",
        "## 方法名称           适用行业                    核心逻辑",
        "## ─────────────────  ──────────────────────────  ─────────────────────────────────────────────",
        "## P/B+ROE            银行/保险/证券/地产/         戈登增长: 合理PB=(ROE−g)/(WACC−g)",
        "##                    建筑/路桥/电力运营           g固定取终值增长率=2%",
        "## DCF(OCF−capex)     半导体/元器件/电气设备/      FCF=经营现金流−资本开支",
        "##                    通信设备/汽车/工程机械/       g=ROE×留存收益率(60%)，上限20%",
        "##                    电信运营/铁路/机场/港口",
        "## 穿越周期DCF        煤炭/石油/化工/有色/钢铁/    FCF=近3年正值FCF均值（平滑周期波动）",
        "##                    水泥/玻璃/船舶/空运           g∈[−5%, +12%]",
        "## 标准DCF            软件/家电/食品/物流/          FCF=OCF（无capex扣减）",
        "##                    影视/商品城等（默认兜底）      g∈[−10%, +20%]",
        f"## PE消费             白酒({PE_BENCHMARKS.get('白酒',25):.0f}x)/"
        f"啤酒({PE_BENCHMARKS.get('啤酒',30):.0f}x)/"
        f"软饮料({PE_BENCHMARKS.get('软饮料',22):.0f}x)/"
        f"乳制品({PE_BENCHMARKS.get('乳制品',20):.0f}x)   合理市值=行业PE×3年均净利润",
        "## DCF医药            化学制药/中成药/              标准DCF变体，g上限18%",
        "##                    医疗保健/医药商业             fallback净利润×0.75",
        f"## PS生物             生物制药                     合理市值=PS({PS_BENCHMARKS.get('生物制药',6):.0f}x)×年收入（FCF长期为负时替代）",
        "## 软周期DCF          农业综合/饲料/水运            FCF=近2年正值FCF均值，g∈[−8%, +15%]",
        "##",
        "## ── 增长率(g)计算逻辑 ─────────────────────────────────────────────────────",
        "## 1. 先算历史收入CAGR（不钳位上限，只看方向）",
        "## 2. 收入CAGR < 0：g = 收入萎缩率（钳位至各方法cap_lo），同时标注[收入萎缩]",
        "## 3. 收入CAGR ≥ 0：g = ROE × 留存收益率(60%)，再按各方法上限钳位",
        "##    ROE = 3年均归母净利润 / 最新归母净资产",
        "##",
        "## ── 净债务计算口径 ─────────────────────────────────────────────────────────",
        "## 债务 = 短期借款 + 长期借款 + 应付债券 + 一年内到期非流动负债 + 租赁负债",
        "## 现金 = 货币资金 + 交易性金融资产（短期理财）",
        "## 净债务 = 债务 − 现金（正值=净负债，负值=净现金）",
        "##",
        "## ── 可识别风险标注规则 ─────────────────────────────────────────────────────",
        f"## 成长溢价      市值/FCF > {GROWTH_PREMIUM_THRESHOLD:.0f}x，DCF估值可信度低，市场已定价高增长预期",
        "## 增长率触顶    g被钳位至方法上限，估值对g极度敏感（小幅g变化→大幅估值波动）",
        "## 高负债压估值  净债务/EV > 60%，债务占经营价值比例过高",
        "## 收入萎缩      历史收入CAGR为负，g被强制为负值（不用ROE法）",
        "## DCF股权为负   净债务 > EV，债务超过企业经营价值，股权价值在DCF框架下为负",
        "##",
    ]
    for line in lines:
        f.write(line + "\n")


# ════════════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    db = create_engine(DB_URL)

    # ── 启动前校验 ──────────────────────────────────────────────────────────
    log.info("0. 校验数据库表结构...")
    if not check_tables(db):
        log.error("\n表结构校验失败，请检查以上报错后重新运行。")
        sys.exit(1)
    log.info("   校验通过\n")

    # ── 数据加载 ────────────────────────────────────────────────────────────
    log.info("1. 读取最新行情（收盘价 + 总股本）...")
    price_map, share_map = load_market_data(db)
    log.info(f"   收盘价 {len(price_map)} 只 / 股本 {len(share_map)} 只")

    log.info("2. 读取股票名称和行业...")
    stock_info = load_stock_info(db)
    log.info(f"   共 {len(stock_info)} 只")

    log.info("3. 读取沪深 300 成分股名单...")
    codes = load_hs300_codes(db)
    log.info(f"   共 {len(codes)} 只\n")

    # ── 批量估值 ────────────────────────────────────────────────────────────
    log.info("4. 批量估值中...\n")
    engine  = UnifiedValuation(DB_URL)
    results = []
    skipped = {"无行情": 0, "估值失败": 0}

    for i, code in enumerate(codes, 1):
        price  = price_map.get(code)
        shares = share_map.get(code)
        if not price or not shares:
            skipped["无行情"] += 1
            log.warning(f"[{i:>3}/{len(codes)}] {code}  缺少行情或股本数据，跳过")
            continue

        si       = stock_info.get(code, {})
        name     = si.get("name", "")
        industry = si.get("industry", "")

        r = engine.calc(code, industry, shares, current_price=price)
        if "error" in r:
            skipped["估值失败"] += 1
            log.warning(f"[{i:>3}/{len(codes)}] {code} {name}  ✗ {r['error']}")
            continue

        fv = r["fair_per_share"]

        # DCF 股权为负：保留进结果，标注原因，空间%置空
        equity_negative = (fv is not None and fv < 0)
        if equity_negative:
            gap   = None   # 无法计算上行空间
            mc_yi = round(price * shares * 1e4 / 1e8, 1)
        else:
            gap   = round((fv / price - 1) * 100, 1) if (fv and price) else None
            mc_yi = round(price * shares * 1e4 / 1e8, 1)

        # 生成风险标注
        fcf_yi = r.get("base_fcf_yi") or 0
        quantifiable_risk, unquantifiable_risk = _build_risk_notes(r, mc_yi, gap, industry)
        if equity_negative:
            quantifiable_risk = "DCF股权为负(债务超经营价值)" + (
                f" | {quantifiable_risk}" if quantifiable_risk else ""
            )

        results.append({
            "ts_code":        code,
            "名称":           name,
            "行业":           industry,
            "估值方法":       r["方法"],
            "当前价":         price,
            "估值":           fv,
            "估值_悲观":      r.get("fair_bear"),
            "估值_中性":      fv,
            "估值_乐观":      r.get("fair_bull"),
            "空间%":          gap,
            "市值亿":         mc_yi,
            "基准FCF/净利亿": r.get("base_fcf_yi"),
            "原始OCF亿":      r.get("ocf_raw_yi"),
            "增长率%":        round(r["growth_rate"] * 100, 1) if r.get("growth_rate") is not None else None,
            "EV亿":           r.get("ev_yi"),
            "有息债务亿":     r.get("debt_yi"),
            "现金及理财亿":   r.get("cash_yi"),
            "净债务亿":       round(
                                  (r.get("debt_yi") or 0) - (r.get("cash_yi") or 0), 1
                              ) if r.get("debt_yi") is not None else None,
            "当前PB":         r.get("cur_pb"),
            "合理PB":         r.get("fair_pb"),
            "ROE%":           r.get("roe_pct"),
            "每股净资产":     r.get("book_per_share"),
            "可识别风险":     quantifiable_risk,
            "不可量化提示":   unquantifiable_risk,
        })

        gap_str  = f"{gap:+.1f}%" if gap is not None else "  N/A"
        note_str = f"  [{quantifiable_risk}]" if quantifiable_risk else ""
        print(
            f"[{i:>3}/{len(codes)}] {code} {name:<6} [{r['方法'][:14]}]"
            f"  现价={price:.2f}  估值={fv:.2f}  空间={gap_str}{note_str}",
            flush=True,
        )

    # ── 空结果保护 ──────────────────────────────────────────────────────────
    if not results:
        log.error("无有效估值结果（可能数据库无数据），退出。")
        sys.exit(1)

    # ── 排序 + 汇总打印 ─────────────────────────────────────────────────────
    results.sort(
        key=lambda x: x["空间%"] if x["空间%"] is not None else -999,
        reverse=True,
    )

    SEP = "=" * 90
    print(f"\n{SEP}")
    print(
        f"  HS300 全行业细分估值汇总（按上行空间排序）"
        f"  有效 {len(results)} 只"
        f"  跳过 {sum(skipped.values())} 只"
        f"（无行情 {skipped['无行情']} / 失败 {skipped['估值失败']}）"
    )
    print(SEP)
    print(f"{'代码':<12}{'名称':<8}{'行业':<8}{'方法':<18}{'当前价':>7}{'估值':>8}{'空间':>8}  备注")
    print("-" * 80)
    for r in results:
        gap_s  = f"{r['空间%']:+.1f}%" if r["空间%"] is not None else "  N/A"
        fv_s   = f"{r['估值']:.2f}"   if r["估值"]  is not None else "  N/A"
        print(
            f"{r['ts_code']:<12}{r['名称']:<8}{r['行业']:<8}"
            f"{r['估值方法'][:16]:<18}{r['当前价']:>6.2f}元"
            f"{fv_s:>8}元  {gap_s:>7}  {r.get('备注','')}"
        )

    # ── 导出 CSV ─────────────────────────────────────────────────────────────
    os.makedirs("data", exist_ok=True)
    base = "data/valuation_hs300_industry"
    canonical = f"{base}.csv"
    if os.path.exists(canonical):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = f"{base}_{ts}.csv"
    else:
        out = canonical
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        _write_legend(f, len(results))
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    log.info(f"已导出: {out}  （{len(results)} 行 × {len(results[0])} 列）")

    # ── 估值方法分布统计 ──────────────────────────────────────────────────────
    method_cnt   = Counter(r["估值方法"].split("(")[0].strip() for r in results)
    flagged_cnt  = sum(1 for r in results if r.get("可识别风险"))
    total        = len(results)
    print("\n估值方法分布：")
    for m, c in method_cnt.most_common():
        bar = "█" * c
        pct = c / total * 100
        print(f"  {m:<24} {c:>3} 只  {pct:5.1f}%  {bar}")
    print(f"\n  含可识别风险标注：{flagged_cnt} 只 / {total} 只")
