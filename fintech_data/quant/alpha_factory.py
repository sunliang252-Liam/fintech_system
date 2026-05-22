"""
fintech_data/quant/alpha_factory.py
用 qlib 表达式引擎计算技术因子（Alpha），并可将结果写回 PostgreSQL。

用法：
    from fintech_data.quant.alpha_factory import compute_alphas, save_alphas_to_pg

    df = compute_alphas(["SH600519", "SZ000858"], fields=ALPHA_FIELDS, start="2020-01-01")
    save_alphas_to_pg(df)
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from fintech_data.logger import get

log = get("alpha_factory")

# ── 预定义因子表达式（qlib 语法）────────────────────────────────────────────
ALPHA_FIELDS: dict[str, str] = {
    # 动量
    "mom_5":      "Ref($close,0)/Ref($close,5)-1",
    "mom_20":     "Ref($close,0)/Ref($close,20)-1",
    "mom_60":     "Ref($close,0)/Ref($close,60)-1",
    # 均线偏离
    "ma5_bias":   "$close/Mean($close,5)-1",
    "ma20_bias":  "$close/Mean($close,20)-1",
    # 波动率
    "vol_20":     "Std($close,20)/$close",
    # 换手率
    "turn_5":     "Mean($volume,5)/($volume+1e-9)",
    # 振幅
    "amp_5":      "Mean(($high-$low)/$close,5)",
    # RSI 近似
    "rsi_14":     "Mean(If($close>Ref($close,1),$close-Ref($close,1),0),14)/"
                  "(Mean(Abs($close-Ref($close,1)),14)+1e-9)",
    # MACD 信号线差
    "macd_diff":  "EMA($close,12)-EMA($close,26)",
}


def init_qlib_if_needed(qlib_dir: str | Path = "~/qlib_data"):
    """如果 qlib 尚未初始化则自动初始化。"""
    import qlib
    from qlib.constant import REG_CN
    try:
        qlib.get_module_logger("test")
    except Exception:
        pass
    qlib_dir = str(Path(qlib_dir).expanduser())
    qlib.init(provider_uri=qlib_dir, region=REG_CN)


def compute_alphas(
    instruments: str | Sequence[str] = "csi300",
    fields: dict[str, str] | None = None,
    start: str = "2018-01-01",
    end: str | None = None,
    qlib_dir: str | Path = "~/qlib_data",
) -> pd.DataFrame:
    """
    用 qlib.D.features() 计算 Alpha 因子。
    instruments: "csi300" 或具体股票列表 ["SH600519", "SZ000858"]
    返回 MultiIndex (instrument, datetime) DataFrame。
    """
    from qlib.data import D

    init_qlib_if_needed(qlib_dir)

    if fields is None:
        fields = ALPHA_FIELDS

    field_exprs = list(fields.values())
    field_names = list(fields.keys())

    log.info(f"计算 {len(field_names)} 个因子，范围: {start} ~ {end or 'today'}")
    df = D.features(
        instruments=instruments,
        fields=field_exprs,
        start_time=start,
        end_time=end,
        freq="day",
    )
    df.columns = field_names
    log.info(f"因子计算完成，shape: {df.shape}")
    return df


def save_alphas_to_pg(df: pd.DataFrame, table: str = "alpha_factors"):
    """
    将因子 DataFrame 写入 PostgreSQL。
    表结构: (ts_code TEXT, trade_date DATE, factor_name TEXT, value FLOAT)
    """
    from fintech_data import db

    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    ts_code    TEXT,
                    trade_date DATE,
                    factor_name TEXT,
                    value      FLOAT,
                    PRIMARY KEY (ts_code, trade_date, factor_name)
                )
            """)
        conn.commit()

        # MultiIndex (instrument, datetime) → 长表
        long = df.stack().reset_index()
        long.columns = ["ts_code", "trade_date", "factor_name", "value"]
        # qlib 使用 SH600519 格式，转回 600519.SH
        long["ts_code"] = long["ts_code"].str.replace(
            r"^(SH|SZ)(\d+)$", lambda m: f"{m.group(2)}.{m.group(1)}", regex=True
        )
        long = long.dropna(subset=["value"])

        rows = long.to_dict("records")
        db.upsert(conn, table, rows, ("ts_code", "trade_date", "factor_name"))
        log.info(f"写入 {len(rows)} 行到 {table}")
    finally:
        db.put_conn(conn)
