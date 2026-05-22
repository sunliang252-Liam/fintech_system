"""
fintech_data/quant/bt_feed.py
将 PostgreSQL stock_daily_hist 接入 backtrader，开箱即用。

用法：
    from fintech_data.quant.bt_feed import PGFeed, run_strategy
    from fintech_data.quant.bt_feed import MACrossStrategy  # 内置示例策略

    # 最简用法
    result = run_strategy(MACrossStrategy, "600519.SH", start="2020-01-01")

    # 自定义策略
    class MyStrategy(bt.Strategy):
        def next(self):
            if not self.position and self.data.close[0] > self.data.close[-1]:
                self.buy()

    run_strategy(MyStrategy, "600519.SH", start="2022-01-01")
"""
from __future__ import annotations

import datetime
from typing import Type

import backtrader as bt
import pandas as pd

from fintech_data import db


# ── 1. 数据适配器：PostgreSQL → backtrader Feed ───────────────────────────────

class PGFeed(bt.feeds.PandasData):
    """
    从 PostgreSQL stock_daily_hist 加载单只股票数据。
    继承 PandasData，字段映射到 backtrader 标准 OHLCV。
    """
    params = (
        ("datetime", None),   # index
        ("open",    "open"),
        ("high",    "high"),
        ("low",     "low"),
        ("close",   "close"),
        ("volume",  "vol"),
        ("openinterest", -1),
    )

    @classmethod
    def from_pg(
        cls,
        symbol: str,
        start: str = "2015-01-01",
        end: str | None = None,
    ) -> "PGFeed":
        """
        拉取数据并返回 PGFeed 实例，直接加入 Cerebro。

        示例：
            cerebro.adddata(PGFeed.from_pg("600519.SH", start="2020-01-01"))
        """
        conn = db.get_conn()
        try:
            where = f"ts_code = '{symbol}' AND trade_date >= '{start}'"
            if end:
                where += f" AND trade_date <= '{end}'"
            sql = f"""
                SELECT trade_date, open, high, low, close, vol
                FROM stock_daily_hist
                WHERE {where}
                ORDER BY trade_date
            """
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            df = pd.DataFrame(rows, columns=cols)
        finally:
            db.put_conn(conn)

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        for col in ["open", "high", "low", "close", "vol"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna()

        feed = cls(dataname=df)
        feed._name = symbol
        return feed


# ── 2. 内置示例策略 ───────────────────────────────────────────────────────────

class MACrossStrategy(bt.Strategy):
    """
    双均线金叉/死叉策略（示例）。
    params: fast(10), slow(30)
    """
    params = (("fast", 10), ("slow", 30), ("printlog", False))

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.crossup   = bt.indicators.CrossUp(self.fast_ma, self.slow_ma)
        self.crossdown = bt.indicators.CrossDown(self.fast_ma, self.slow_ma)

    def next(self):
        if not self.position and self.crossup[0]:
            self.buy()
        elif self.position and self.crossdown[0]:
            self.close()

    def notify_trade(self, trade):
        if self.p.printlog and trade.isclosed:
            print(f"  交易: 盈亏={trade.pnlcomm:.2f}  净值={self.broker.getvalue():.2f}")


class VolSurgeStrategy(bt.Strategy):
    """
    量比放量策略：量比 > threshold 且当日上涨 → 买入，持 hold_days 天后卖出。
    """
    params = (
        ("vol_window",  20),
        ("vol_thresh",  2.0),
        ("hold_days",   5),
        ("printlog",    False),
    )

    def __init__(self):
        self.vol_ma    = bt.indicators.SMA(self.data.volume, period=self.p.vol_window)
        self.entry_bar = None

    def next(self):
        vol_ratio = self.data.volume[0] / (self.vol_ma[0] + 1e-9)
        up_today  = self.data.close[0] > self.data.close[-1]

        if not self.position:
            if vol_ratio > self.p.vol_thresh and up_today:
                self.buy()
                self.entry_bar = len(self)
                if self.p.printlog:
                    print(f"  买入 {self.data.datetime.date()} 量比={vol_ratio:.2f}")
        else:
            if len(self) >= self.entry_bar + self.p.hold_days:
                self.close()
                if self.p.printlog:
                    print(f"  卖出 {self.data.datetime.date()}")


class RSIStrategy(bt.Strategy):
    """RSI 超卖买入 / 超买卖出。"""
    params = (("period", 14), ("oversold", 30), ("overbought", 70))

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.period)

    def next(self):
        if not self.position and self.rsi[0] < self.p.oversold:
            self.buy()
        elif self.position and self.rsi[0] > self.p.overbought:
            self.close()


