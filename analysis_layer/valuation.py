"""
analysis_layer/valuation.py
-----------------------------
多方法估值引擎：根据行业自动选择最合适的估值公式。

方法分类：
  pb_roe      — 银行/保险/证券/地产：P/B + ROE 戈登增长模型
  dcf_capex   — 重资产行业：FCF = 经营现金流 − 资本开支
  dcf_cycle   — 强周期行业：FCF = 近3年(OCF−capex)均值
  dcf_std     — 稳定现金流：FCF = 经营现金流（保守兜底）
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = (
    f"postgresql://{os.getenv('PG_USER','postgres')}:{os.getenv('PG_PASSWORD','')}"
    f"@{os.getenv('PG_HOST','localhost')}:{os.getenv('PG_PORT','5432')}"
    f"/{os.getenv('PG_DB','fintech_db')}"
)

# ── 行业 → 估值方法映射 ────────────────────────────────────────────────────
INDUSTRY_METHOD: dict[str, str] = {
    # P/B + ROE（金融、地产及高杠杆/重资产且现金流不稳行业）
    "银行":     "pb_roe",
    "保险":     "pb_roe",
    "证券":     "pb_roe",
    "多元金融": "pb_roe",
    "全国地产": "pb_roe",
    "区域地产": "pb_roe",
    "园区开发": "pb_roe",
    "建筑工程": "pb_roe",   # 建筑业垫资多、周转慢，DCF易失真
    "路桥":     "pb_roe",

    # DCF 扣 capex（重资产，经营现金流含大量资本消耗）
    "半导体":   "dcf_capex",
    "元器件":   "dcf_capex",
    "电气设备": "dcf_capex",
    "新型电力": "dcf_capex",
    "火力发电": "dcf_capex",
    "水力发电": "dcf_capex",
    "航空":     "dcf_capex",
    "空运":     "dcf_capex",
    "通信设备": "dcf_capex",
    "运输设备": "dcf_capex",
    "铁路":     "dcf_capex",
    "机场":     "dcf_capex",
    "港口":     "dcf_capex",
    "供气供热": "dcf_capex",

    # 穿越周期 DCF（强周期，用近3年均值FCF代替单年）
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

    # 其余行业默认标准 DCF（dcf_std）
}

WACC            = 0.09
TERMINAL_GROWTH = 0.02
YEARS           = 5


def _engine():
    return create_engine(DB_URL)


# ── 共用数据拉取 ──────────────────────────────────────────────────────────

def _fetch_income(conn, ts_code: str, n: int = 5) -> pd.DataFrame:
    return pd.read_sql(text("""
        SELECT report_year, revenue, net_profit_parent
        FROM income_statement
        WHERE ts_code = :c ORDER BY report_year DESC LIMIT :n
    """), conn, params={"c": ts_code, "n": n}).fillna(0)


def _fetch_cashflow(conn, ts_code: str, n: int = 5) -> pd.DataFrame:
    return pd.read_sql(text("""
        SELECT report_year, operating_cashflow, capex
        FROM cash_flow_statement
        WHERE ts_code = :c ORDER BY report_year DESC LIMIT :n
    """), conn, params={"c": ts_code, "n": n}).fillna(0)


def _fetch_balance(conn, ts_code: str) -> pd.Series:
    df = pd.read_sql(text("""
        SELECT cash, short_term_debt, long_term_debt,
               equity_parent, total_equity
        FROM balance_sheet
        WHERE ts_code = :c ORDER BY report_year DESC LIMIT 1
    """), conn, params={"c": ts_code})
    return df.iloc[0] if not df.empty else pd.Series(dtype=float)


def _revenue_cagr(income_df: pd.DataFrame) -> float:
    if len(income_df) < 2:
        return 0.05
    revs = income_df["revenue"].values[::-1]
    if revs[0] <= 0:
        return 0.05
    cagr = (revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1
    return float(max(min(cagr, 0.25), -0.10))


def _dcf_ev(base_fcf: float, g: float,
            wacc: float = WACC,
            tg: float = TERMINAL_GROWTH,
            years: int = YEARS) -> float:
    pv = sum(base_fcf * (1 + g) ** t / (1 + wacc) ** t for t in range(1, years + 1))
    tv_fcf = base_fcf * (1 + g) ** years * (1 + tg)
    tv_pv  = (tv_fcf / (wacc - tg)) / (1 + wacc) ** years
    return pv + tv_pv


# ── 估值方法 ──────────────────────────────────────────────────────────────

def _pb_roe(conn, ts_code: str, total_shares_wan: float,
            current_price: float = None) -> dict:
    """P/B + ROE 戈登增长（适用于银行/保险/证券/地产）。"""
    income_df = _fetch_income(conn, ts_code, 3)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty or bs.empty:
        return {"error": "缺少净资产或利润数据"}

    equity = float(bs.get("equity_parent") or bs.get("total_equity") or 0)
    if equity <= 0:
        return {"error": "净资产为零或负"}

    net_profit = float(income_df.iloc[0]["net_profit_parent"])
    roe        = net_profit / equity                    # 当年ROE

    # 戈登增长：合理P/B = (ROE - g) / (WACC - g)
    g       = TERMINAL_GROWTH
    fair_pb = (roe - g) / (WACC - g) if (WACC > g and roe > g) else 1.0
    fair_pb = max(0.3, min(fair_pb, 6.0))               # 限幅 0.3~6x

    total_shares    = total_shares_wan * 1e4
    book_per_share  = equity / total_shares
    fair_per_share  = fair_pb * book_per_share
    cur_pb          = (current_price / book_per_share) if (current_price and book_per_share > 0) else None

    return {
        "方法":          "P/B+ROE",
        "公式":          "合理P/B = (ROE - g) / (WACC - g); 价值 = P/B * 每股净资产",
        "fair_per_share": round(fair_per_share, 2),
        "fair_pb":        round(fair_pb, 2),
        "cur_pb":         round(cur_pb, 2) if cur_pb else None,
        "roe_pct":        round(roe * 100, 1),
        "book_per_share": round(book_per_share, 2),
        "base_fcf_yi":    round(net_profit / 1e8, 2),
        "growth_rate":    g,
        "ev_yi":          None,
        "cash_yi":        None,
        "debt_yi":        None,
    }


def _dcf_capex(conn, ts_code: str, total_shares_wan: float) -> dict:
    """DCF 扣减资本开支（适用于重资产行业）。"""
    income_df = _fetch_income(conn, ts_code)
    cf_df     = _fetch_cashflow(conn, ts_code)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    # FCF = OCF − capex，capex 取正值（数据库中可能已是负数）
    fcf = 0.0
    if not cf_df.empty:
        ocf   = float(cf_df.iloc[0]["operating_cashflow"] or 0)
        capex = abs(float(cf_df.iloc[0]["capex"] or 0))
        fcf   = ocf - capex

    if fcf <= 0:
        # 兜底：净利润 × 0.6（重资产行业再打折）
        fcf = float(income_df.iloc[0]["net_profit_parent"]) * 0.6

    g     = _revenue_cagr(income_df)
    ev    = _dcf_ev(fcf, g)
    cash  = float(bs.get("cash") or 0) if not bs.empty else 0
    debt  = float((bs.get("short_term_debt") or 0) +
                  (bs.get("long_term_debt")  or 0)) if not bs.empty else 0

    equity_val    = ev + cash - debt
    total_shares  = total_shares_wan * 1e4
    fair_per_share = equity_val / total_shares if total_shares > 0 else None

    return {
        "方法":          "DCF(OCF−capex)",
        "公式":          "FCF = 经营现金流 - 资本支出; 价值 = 预测折现FCF + 净现金",
        "fair_per_share": round(fair_per_share, 2) if fair_per_share else None,
        "base_fcf_yi":    round(fcf / 1e8, 2),
        "growth_rate":    round(g, 4),
        "ev_yi":          round(ev / 1e8, 1),
        "cash_yi":        round(cash / 1e8, 1),
        "debt_yi":        round(debt / 1e8, 1),
    }


def _dcf_cycle(conn, ts_code: str, total_shares_wan: float) -> dict:
    """穿越周期 DCF（适用于强周期行业，取近3年FCF均值）。"""
    income_df = _fetch_income(conn, ts_code, 5)
    cf_df     = _fetch_cashflow(conn, ts_code, 5)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    # 近3年 FCF = OCF − capex，只取正值参与均值
    fcf_list = []
    for _, row in cf_df.head(3).iterrows():
        ocf   = float(row["operating_cashflow"] or 0)
        capex = abs(float(row["capex"] or 0))
        f     = ocf - capex
        if f > 0:
            fcf_list.append(f)

    if fcf_list:
        fcf = sum(fcf_list) / len(fcf_list)
    else:
        # 周期股亏损时，保守取净利润的 0.4 或 0 
        net_profit = float(income_df.iloc[0]["net_profit_parent"])
        fcf = max(net_profit * 0.4, 0.0)

    # 周期股保守处理：增长率限幅更严 −5%~15%
    g = _revenue_cagr(income_df)
    g = max(min(g, 0.12), -0.05)

    ev   = _dcf_ev(fcf, g)
    cash = float(bs.get("cash") or 0) if not bs.empty else 0
    debt = float((bs.get("short_term_debt") or 0) +
                 (bs.get("long_term_debt")  or 0)) if not bs.empty else 0

    equity_val     = ev + cash - debt
    total_shares   = total_shares_wan * 1e4
    fair_per_share = equity_val / total_shares if total_shares > 0 else None

    return {
        "方法":          f"穿越周期DCF(n={len(fcf_list)}年均值)",
        "公式":          "FCF = 近3年(OCF - 资本支出)均值; 价值 = 预测折现FCF + 净现金",
        "fair_per_share": round(fair_per_share, 2) if fair_per_share else None,
        "base_fcf_yi":    round(fcf / 1e8, 2),
        "growth_rate":    round(g, 4),
        "ev_yi":          round(ev / 1e8, 1),
        "cash_yi":        round(cash / 1e8, 1),
        "debt_yi":        round(debt / 1e8, 1),
    }


def _dcf_std(conn, ts_code: str, total_shares_wan: float) -> dict:
    """标准 DCF（稳定现金流行业）。"""
    income_df = _fetch_income(conn, ts_code)
    cf_df     = _fetch_cashflow(conn, ts_code)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    fcf = 0.0
    if not cf_df.empty:
        ocf = float(cf_df.iloc[0]["operating_cashflow"] or 0)
        if ocf > 0:
            fcf = ocf
    if fcf <= 0:
        fcf = float(income_df.iloc[0]["net_profit_parent"]) * 0.8

    g  = _revenue_cagr(income_df)
    ev = _dcf_ev(fcf, g)

    cash = float(bs.get("cash") or 0) if not bs.empty else 0
    debt = float((bs.get("short_term_debt") or 0) +
                 (bs.get("long_term_debt")  or 0)) if not bs.empty else 0

    equity_val     = ev + cash - debt
    total_shares   = total_shares_wan * 1e4
    fair_per_share = equity_val / total_shares if total_shares > 0 else None

    return {
        "方法":          "标准DCF",
        "公式":          "FCF = 经营现金流; 价值 = 预测折现FCF + 净现金",
        "fair_per_share": round(fair_per_share, 2) if fair_per_share else None,
        "base_fcf_yi":    round(fcf / 1e8, 2),
        "growth_rate":    round(g, 4),
        "ev_yi":          round(ev / 1e8, 1),
        "cash_yi":        round(cash / 1e8, 1),
        "debt_yi":        round(debt / 1e8, 1),
    }


# ── 统一入口 ──────────────────────────────────────────────────────────────

class UnifiedValuation:
    def __init__(self):
        self.engine = _engine()

    def calc(self, ts_code: str, industry: str,
             total_shares_wan: float, current_price: float = None) -> dict:
        """
        根据行业自动选择估值方法，返回统一格式的结果字典。
        result 必含：方法, fair_per_share（可能为 None）, base_fcf_yi, growth_rate
        """
        method = INDUSTRY_METHOD.get(industry, "dcf_std")
        with self.engine.connect() as conn:
            try:
                if method == "pb_roe":
                    r = _pb_roe(conn, ts_code, total_shares_wan, current_price)
                elif method == "dcf_capex":
                    r = _dcf_capex(conn, ts_code, total_shares_wan)
                elif method == "dcf_cycle":
                    r = _dcf_cycle(conn, ts_code, total_shares_wan)
                else:
                    r = _dcf_std(conn, ts_code, total_shares_wan)
            except Exception as e:
                r = {"error": str(e)}

        r["ts_code"]  = ts_code
        r["industry"] = industry
        r.setdefault("方法", method)
        return r
