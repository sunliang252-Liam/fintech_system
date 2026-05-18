"""
analysis_layer/dcf.py
----------------------
基于 dcf_valuation_v1.py 的逻辑，对接本项目已有的
income_statement / cash_flow_statement / balance_sheet 三张表。

核心逻辑不变：
  - 优先用经营活动现金流，其次 free_cashflow，最后用净利润*0.8 兜底
  - 给定市值 → 二分法反推市场隐含增长率
  - 对比历史营收 CAGR，输出判断
"""

import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text

DB_URL = (
    f"postgresql://{os.getenv('PG_USER','postgres')}:{os.getenv('PG_PASSWORD','')}"
    f"@{os.getenv('PG_HOST','localhost')}:{os.getenv('PG_PORT','5432')}"
    f"/{os.getenv('PG_DB','fintech_db')}"
)


def implied_growth_rate(market_cap_yi, base_fcf, wacc=0.08, terminal_growth=0.02, years=5):
    """给定市值（亿），二分法反推市场隐含年化增长率。"""
    target = market_cap_yi * 1e8

    low, high = -0.5, 1.0
    for _ in range(100):
        mid = (low + high) / 2
        rate = max(mid, -0.99)
        fcfs = [base_fcf * ((1 + rate) ** i) for i in range(1, years + 1)]
        discounted = [f / ((1 + wacc) ** i) for i, f in enumerate(fcfs, 1)]
        tv = (fcfs[-1] * (1 + terminal_growth)) / (wacc - terminal_growth)
        ev = sum(discounted) + tv / ((1 + wacc) ** years)
        if ev < target:
            low = mid
        else:
            high = mid
    return mid