# ── 3. 运行引擎 ───────────────────────────────────────────────────────────────

def run_strategy(
    strategy_cls: Type[bt.Strategy],
    symbol: str,
    start: str = "2015-01-01",
    end: str | None = None,
    init_cash: float = 100_000,
    commission: float = 0.0003,
    strategy_params: dict | None = None,
    plot: bool = False,
) -> dict:
    """
    一行跑完单只股票回测，返回统计结果字典。

    示例：
        result = run_strategy(MACrossStrategy, "600519.SH",
                              start="2020-01-01", strategy_params={"fast":5,"slow":20})
        print(result)
    """
    cerebro = bt.Cerebro()

    # 数据
    cerebro.adddata(PGFeed.from_pg(symbol, start=start, end=end))

    # 策略
    params = strategy_params or {}
    cerebro.addstrategy(strategy_cls, **params)

    # 经纪商
    cerebro.broker.setcash(init_cash)
    cerebro.broker.setcommission(commission=commission)

    # 分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio,  _name="sharpe",
                        riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown,     _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns,      _name="returns")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer,_name="trades")

    results = cerebro.run()
    strat   = results[0]

    final_value  = cerebro.broker.getvalue()
    total_return = (final_value - init_cash) / init_cash

    sharpe   = strat.analyzers.sharpe.get_analysis().get("sharperatio") or 0
    max_dd   = strat.analyzers.drawdown.get_analysis().get("max", {}).get("drawdown", 0)
    trades   = strat.analyzers.trades.get_analysis()
    n_trades = trades.get("total", {}).get("closed", 0)
    win_rate = 0.0
    if n_trades > 0:
        won = trades.get("won", {}).get("total", 0)
        win_rate = won / n_trades

    result = {
        "symbol":       symbol,
        "start":        start,
        "end":          end or "今日",
        "init_cash":    init_cash,
        "final_value":  round(final_value, 2),
        "total_return": f"{total_return:.2%}",
        "sharpe_ratio": round(sharpe, 3) if sharpe else "N/A",
        "max_drawdown": f"{max_dd:.2f}%",
        "n_trades":     n_trades,
        "win_rate":     f"{win_rate:.1%}",
    }

    if plot:
        cerebro.plot(style="candlestick", iplot=False)

    return result


def compare_strategies(
    symbol: str,
    start: str = "2020-01-01",
    init_cash: float = 100_000,
) -> pd.DataFrame:
    """
    对同一只股票并排比较三个内置策略。
    """
    strategies = [
        ("MA(10/30)",      MACrossStrategy, {"fast": 10, "slow": 30}),
        ("MA(5/20)",       MACrossStrategy, {"fast":  5, "slow": 20}),
        ("量比放量(5日)",   VolSurgeStrategy, {"vol_thresh": 2.0, "hold_days": 5}),
        ("RSI(14)",        RSIStrategy,     {"period": 14}),
    ]
    rows = []
    for name, cls, params in strategies:
        r = run_strategy(cls, symbol, start=start, init_cash=init_cash,
                         strategy_params=params)
        r["strategy"] = name
        rows.append(r)

    df = pd.DataFrame(rows)[["strategy", "total_return", "sharpe_ratio",
                               "max_drawdown", "n_trades", "win_rate"]]
    return df.set_index("strategy")
