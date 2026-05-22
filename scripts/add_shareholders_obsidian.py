#!/usr/bin/env python3
"""
scripts/add_shareholders_obsidian.py
从 Tushare 拉取前十大股东 / 前十大流通股东，写入 Obsidian 文件。

用法：
  python3 scripts/add_shareholders_obsidian.py            # 处理全部文件（跳过已有章节）
  python3 scripts/add_shareholders_obsidian.py --force    # 强制覆盖已有章节
  python3 scripts/add_shareholders_obsidian.py --hs300    # 只处理沪深300

Tushare 接口：
  top10_holders      — 前十大股东（含非流通）
  top10_floatholders — 前十大流通股东
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/liam-sun/fintech_system")
os.chdir("/home/liam-sun/fintech_system")

VAULT_DIR     = Path.home() / "Documents/Obsidian_Vault/02_Company_Analysis"
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a")
MARKER        = "## 💼 股东结构"
SLEEP_SEC     = 0.6   # 每只股票两次请求后等待，避免触发限频


# ── Tushare ──────────────────────────────────────────────────────────────────

def ts_post(api_name: str, **params) -> list[dict]:
    url     = "https://api.tushare.pro"
    payload = json.dumps({"api_name": api_name, "token": TUSHARE_TOKEN,
                          "params": params}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read())
    except Exception as e:
        print(f"    网络错误: {e}")
        return []
    if res.get("code") != 0:
        return []
    fields = res["data"]["fields"]
    return [dict(zip(fields, row)) for row in res["data"]["items"]]


def fetch_holders(ts_code: str) -> tuple[list, list, str]:
    """返回 (前十大股东, 前十大流通股东, 截止日期)"""
    holders       = ts_post("top10_holders",      ts_code=ts_code, limit=10)
    float_holders = ts_post("top10_floatholders", ts_code=ts_code, limit=10)

    if not holders and not float_holders:
        return [], [], ""

    # 只取最新一期
    period = ""
    if holders:
        period = holders[0]["end_date"]
        holders = [r for r in holders if r["end_date"] == period]
    if float_holders:
        fp = float_holders[0]["end_date"]
        float_holders = [r for r in float_holders if r["end_date"] == fp]
        if not period:
            period = fp

    return holders, float_holders, period


# ── 格式化 ────────────────────────────────────────────────────────────────────

def _fmt_amount(val) -> str:
    if val is None:
        return "-"
    try:
        return f"{float(val) / 10000:.2f}"
    except (ValueError, TypeError):
        return "-"


def _fmt_ratio(val) -> str:
    if val is None:
        return "-"
    try:
        return f"{float(val):.2f}%"
    except (ValueError, TypeError):
        return "-"


def _fmt_change(val) -> str:
    if val is None:
        return "-"
    try:
        v = float(val) / 10000
        if v > 0:
            return f"▲{v:.2f}"
        elif v < 0:
            return f"▼{abs(v):.2f}"
        return "持平"
    except (ValueError, TypeError):
        return "-"


def _is_same(a: list, b: list) -> bool:
    """判断两个持股列表是否实质相同（名称集合一样）"""
    if len(a) != len(b):
        return False
    return {r["holder_name"] for r in a} == {r["holder_name"] for r in b}


def holder_block(holders: list, float_holders: list, period: str) -> str:
    date_fmt = f"{period[:4]}-{period[4:6]}-{period[6:]}" if len(period) == 8 else period
    lines    = [f"\n{MARKER}（截至 {date_fmt}）\n"]

    def table(rows: list) -> list[str]:
        t = ["| 股东名称 | 持股量（万股）| 持股比例 | 持股变化（万股）| 股东类型 |",
             "|---------|-------------|--------|--------------|--------|"]
        for r in rows:
            t.append(
                f"| {r.get('holder_name','-')} "
                f"| {_fmt_amount(r.get('hold_amount'))} "
                f"| {_fmt_ratio(r.get('hold_ratio'))} "
                f"| {_fmt_change(r.get('hold_change'))} "
                f"| {r.get('holder_type') or '-'} |"
            )
        return t

    if holders:
        lines.append("### 前十大股东\n")
        lines.extend(table(holders))

    # 只有和前十大不同时才单独展示流通股东
    if float_holders and not _is_same(holders, float_holders):
        lines.append("\n### 前十大流通股东\n")
        lines.extend(table(float_holders))
    elif float_holders and _is_same(holders, float_holders):
        lines.append("\n> 前十大流通股东与前十大股东相同")

    lines.append("")
    return "\n".join(lines) + "\n"


# ── 写入 Obsidian ─────────────────────────────────────────────────────────────

def update_file(path: Path, ts_code: str, force: bool) -> str:
    """返回 'updated' / 'skipped' / 'no_data'"""
    content = path.read_text(encoding="utf-8")

    if MARKER in content and not force:
        return "skipped"

    holders, float_holders, period = fetch_holders(ts_code)
    time.sleep(SLEEP_SEC)

    if not period:
        return "no_data"

    block = holder_block(holders, float_holders, period)

    if MARKER in content:
        # 替换旧章节（从 MARKER 到下一个 ## 或文件末尾）
        content = re.sub(
            rf"\n{re.escape(MARKER)}.+?(?=\n## |\Z)",
            "",
            content,
            flags=re.DOTALL,
        )

    path.write_text(content.rstrip() + "\n" + block, encoding="utf-8")
    return "updated"


# ── HS300 名单 ────────────────────────────────────────────────────────────────

def load_hs300_codes() -> set[str]:
    import psycopg2
    try:
        conn = psycopg2.connect(host="localhost", port=5432, dbname="fintech_db",
                                user="postgres", password="fintech123")
        cur  = conn.cursor()
        cur.execute("SELECT ts_code FROM index_components WHERE index_code='000300.SH'")
        codes = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return codes
    except Exception as e:
        print(f"无法读取 HS300 名单: {e}")
        return set()


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    force  = "--force"  in sys.argv
    hs300  = "--hs300"  in sys.argv

    hs300_codes = load_hs300_codes() if hs300 else None

    # 收集所有 Obsidian 文件，提取 ts_code
    files: list[tuple[Path, str]] = []
    for p in sorted(VAULT_DIR.glob("*.md")):
        m = re.match(r"^(\d{6})_([A-Z]{2})_", p.name)
        if not m:
            continue
        code6, market = m.group(1), m.group(2)
        ts_code = f"{code6}.{market}"
        if hs300_codes is not None and ts_code not in hs300_codes:
            continue
        files.append((p, ts_code))

    total   = len(files)
    updated = skipped = no_data = error = 0

    print(f"{'HS300' if hs300 else '全量'} 模式  共 {total} 只  force={force}\n")

    for i, (path, ts_code) in enumerate(files, 1):
        try:
            result = update_file(path, ts_code, force)
        except Exception as e:
            print(f"[{i:>4}/{total}] {ts_code}  ERROR: {e}")
            error += 1
            continue

        if result == "updated":
            updated += 1
            print(f"[{i:>4}/{total}] {ts_code}  ✓ 已写入")
        elif result == "skipped":
            skipped += 1
            if i % 200 == 0:
                print(f"[{i:>4}/{total}] ... 已跳过 {skipped} 只（已有章节）")
        else:
            no_data += 1
            print(f"[{i:>4}/{total}] {ts_code}  — 无数据")

    print(f"\n完成 | 写入: {updated} | 跳过: {skipped} | 无数据: {no_data} | 报错: {error}")


if __name__ == "__main__":
    main()