class DCFValuation:
    def __init__(self, ts_code: str):
        self.ts_code = ts_code
        self.engine  = create_engine(DB_URL)

    def fetch_data(self, periods: int = 5):
        """从本项目三张财报表中提取数据。"""
        with self.engine.connect() as conn:
            income_df = pd.read_sql(text("""
                SELECT end_date, revenue, n_income_attr_p
                FROM income_statement
                WHERE ts_code = :code
                ORDER BY end_date DESC LIMIT :p
            """), conn, params={"code": self.ts_code, "p": periods})

            fcf_df = pd.read_sql(text("""
                SELECT end_date, n_cashflow_act, free_cashflow
                FROM cash_flow_statement
                WHERE ts_code = :code
                ORDER BY end_date DESC LIMIT :p
            """), conn, params={"code": self.ts_code, "p": periods})

        return income_df.fillna(0), fcf_df.fillna(0)

    def fetch_market_cap(self):
        """尝试从 stk_daily_basic 取最新总市值（万元→亿元），不存在则返回 None。"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT total_mv FROM stk_daily_basic
                    WHERE ts_code = :code ORDER BY trade_date DESC LIMIT 1
                """), {"code": self.ts_code}).fetchone()
            return result[0] / 10000 if result else None
        except Exception:
            return None

    def run_valuation(self, wacc=0.09, terminal_growth=0.02, manual_market_cap_yi=None):
        """运行估值推演，输出报告。"""
        income_df, fcf_df = self.fetch_data()
        mc_yi = manual_market_cap_yi if manual_market_cap_yi else self.fetch_market_cap()

        if income_df.empty:
            print(f"[{self.ts_code}] 缺失必要利润数据")
            return

        # 优先经营现金流 → free_cashflow → 净利润*0.8
        base_fcf, fcf_source = 0, ""
        if not fcf_df.empty:
            v = fcf_df.iloc[0].get("n_cashflow_act", 0)
            if v and v > 0:
                base_fcf, fcf_source = v, "经营活动现金流 (n_cashflow_act)"
            else:
                v2 = fcf_df.iloc[0].get("free_cashflow", 0)
                if v2 and v2 > 0:
                    base_fcf, fcf_source = v2, "自由现金流 (free_cashflow)"

        if base_fcf <= 0:
            base_fcf   = income_df.iloc[0]["n_income_attr_p"] * 0.8
            fcf_source = "归母净利润 × 0.8（替代方案）"
            print("警告：现金流数据缺失或为负，使用净利润替代，结果仅供参考")

        print(f"\n--- 估值推演报告: {self.ts_code} ---")
        print(f"基准 FCF 来源: {fcf_source}")
        print(f"基准 FCF 数值: {base_fcf/1e8:.2f} 亿")

        if mc_yi:
            imp_g = implied_growth_rate(mc_yi, base_fcf, wacc, terminal_growth)
            print(f"当前市值: {mc_yi:.2f} 亿")
            print(f"市场隐含年化增长率 (g): {imp_g:.2%}")
            print("-" * 35)

            if len(income_df) >= 2:
                revs = income_df["revenue"].values[::-1]
                hist_cagr = (revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1
                print(f"历史营收 CAGR（参考）: {hist_cagr:.2%}")
                delta = abs(imp_g - hist_cagr)
                if imp_g < 0:
                    label = "[市场预期极悲观]"
                elif delta < 0.05:
                    label = "[预期合理]"
                else:
                    label = "[预期较高]"
                print(f"判断: {label}")
        else:
            print("当前市值数据缺失，请通过 manual_market_cap_yi 传入（单位：亿）")
        print("-" * 35)

    def calc_fair_value(self, total_shares_wan: float,
                        growth_rate: float = None,
                        wacc: float = 0.09,
                        terminal_growth: float = 0.02,
                        years: int = 5) -> dict:
        """
        正向 DCF 估值，返回每股内在价值。

        total_shares_wan : 总股本（万股）
        growth_rate      : 预测增长率；None 则用历史营收 CAGR（保守取值）
        """
        income_df, fcf_df = self.fetch_data()
        if income_df.empty:
            return {"error": "缺少利润数据"}

        # 取 base_fcf（同 run_valuation 逻辑）
        base_fcf = 0
        if not fcf_df.empty:
            v = fcf_df.iloc[0].get("n_cashflow_act", 0)
            if v and v > 0:
                base_fcf = v
            else:
                v2 = fcf_df.iloc[0].get("free_cashflow", 0)
                if v2 and v2 > 0:
                    base_fcf = v2
        if base_fcf <= 0:
            base_fcf = income_df.iloc[0]["n_income_attr_p"] * 0.8

        # 历史营收 CAGR 作为增长率参考
        if growth_rate is None and len(income_df) >= 2:
            revs = income_df["revenue"].values[::-1]
            hist_cagr = (revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1
            growth_rate = max(min(hist_cagr, 0.25), -0.10)  # 限幅 -10%~25%

        growth_rate = growth_rate or 0.05

        # 取资产负债表净债务（最新年）
        with self.engine.connect() as conn:
            bs = pd.read_sql(text("""
                SELECT money_cap, st_borr, lt_borr
                FROM balance_sheet WHERE ts_code=:c ORDER BY end_date DESC LIMIT 1
            """), conn, params={"c": self.ts_code})
        if not bs.empty:
            cash = pd.to_numeric(bs["money_cap"].iloc[0], errors="coerce") or 0
            st   = pd.to_numeric(bs["st_borr"].iloc[0],   errors="coerce") or 0
            lt   = pd.to_numeric(bs["lt_borr"].iloc[0],   errors="coerce") or 0
            debt = st + lt
        else:
            cash, debt = 0, 0

        # 预测期折现
        pv_sum = sum(
            base_fcf * (1 + growth_rate) ** t / (1 + wacc) ** t
            for t in range(1, years + 1)
        )
        # 终值
        terminal_fcf = base_fcf * (1 + growth_rate) ** years * (1 + terminal_growth)
        terminal_pv  = (terminal_fcf / (wacc - terminal_growth)) / (1 + wacc) ** years
        ev           = pv_sum + terminal_pv
        equity_val   = ev + cash - debt
        total_shares = total_shares_wan * 1e4
        fair_per_share = equity_val / total_shares if total_shares > 0 else None

        return {
            "ts_code":         self.ts_code,
            "base_fcf_yi":     round(base_fcf / 1e8, 2),
            "growth_rate":     round(growth_rate, 4),
            "wacc":            wacc,
            "terminal_growth": terminal_growth,
            "ev_yi":           round(ev / 1e8, 1),
            "cash_yi":         round(cash / 1e8, 1),
            "debt_yi":         round(debt / 1e8, 1),
            "equity_val_yi":   round(equity_val / 1e8, 1),
            "total_shares_wan":total_shares_wan,
            "fair_per_share":  round(fair_per_share, 2) if fair_per_share else None,
        }


if __name__ == "__main__":
    for code, mc in [("600893.SH", None), ("002572.SZ", None)]:
        model = DCFValuation(code)
        model.run_valuation(manual_market_cap_yi=mc)
