"""
fintech_data/quant/pg_to_qlib.py
将 PostgreSQL stock_daily_hist 数据导出为 qlib 标准数据集，并初始化 qlib provider。

用法：
    python -m fintech_data.quant.pg_to_qlib --qlib-dir ~/qlib_data --start 20200101
    python -m fintech_data.quant.pg_to_qlib --symbols 600519.SH 000858.SZ --qlib-dir ~/qlib_data
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

import pandas as pd

from fintech_data import db, config
from fintech_data.logger import get

log = get("pg_to_qlib")

QLIB_FIELDS = ["open", "high", "low", "close", "volume", "amount", "change", "pct_chg"]
PG_TO_QLIB = {
    "open":    "$open",
    "high":    "$high",
    "low":     "$low",
    "close":   "$close",
    "vol":     "$volume",
    "amount":  "$amount",
    "change":  "$change",
    "pct_chg": "$factor",
}


def _ts_to_qlib_symbol(ts_code: str) -> str:
    """600519.SH → SH600519 (qlib 惯例)"""
    code, market = ts_code.split(".")
    return f"{market}{code}"


def fetch_ohlcv(
    symbols: list[str] | None = None,
    start: str = "20140101",
    end: str | None = None,
) -> pd.DataFrame:
    """从 stock_daily_hist 取 OHLCV 数据，返回 MultiIndex (ts_code, trade_date) DataFrame。"""
    conn = db.get_conn()
    try:
        where_parts = [f"trade_date >= '{start}'"]
        if end:
            where_parts.append(f"trade_date <= '{end}'")
        if symbols:
            sym_list = ", ".join(f"'{s}'" for s in symbols)
            where_parts.append(f"ts_code IN ({sym_list})")

        sql = f"""
            SELECT ts_code, trade_date, open, high, low, close,
                   vol, amount, change, pct_chg
            FROM stock_daily_hist
            WHERE {' AND '.join(where_parts)}
            ORDER BY ts_code, trade_date
        """
        df = pd.read_sql(sql, conn)
    finally:
        db.put_conn(conn)

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index(["ts_code", "trade_date"]).sort_index()
    return df


def dump_qlib_csv(qlib_dir: str | Path, symbols: list[str] | None = None, start: str = "20140101"):
    """
    导出为 qlib csv provider 目录结构：
        qlib_dir/
          instruments/all.txt
          features/<SYMBOL>/<field>.day.bin  ← 使用 qlib dump_bin 工具
    实际上这里先写成 CSV，再用 qlib 的 dump_bin.py 转换。
    """
    import qlib
    from qlib.data.data import LocalDatasetProvider
    from qlib.utils import init_instance_by_config

    qlib_dir = Path(qlib_dir)
    csv_dir = qlib_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    log.info("从 PostgreSQL 拉取行情数据 …")
    df = fetch_ohlcv(symbols=symbols, start=start)

    all_symbols = df.index.get_level_values("ts_code").unique().tolist()
    instr_dir = qlib_dir / "instruments"
    instr_dir.mkdir(parents=True, exist_ok=True)

    with open(instr_dir / "all.txt", "w") as f:
        for sym in all_symbols:
            qsym = _ts_to_qlib_symbol(sym)
            f.write(f"{qsym}\t{df.loc[sym].index.min().strftime('%Y-%m-%d')}\t{df.loc[sym].index.max().strftime('%Y-%m-%d')}\n")

    log.info(f"共 {len(all_symbols)} 只股票，写入 CSV …")
    for ts_code, grp in df.groupby(level="ts_code"):
        qsym = _ts_to_qlib_symbol(ts_code)
        out = grp.reset_index(level="ts_code", drop=True).copy()
        out.index.name = "date"
        out.to_csv(csv_dir / f"{qsym}.csv")

    log.info(f"CSV 已写入 {csv_dir}，共 {len(all_symbols)} 个文件")
    return csv_dir


def init_qlib(qlib_dir: str | Path, provider: str = "file"):
    """
    初始化 qlib，使 qlib.D.features() 可用。
    provider='file' 使用本地 CSV；provider='mongo' 需额外配置。
    """
    import qlib
    from qlib.constant import REG_CN

    qlib_dir = str(Path(qlib_dir).expanduser())
    qlib.init(
        provider_uri=qlib_dir,
        region=REG_CN,
    )
    log.info(f"qlib 已初始化，数据目录: {qlib_dir}")


def _cli():
    parser = argparse.ArgumentParser(description="导出 fintech DB 行情到 qlib 格式")
    parser.add_argument("--qlib-dir", default="~/qlib_data", help="qlib 数据根目录")
    parser.add_argument("--start", default="20140101", help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD")
    parser.add_argument("--symbols", nargs="+", default=None, help="指定股票代码，如 600519.SH")
    args = parser.parse_args()

    csv_dir = dump_qlib_csv(
        qlib_dir=Path(args.qlib_dir).expanduser(),
        symbols=args.symbols,
        start=args.start,
    )
    print(f"\n完成。CSV 目录: {csv_dir}")
    print("下一步：运行 qlib dump_bin 将 CSV 转为二进制格式（可选，可直接用 CSV provider）")


if __name__ == "__main__":
    _cli()
