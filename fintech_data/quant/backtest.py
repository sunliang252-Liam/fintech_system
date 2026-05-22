"""
fintech_data/quant/backtest.py
用 vectorbt 对单股或股票组合做回测，数据直接从 PostgreSQL 读取。

用法示例：
    from fintech_data.quant.backtest import run_ma_cross, run_portfolio

    # 单股均线策略
    stats = run_ma_cross("600519.SH", fast=10, slow=30, start="2020-01-01")
    print(stats)

    # 多股组合回测
    pf = run_portfolio(["600519.SH", "000858.SZ"], start="2022-01-01")
    pf.stats()
"""
from __future__ import annotations

from typing import Sequence

import pandas as pd
import numpy as np
import vectorbt as vbt

from fintech_data import db
from fintech_data.logger import get

log = get("backtest")


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def load_price(
    symbols: str | Sequence[str],
    start: str = "2015-01-01",
    end: str | None = None,
    price_col: str = "close",
) -> pd.DataFrame:
    """
    从 stock_daily_hist 加载价格，返回 date × symbol 的 DataFrame。
    stock_daily_hist 存储未复权价格（tushare 不含 adj_factor）。
    """
    if isinstance(symbols, str):
        symbols = [symbols]

    conn = db.get_conn()
    try:
        sym_list = ", ".join(f"'{s}'" for s in symbols)
        where = f"ts_code IN ({sym_list}) AND trade_date >= '{start}'"
        if end:
            where += f" AND trade_date <= '{end}'"
        sql = f"""
            SELECT ts_code, trade_date, open, high, low, close, vol AS volume
            FROM stock_daily_hist
            WHERE {where}
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
    for col in ["open", "high", "low", "close", "volume"]:
        if col in raw.columns:
            raw[col] = raw[col].astype(float)
    prices = raw.pivot(index="trade_date", columns="ts_code", values=price_col)
    prices.index.name = "date"
    prices.columns.name = None

    if len(symbols) == 1:
        return prices[symbols[0]].rename(symbols[0])
    return prices[list(symbols)]


def load_ohlcv(symbol: str, start: str = "2015-01-01", end: str | None = None) -> pd.DataFrame:
    """返回单股 OHLCV DataFrame，index 为 date。"""
    conn = db.get_conn()
    try:
        where = f"ts_code = '{symbol}' AND trade_date >= '{start}'"
        if end:
            where += f" AND trade_date <= '{end}'"
        sql = f"""
            SELECT trade_date, open, high, low, close, vol AS volume
            FROM stock_daily_hist WHERE {where} ORDER BY trade_date
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        df = pd.DataFrame(rows, columns=cols)
    finally:
        db.put_conn(conn)

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df.set_index("trade_date")


# ── 策略模板 ──────────────────────────────────────────────────────────────────

def run_ma_cross(
    symbol: str,
    fast: int = 10,
    slow: int = 30,
    start: str = "2015-01-01",
    end: str | None = None,
    init_cash: float = 100_000,
    fees: float = 0.0003,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """
    双均线金叉/死叉策略。返回 vectorbt Portfolio 对象，可调用 .stats() / .plot()。
    """
    price = load_price(symbol, start=start, end=end)
    fast_ma = vbt.MA.run(price, fast, short_name="fast")
    slow_ma = vbt.MA.run(price, slow, short_name="slow")

    entries  = fast_ma.ma_crossed_above(slow_ma)
    exits    = fast_ma.ma_crossed_below(slow_ma)

    pf = vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        init_cash=init_cash,
        fees=fees,
        slippage=slippage,
        freq="D",
    )
    log.info(f"[{symbol}] MA({fast}/{slow}) 回测完成: 总收益率={pf.total_return():.2%}")
    return pf


def run_rsi_strategy(
    symbol: str,
    rsi_period: int = 14,
    rsi_buy: float = 30,
    rsi_sell: float = 70,
    start: str = "2015-01-01",
    end: str | None = None,
    init_cash: float = 100_000,
    fees: float = 0.0003,
) -> vbt.Portfolio:
    """RSI 超买超卖策略。"""
    price = load_price(symbol, start=start, end=end)
    rsi = vbt.RSI.run(price, rsi_period)

    entries = rsi.rsi_below(rsi_buy)
    exits   = rsi.rsi_above(rsi_sell)

    pf = vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        init_cash=init_cash,
        fees=fees,
        freq="D",
    )
    log.info(f"[{symbol}] RSI({rsi_period}) 回测完成: 总收益率={pf.total_return():.2%}")
    return pf


def run_portfolio(
    symbols: Sequence[str],
    start: str = "2020-01-01",
    end: str | None = None,
    fast: int = 10,
    slow: int = 30,
    init_cash: float = 1_000_000,
    fees: float = 0.0003,
) -> vbt.Portfolio:
    """
    多股组合：每只股票独立运行均线策略，等权分配资金。
    """
    prices = load_price(list(symbols), start=start, end=end)

    fast_ma = vbt.MA.run(prices, fast)
    slow_ma = vbt.MA.run(prices, slow)

    entries = fast_ma.ma_crossed_above(slow_ma)
    exits   = fast_ma.ma_crossed_below(slow_ma)

    pf = vbt.Portfolio.from_signals(
        prices,
        entries=entries,
        exits=exits,
        init_cash=init_cash / len(symbols),
        fees=fees,
        freq="D",
        group_by=False,
    )
    log.info(f"组合回测完成，共 {len(symbols)} 只股票")
    return pf


def grid_search_ma(
    symbol: str,
    fast_range: range = range(5, 25, 5),
    slow_range: range = range(20, 60, 10),
    start: str = "2018-01-01",
) -> pd.DataFrame:
    """
    对均线参数做网格搜索，返回每组参数的统计汇总 DataFrame。
    """
    price = load_price(symbol, start=start)

    fast_ma = vbt.MA.run(price, list(fast_range), short_name="fast", param_product=True)
    slow_ma = vbt.MA.run(price, list(slow_range), short_name="slow", param_product=True)

    entries = fast_ma.ma_crossed_above(slow_ma)
    exits   = fast_ma.ma_crossed_below(slow_ma)

    pf = vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        fees=0.0003,
        freq="D",
    )
    stats = pf.stats(agg_func=None)
    log.info(f"网格搜索完成: {len(stats)} 组参数")
    return stats
