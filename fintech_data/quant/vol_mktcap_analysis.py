"""
fintech_data/quant/vol_mktcap_analysis.py
分析成交量变化与市值（股价）变化的关系，并做量化回测。

指标定义：
  - 量比 (vol_ratio): 今日成交量 / 20日均量
  - 额比 (amt_ratio): 今日成交额 / 20日均额（更准确的资金流入代理）
  - 市值变化: 用 pct_chg 代理（市值 ≈ 价格 × 总股本，日内总股本不变）
  - 前向收益: 未来 1/5/20 日收益率

用法：
    conda run -n fintech python -m fintech_data.quant.vol_mktcap_analysis
"""
from __future__ import annotations
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import vectorbt as vbt

from fintech_data import db
from fintech_data.logger import get

log = get("vol_mktcap")


# ── 1. 数据加载 ───────────────────────────────────────────────────────────────

def load_hs300_universe(latest_date: str = "20260430") -> list[str]:
    """取沪深300最新成分股列表。"""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ts_code FROM index_components
                WHERE index_code='000300.SH' AND trade_date=(
                    SELECT MAX(trade_date) FROM index_components WHERE index_code='000300.SH'
                )
                ORDER BY weight DESC
            """)
            return [r[0] for r in cur.fetchall()]
    finally:
        db.put_conn(conn)


def load_daily_data(symbols: list[str], start: str = "2020-01-01") -> pd.DataFrame:
    """
    加载 OHLCV + pct_chg，返回 MultiIndex (ts_code, trade_date) DataFrame。
    """
    conn = db.get_conn()
    try:
        sym_list = ", ".join(f"'{s}'" for s in symbols)
        sql = f"""
            SELECT ts_code, trade_date, close, vol, amount, pct_chg
            FROM stock_daily_hist
            WHERE ts_code IN ({sym_list}) AND trade_date >= '{start}'
            ORDER BY ts_code, trade_date
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        df = pd.DataFrame(rows, columns=cols)
    finally:
        db.put_conn(conn)

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for col in ["close", "vol", "amount", "pct_chg"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.set_index(["ts_code", "trade_date"]).sort_index()
    return df


# ── 2. 因子计算 ───────────────────────────────────────────────────────────────

def compute_factors(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    对 MultiIndex DataFrame 计算：
      vol_ratio  : 量比
      amt_ratio  : 额比（成交额比）
      ret_fwd_1  : 未来1日收益
      ret_fwd_5  : 未来5日收益
      ret_fwd_20 : 未来20日收益
    """
    results = []
    for sym, grp in df.groupby(level="ts_code"):
        g = grp.droplevel("ts_code").copy()

        # 量比 / 额比
        g["vol_ratio"] = g["vol"] / g["vol"].rolling(window).mean()
        g["amt_ratio"] = g["amount"] / g["amount"].rolling(window).mean()

        # 当日收益（来自 pct_chg 字段，tushare 单位 %）
        g["ret_0"] = g["pct_chg"] / 100

        # 前向收益：今日收盘持仓 N 日后的累计收益
        g["ret_fwd_1"]  = g["close"].shift(-1)  / g["close"] - 1
        g["ret_fwd_5"]  = g["close"].shift(-5)  / g["close"] - 1
        g["ret_fwd_20"] = g["close"].shift(-20) / g["close"] - 1

        g.index = pd.MultiIndex.from_arrays([[sym] * len(g), g.index], names=["ts_code", "trade_date"])
        results.append(g)

    return pd.concat(results)


# ── 3. 统计分析 ───────────────────────────────────────────────────────────────

def bucket_analysis(factors: pd.DataFrame, factor_col: str = "vol_ratio") -> pd.DataFrame:
    """
    将量比/额比分成 5 个等级，统计每档的前向收益均值和胜率。
    """
    df = factors[[factor_col, "ret_fwd_1", "ret_fwd_5", "ret_fwd_20"]].dropna()

    # 按分位数分档（忽略极值，截尾到 0.5%~99.5%）
    lo, hi = df[factor_col].quantile(0.005), df[factor_col].quantile(0.995)
    df = df[(df[factor_col] >= lo) & (df[factor_col] <= hi)]
    df["bucket"] = pd.qcut(df[factor_col], q=5, labels=["极低", "低", "中", "高", "极高"])

    result = df.groupby("bucket", observed=True).agg(
        count=(factor_col, "count"),
        vol_ratio_mean=(factor_col, "mean"),
        ret1d_mean=("ret_fwd_1", "mean"),
        ret5d_mean=("ret_fwd_5", "mean"),
        ret20d_mean=("ret_fwd_20", "mean"),
        ret1d_win_rate=("ret_fwd_1", lambda x: (x > 0).mean()),
        ret5d_win_rate=("ret_fwd_5", lambda x: (x > 0).mean()),
    )
    result["ret1d_mean"]    = result["ret1d_mean"].map("{:.3%}".format)
    result["ret5d_mean"]    = result["ret5d_mean"].map("{:.3%}".format)
    result["ret20d_mean"]   = result["ret20d_mean"].map("{:.3%}".format)
    result["ret1d_win_rate"] = result["ret1d_win_rate"].map("{:.1%}".format)
    result["ret5d_win_rate"] = result["ret5d_win_rate"].map("{:.1%}".format)
    result["vol_ratio_mean"] = result["vol_ratio_mean"].map("{:.2f}".format)
    return result


def correlation_analysis(factors: pd.DataFrame) -> pd.DataFrame:
    """量比/额比与前向收益的皮尔逊相关系数及 p-value。"""
    from scipy import stats

    rows = []
    for x_col in ["vol_ratio", "amt_ratio"]:
        for y_col in ["ret_fwd_1", "ret_fwd_5", "ret_fwd_20"]:
            sub = factors[[x_col, y_col]].dropna()
            r, p = stats.pearsonr(sub[x_col], sub[y_col])
            rows.append({
                "factor": x_col,
                "forward_return": y_col,
                "pearson_r": round(r, 4),
                "p_value": round(p, 6),
                "significant": "✓" if p < 0.05 else "✗",
            })
    return pd.DataFrame(rows)


def lagged_correlation(factors: pd.DataFrame, sym: str = "600519.SH", max_lag: int = 20) -> pd.DataFrame:
    """单股：vol_ratio 滞后 N 日 与当日收益的相关系数，分析领先/滞后关系。"""
    g = factors.loc[sym] if sym in factors.index.get_level_values("ts_code") else None
    if g is None:
        return pd.DataFrame()
    rows = []
    for lag in range(-5, max_lag + 1):
        r = g["vol_ratio"].shift(lag).corr(g["ret_0"])
        rows.append({"lag": lag, "corr": round(r, 4),
                     "direction": "vol领先ret" if lag > 0 else ("同步" if lag == 0 else "ret领先vol")})
    return pd.DataFrame(rows)


# ── 4. vectorbt 量比策略回测 ─────────────────────────────────────────────────

def run_vol_surge_strategy(
    symbols: list[str],
    start: str = "2020-01-01",
    vol_thresh: float = 2.0,   # 量比超过此值触发买入
    exit_days: int = 5,        # 持有N天后离场
    init_cash: float = 100_000,
    fees: float = 0.0003,
) -> vbt.Portfolio:
    """
    量比放量策略：
      - 入场：vol_ratio > vol_thresh 且当日涨幅 > 0（量价齐升）
      - 出场：持有 exit_days 天后固定退出
    """
    from fintech_data.quant.backtest import load_price

    prices = load_price(symbols, start=start)
    if isinstance(prices, pd.Series):
        prices = prices.to_frame()

    # 计算量比
    conn = db.get_conn()
    try:
        sym_list = ", ".join(f"'{s}'" for s in symbols)
        sql = f"""
            SELECT ts_code, trade_date, vol, pct_chg
            FROM stock_daily_hist
            WHERE ts_code IN ({sym_list}) AND trade_date >= '{start}'
            ORDER BY trade_date, ts_code
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        raw = pd.DataFrame(rows, columns=cols)
    finally:
        db.put_conn(conn)

    raw["trade_date"] = pd.to_datetime(raw["trade_date"])
    raw["vol"]      = raw["vol"].astype(float)
    raw["pct_chg"]  = raw["pct_chg"].astype(float)

    vol_pivot = raw.pivot(index="trade_date", columns="ts_code", values="vol")
    chg_pivot = raw.pivot(index="trade_date", columns="ts_code", values="pct_chg")
    vol_pivot.columns.name = None
    chg_pivot.columns.name = None

    vol_ratio = vol_pivot / vol_pivot.rolling(20).mean()

    # 入场信号：量比 > 阈值 且 今日上涨
    entries = (vol_ratio > vol_thresh) & (chg_pivot > 0)
    # 出场：N日后固定离场（用 exit_after_n_days）
    exits = entries.shift(exit_days).fillna(False)

    # 对齐 prices 列
    common_cols = [c for c in prices.columns if c in entries.columns]
    prices   = prices[common_cols]
    entries  = entries.reindex(prices.index, fill_value=False)[common_cols]
    exits    = exits.reindex(prices.index, fill_value=False)[common_cols]

    pf = vbt.Portfolio.from_signals(
        prices,
        entries=entries,
        exits=exits,
        init_cash=init_cash,
        fees=fees,
        freq="D",
        group_by=False,
    )
    return pf


# ── 5. 主流程 ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("成交量变化 vs 市值变化 量化分析")
    print("=" * 70)

    # ── 取沪深300成分股 ──────────────────────────────────────────────────────
    print("\n[1/5] 加载沪深300成分股 …")
    symbols = load_hs300_universe()
    print(f"  成分股数量: {len(symbols)}")

    # ── 加载行情 ─────────────────────────────────────────────────────────────
    print("\n[2/5] 加载日线数据（2021至今）…")
    raw = load_daily_data(symbols, start="2021-01-01")
    n_stocks = raw.index.get_level_values("ts_code").nunique()
    n_rows   = len(raw)
    print(f"  {n_stocks} 只股票，共 {n_rows:,} 行")

    # ── 计算因子 ─────────────────────────────────────────────────────────────
    print("\n[3/5] 计算量比、额比、前向收益 …")
    factors = compute_factors(raw)
    print(f"  因子计算完成，有效行数: {factors[['vol_ratio','ret_fwd_1']].dropna().shape[0]:,}")

    # ── 分档统计 ─────────────────────────────────────────────────────────────
    print("\n[4/5] 量比分档收益统计")
    print("-" * 70)
    vol_buckets = bucket_analysis(factors, "vol_ratio")
    print(vol_buckets.to_string())

    print("\n  额比（成交额）分档收益统计")
    print("-" * 70)
    amt_buckets = bucket_analysis(factors, "amt_ratio")
    print(amt_buckets.to_string())

    # ── 相关系数 ─────────────────────────────────────────────────────────────
    print("\n  量比/额比 与前向收益 相关系数（全市场）")
    print("-" * 70)
    corr = correlation_analysis(factors)
    print(corr.to_string(index=False))

    # ── 单股滞后相关（茅台） ────────────────────────────────────────────────
    print("\n  茅台(600519.SH) 量比滞后相关分析（lag=0 同步，lag>0 量比领先）")
    print("-" * 40)
    lag_corr = lagged_correlation(factors, "600519.SH", max_lag=10)
    if not lag_corr.empty:
        print(lag_corr[lag_corr["lag"].between(-3, 10)].to_string(index=False))

    # ── 量比放量策略回测 ─────────────────────────────────────────────────────
    print("\n[5/5] 量比放量策略回测（沪深300前50只，2021至今）")
    print("-" * 70)
    top50 = symbols[:50]
    pf = run_vol_surge_strategy(top50, start="2021-01-01", vol_thresh=2.0, exit_days=5)

    # 汇总所有股票的组合表现
    total_ret    = pf.total_return().mean()
    max_dd       = pf.max_drawdown().mean()
    sharpe       = pf.sharpe_ratio().mean()
    n_trades     = pf.trades.count().sum()

    print(f"  策略：量比 > 2.0 且当日上涨，持有5天")
    print(f"  标的：沪深300前50只（等权）")
    print(f"  平均总收益率:  {total_ret:.2%}")
    print(f"  平均最大回撤:  {max_dd:.2%}")
    print(f"  平均夏普比率:  {sharpe:.2f}")
    print(f"  总交易次数:    {int(n_trades)}")

    # 对比基准：各股票简单买入持有
    from fintech_data.quant.backtest import load_price
    prices_bh = load_price(top50, start="2021-01-01")
    if isinstance(prices_bh, pd.Series):
        prices_bh = prices_bh.to_frame()
    bh_rets = (prices_bh.iloc[-1] / prices_bh.iloc[0] - 1).mean()
    print(f"  买入持有基准:  {bh_rets:.2%}  (各股平均，全期)")
    print(f"  超额收益:      {total_ret - bh_rets:+.2%}")

    print("\n完成。")
    return factors, pf


if __name__ == "__main__":
    main()
