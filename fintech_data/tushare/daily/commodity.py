"""tushare/daily/commodity.py — 大宗商品雷达增量更新 + Obsidian报告"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from pathlib import Path
from ..client import get_pro
from ... import config, db, logger

log = logger.get("commodity")

COMMODITY_MAP = {
    "LC.GFE": "碳酸锂(GFE)",
    "NI.SHF": "沪镍(SHFE)",
    "CU.SHF": "沪铜(SHFE)",
    "AU.SHF": "沪金(SHFE)",
    "SC.INE": "原油(INE)",
    "RB.SHF": "螺纹钢(SHFE)",
}

OBSIDIAN_RADAR = Path("/home/liam-sun/Documents/Obsidian_Vault/03_Technical/Commodity_Radar.md")


def _last_date(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(trade_date) FROM commodity_radar")
        val = cur.fetchone()[0]
    if val is None:
        return (datetime.today() - timedelta(days=40)).strftime("%Y%m%d")
    return str(val).replace("-", "")


def _write_obsidian(rows: list[dict]):
    if not rows:
        return
    by_code: dict[str, dict] = {}
    for r in rows:
        code = r.get("ts_code", "")
        if code not in by_code or r.get("trade_date", "") > by_code[code].get("trade_date", ""):
            by_code[code] = r

    lines = [
        "# 大宗商品全球雷达",
        f"\n> 最后同步：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "\n---\n",
        "| 品种 | 日期 | 收盘价 | 结算价 |",
        "|------|------|--------|--------|",
    ]
    for code, name in COMMODITY_MAP.items():
        r = by_code.get(code, {})
        lines.append(
            f"| {name} | {r.get('trade_date','-')} "
            f"| {r.get('close','-')} | {r.get('settle','-')} |"
        )

    OBSIDIAN_RADAR.parent.mkdir(parents=True, exist_ok=True)
    OBSIDIAN_RADAR.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Obsidian 商品雷达已更新: {OBSIDIAN_RADAR.name}")


def run() -> dict:
    pro   = get_pro()
    conn  = db.get_conn()
    end   = datetime.today().strftime("%Y%m%d")
    start = _last_date(conn)

    all_rows = []
    try:
        for code, name in COMMODITY_MAP.items():
            try:
                df = pro.fut_daily(ts_code=code, start_date=start, end_date=end)
                if df is not None and not df.empty:
                    df["commodity_name"] = name
                    rows = df.to_dict("records")
                    n    = db.upsert(conn, "commodity_radar", rows, ("ts_code", "trade_date"))
                    all_rows.extend(rows)
                    log.info(f"[{code}] {name}: {n} 行")
            except Exception as e:
                log.warning(f"[{code}] 失败: {e}")
            time.sleep(0.5)
    finally:
        db.put_conn(conn)

    _write_obsidian(all_rows)
    log.info(f"commodity 完成: {len(all_rows)} 行")
    return {"rows": len(all_rows)}
