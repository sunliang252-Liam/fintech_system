"""
data_layer/turshare_connector/client.py
"""
from __future__ import annotations
from typing import Optional
from . import db


class LocalProAPI:
    def __init__(self, **pg_kwargs):
        self._pg_kwargs = pg_kwargs

    def _conn(self):
        return db.get_conn(**self._pg_kwargs)

    def daily(self, ts_code=None, start_date=None, end_date=None, trade_date=None):
        conds, params = [], []
        if ts_code:
            code = ts_code.split(".")[0]
            conds.append('"股票代码" = %s')
            params.append(code)
        if trade_date:
            conds.append('"日期" = %s')
            params.append(trade_date)
        if start_date:
            conds.append('"日期" >= %s')
            params.append(start_date)
        if end_date:
            conds.append('"日期" <= %s')
            params.append(end_date)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"""
            SELECT
                "股票代码" AS ts_code,
                "日期"     AS trade_date,
                "开盘"     AS open,
                "最高"     AS high,
                "最低"     AS low,
                "收盘"     AS close,
                "成交量"   AS vol,
                "成交额"   AS amount,
                "涨跌幅"   AS pct_chg,
                "涨跌额"   AS change,
                "换手率"   AS turnover_rate
            FROM stock_daily {where}
            ORDER BY "日期" ASC
        """
        return db.query(sql, tuple(params), self._conn())

    def stock_basic(self, ts_code=None, list_status=None, exchange=None):
        conds, params = [], []
        if ts_code:      conds.append('"股票代码" = %s'); params.append(ts_code.split(".")[0])
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = f'SELECT * FROM stock_basic {where} ORDER BY "股票代码" ASC'
        return db.query(sql, tuple(params), self._conn())

    def adj_factor(self, ts_code=None, start_date=None, end_date=None, trade_date=None):
        conds, params = [], []
        if ts_code:     conds.append('"股票代码" = %s'); params.append(ts_code.split(".")[0])
        if trade_date:  conds.append('"日期" = %s');     params.append(trade_date)
        if start_date:  conds.append('"日期" >= %s');    params.append(start_date)
        if end_date:    conds.append('"日期" <= %s');    params.append(end_date)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"""
            SELECT
                "股票代码" AS ts_code,
                "日期"     AS trade_date,
                "复权因子" AS adj_factor
            FROM adj_factor {where}
            ORDER BY "日期" ASC
        """
        return db.query(sql, tuple(params), self._conn())

    def trade_cal(self, exchange=None, start_date=None, end_date=None, is_open=None):
        conds, params = [], []
        if exchange:   conds.append("exchange = %s");    params.append(exchange)
        if start_date: conds.append("cal_date >= %s");   params.append(start_date)
        if end_date:   conds.append("cal_date <= %s");   params.append(end_date)
        if is_open is not None:
            conds.append("is_open = %s"); params.append(is_open)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"SELECT exchange, cal_date, is_open, pretrade_date FROM trade_cal {where} ORDER BY cal_date ASC"
        return db.query(sql, tuple(params), self._conn())

    def pro_bar(self, ts_code: str, start_date=None, end_date=None, adj=None):
        import pandas as pd
        df = self.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if df.empty or adj is None:
            return df
        try:
            af = self.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception:
            return df
        if af.empty:
            return df
        df = df.merge(af[["trade_date", "adj_factor"]], on="trade_date", how="left")
        df["adj_factor"] = df["adj_factor"].fillna(1.0)
        price_cols = ["open", "high", "low", "close"]
        if adj == "qfq":
            latest = df["adj_factor"].iloc[-1]
            for col in price_cols:
                df[col] = (df[col] * df["adj_factor"] / latest).round(4)
        elif adj == "hfq":
            for col in price_cols:
                df[col] = (df[col] * df["adj_factor"]).round(4)
        return df.drop(columns=["adj_factor"])

    def query(self, api_name, **kwargs):
        _dispatch = {
            "daily":       self.daily,
            "stock_basic": self.stock_basic,
            "adj_factor":  self.adj_factor,
            "trade_cal":   self.trade_cal,
            "pro_bar":     self.pro_bar,
        }
        if api_name not in _dispatch:
            raise ValueError(f"不支持: {api_name}。已支持: {list(_dispatch)}")
        return _dispatch[api_name](**kwargs)


def pro_api(**pg_kwargs) -> LocalProAPI:
    return LocalProAPI(**pg_kwargs)
