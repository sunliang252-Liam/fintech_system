"""
fintech_data/scheduler.py — 主入口，cron 每日调用

每日任务（每天盘后运行）：
    python -m fintech_data.scheduler --daily

季度任务（年报季手动触发，或按需 cron）：
    python -m fintech_data.scheduler --quarterly

巨潮年报全流程（下载→转MD→推理→同步）：
    python -m fintech_data.scheduler --annual-report \
        --disclosure-index /path/to/all_disclosure_dates.csv

单独运行某个模块：
    python -m fintech_data.scheduler --only stock_hist
    python -m fintech_data.scheduler --only deepseek [--dry-run]
"""
from __future__ import annotations
import argparse
import sys
import time
from datetime import datetime
from . import logger

log = logger.get("scheduler")


# ── 每日任务 ──────────────────────────────────────────────────────────────────

def run_daily():
    log.info("=== 每日更新开始 ===")
    results = {}

    from .tushare.daily import stock_hist, macro, index, lhb

    from .tushare.daily import commodity

    for name, fn in [
        ("stock_hist", stock_hist.run),
        ("macro",      macro.run),
        ("index",      index.run),
        ("lhb",        lhb.run),
        ("commodity",  commodity.run),
    ]:
        t0 = time.time()
        try:
            results[name] = fn()
            log.info(f"[{name}] 完成 ({time.time()-t0:.0f}s): {results[name]}")
        except Exception as e:
            log.error(f"[{name}] 失败: {e}")
            results[name] = {"error": str(e)}

    log.info(f"=== 每日更新结束 | {results} ===")
    return results


# ── 季度任务 ──────────────────────────────────────────────────────────────────

def run_quarterly(period: str | None = None):
    from . import db
    from .tushare.quarterly import detector, income, balance_sheet, cashflow

    conn    = db.get_conn()
    pending = detector.get_pending(conn, period)
    db.put_conn(conn)

    if not pending:
        log.info("季度任务：无待补数据")
        return {}

    p = period or detector.ANNUAL_PERIOD
    log.info(f"=== 季度财报更新 period={p}，共 {len(pending)} 只 ===")

    results = {}
    for name, fn in [
        ("income",        income.run),
        ("balance_sheet", balance_sheet.run),
        ("cashflow",      cashflow.run),
    ]:
        t0 = time.time()
        try:
            n = fn(pending, p)
            results[name] = n
            log.info(f"[{name}] {n} 行 ({time.time()-t0:.0f}s)")
        except Exception as e:
            log.error(f"[{name}] 失败: {e}")
            results[name] = -1

    log.info(f"=== 季度任务结束 | {results} ===")
    return results


# ── 巨潮年报全流程 ────────────────────────────────────────────────────────────

def run_annual_report(disclosure_index_csv: str, dry_run: bool = False):
    from .juchao import downloader, pdf_to_md, deepseek_infer, obsidian_sync
    from . import db

    log.info("=== 年报全流程开始 ===")

    # 1. 下载 PDF
    log.info("[1/4] PDF 下载")
    dl_result = downloader.run(disclosure_index_csv=disclosure_index_csv)
    log.info(f"下载结果: {dl_result}")

    # 2. 获取待转换列表（已下载但尚无 MD 的）
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT ts_code, name FROM stock_basic")
        all_stocks = cur.fetchall()
    db.put_conn(conn)

    codes_for_md = [
        (ts_code, name)
        for ts_code, name in all_stocks
    ]

    log.info("[2/4] PDF → MD 转换")
    md_result = pdf_to_md.run(codes_for_md, workers=4)
    log.info(f"转换结果: {md_result}")

    # 3. 附注字段提取 + DeepSeek 推理
    log.info("[3a/4] 附注字段提取")
    from .juchao import extract_supplements
    supp_result = extract_supplements.run()
    log.info(f"附注提取结果: {supp_result}")

    log.info("[3b/4] DeepSeek 推理")
    infer_result = deepseek_infer.run(dry_run=dry_run)
    log.info(f"推理结果: {infer_result}")

    # 4. Obsidian 同步
    log.info("[4/4] Obsidian 同步")
    sync_result = obsidian_sync.run(refresh_cache=True)
    log.info(f"同步结果: {sync_result}")

    log.info("=== 年报全流程结束 ===")
    return {
        "download":    dl_result,
        "pdf_to_md":   md_result,
        "supplements": supp_result,
        "infer":       infer_result,
        "obsidian":    sync_result,
    }


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="fintech_data 调度器")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--daily",         action="store_true", help="运行每日任务")
    group.add_argument("--quarterly",     action="store_true", help="运行季度财报任务")
    group.add_argument("--annual-report", action="store_true", help="运行年报全流程")
    group.add_argument("--only",          metavar="MODULE",    help="只运行指定模块")

    parser.add_argument("--period",            help="财报期，如 20241231")
    parser.add_argument("--disclosure-index",  help="all_disclosure_dates.csv 路径")
    parser.add_argument("--dry-run",           action="store_true")

    args = parser.parse_args()

    if args.daily:
        run_daily()

    elif args.quarterly:
        run_quarterly(args.period)

    elif args.annual_report:
        if not args.disclosure_index:
            parser.error("--annual-report 需要 --disclosure-index 参数")
        run_annual_report(args.disclosure_index, dry_run=args.dry_run)

    elif args.only:
        mod = args.only
        if mod == "stock_hist":
            from .tushare.daily.stock_hist import run; run()
        elif mod == "macro":
            from .tushare.daily.macro import run; run()
        elif mod == "index":
            from .tushare.daily.index import run; run()
        elif mod == "lhb":
            from .tushare.daily.lhb import run; run()
        elif mod == "quarterly":
            run_quarterly(args.period)
        elif mod == "download":
            if not args.disclosure_index:
                parser.error("--only download 需要 --disclosure-index 参数")
            from .juchao.downloader import run; run(args.disclosure_index)
        elif mod == "pdf_to_md":
            from .juchao.pdf_to_md import run
            from . import db
            conn = db.get_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT ts_code, name FROM stock_basic")
                codes = cur.fetchall()
            db.put_conn(conn)
            run(codes)
        elif mod == "deepseek":
            from .juchao.deepseek_infer import run; run(dry_run=args.dry_run)
        elif mod == "obsidian":
            from .juchao.obsidian_sync import run; run(refresh_cache=True)
        else:
            print(f"未知模块: {mod}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
