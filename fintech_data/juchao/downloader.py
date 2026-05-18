"""juchao/downloader.py — 年报 PDF 增量下载（整合自 download_v8_final.py）

用法：
    from fintech_data.juchao.downloader import run
    run(disclosure_index_csv="/path/to/all_disclosure_dates.csv")
"""
from __future__ import annotations
import time
import pandas as pd
from pathlib import Path
from .client import get_session, search_announcement, build_pdf_url
from .. import config, logger

log = logger.get("juchao_downloader")


def _pdf_path(name: str) -> Path:
    safe = name.replace("/", "_").replace("\\", "_")
    return config.PDF_DIR / f"{safe}：2025年年度报告.pdf"


def run(
    disclosure_index_csv: str,
    pending_csv: str | None = None,
) -> dict:
    """
    下载年报 PDF。

    disclosure_index_csv: all_disclosure_dates.csv（含 ts_code, actual_date 列）
    pending_csv:          待下载名单，含 ts_code, name 列。
                          若为 None 则从 stock_basic 表读取全量。
    """
    config.PDF_DIR.mkdir(parents=True, exist_ok=True)

    df_index = pd.read_csv(disclosure_index_csv)
    df_index["ts_code"] = df_index["ts_code"].astype(str)

    if pending_csv:
        df_pending = pd.read_csv(pending_csv)
    else:
        # 从数据库读取全量股票列表
        import psycopg2
        conn = psycopg2.connect(**config.DB)
        with conn.cursor() as cur:
            cur.execute("SELECT ts_code, name FROM stock_basic ORDER BY ts_code")
            rows = cur.fetchall()
        conn.close()
        df_pending = pd.DataFrame(rows, columns=["ts_code", "name"])

    log.info(f"待处理 {len(df_pending)} 家")

    ok = skip = fail = no_date = 0
    session = get_session()

    for _, row in df_pending.iterrows():
        ts_code = str(row["ts_code"])
        name    = str(row["name"])
        pdf_path = _pdf_path(name)

        if pdf_path.exists():
            skip += 1
            continue

        date_info = df_index[df_index["ts_code"] == ts_code]
        if date_info.empty or pd.isna(date_info.iloc[0].get("actual_date")):
            no_date += 1
            continue

        actual_date = str(int(date_info.iloc[0]["actual_date"]))
        symbol      = ts_code.split(".")[0]

        try:
            ann_id = search_announcement(symbol, actual_date)
            if not ann_id:
                fail += 1
                log.warning(f"[{ts_code}] {name} 未找到公告 ID")
                time.sleep(config.JUCHAO["delay"])
                continue

            pdf_url = build_pdf_url(ann_id, actual_date)
            r = session.get(pdf_url, timeout=config.JUCHAO["timeout"])
            if r.status_code == 200:
                pdf_path.write_bytes(r.content)
                ok += 1
                log.info(f"[{ok}] {name} 下载完成")
            else:
                fail += 1
                log.warning(f"[{ts_code}] HTTP {r.status_code}")
        except Exception as e:
            fail += 1
            log.warning(f"[{ts_code}] 异常: {e}")
            time.sleep(config.JUCHAO["delay"] * 2)
            continue

        time.sleep(config.JUCHAO["delay"])

    log.info(f"下载完成: 成功={ok} 跳过={skip} 失败={fail} 无日期={no_date}")
    return {"ok": ok, "skip": skip, "fail": fail, "no_date": no_date}
