"""juchao/extract_supplements.py — 从 plumber MD 正则提取第一等级附注字段 → annual_report_supplements"""
from __future__ import annotations
import re
import json
from pathlib import Path
from collections import defaultdict
from .. import config, db, logger

log = logger.get("extract_supplements")


# ── 数值解析 ──────────────────────────────────────────────────────────────────

def _num(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace(",", "").replace("，", "").strip()
    mul = 1
    if "亿" in s:
        mul = 1e8
        s = s.replace("亿", "")
    elif "万" in s:
        mul = 1e4
        s = s.replace("万", "")
    try:
        return float(s) * mul
    except ValueError:
        return None


# ── ts_code 解析 ──────────────────────────────────────────────────────────────

_name_map: dict[str, str] = {}


def _load_name_map():
    if _name_map:
        return
    if not config.STOCK_CACHE.exists():
        return
    cache = json.loads(config.STOCK_CACHE.read_text("utf-8"))
    for code, info in cache.items():
        name = re.sub(r"\s+", "", info.get("name", ""))
        market = info.get("market", "SH")
        _name_map[name] = f"{code}.{market}"


def ts_code_from_path(path: Path) -> str:
    _load_name_map()
    stem    = path.stem
    cn_name = stem.split("：")[0].split(":")[0]
    normalized = re.sub(r"\s+", "", cn_name)
    if normalized in _name_map:
        return _name_map[normalized]
    m = re.search(r"(\d{6})[-_.]?(SH|SZ|BJ)", path.stem, re.IGNORECASE)
    if m:
        return f"{m.group(1)}.{m.group(2).upper()}"
    return f"UNKNOWN_{normalized[:10]}"


# ── 字段提取函数 ──────────────────────────────────────────────────────────────

def _contract_liab(text: str) -> dict:
    r = {"end": None, "start": None}
    for pat in [
        r"预收经销商货款[^\d]*([\d,]+\.?\d*)[^\d\n]+([\d,]+\.?\d*)",
        r"合同负债.*?合计[^\d]*([\d,]+\.?\d*)[^\d\n]+([\d,]+\.?\d*)",
        r"合同负债\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)",
    ]:
        m = re.search(pat, text, re.MULTILINE)
        if m:
            r["end"], r["start"] = _num(m.group(1)), _num(m.group(2))
            return r
    return r


def _construction(text: str) -> dict:
    r = {"end": None, "start": None, "largest_name": None,
         "largest_budget": None, "largest_done_pct": None}
    m = re.search(r"在建工程\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)", text)
    if m:
        r["end"], r["start"] = _num(m.group(1)), _num(m.group(2))
    pat = re.compile(
        r"([^\|\n]{4,30})\s*\|[^\|]*\|[^\|]*\|[^\|]*\|([\d,]+\.?\d+)[^\|]*\|[^\|]*\|[^\|]*\|([\d.]+)%"
    )
    best = 0
    for m in pat.finditer(text):
        budget = _num(m.group(2))
        if budget and budget > best:
            best = budget
            r["largest_name"]     = m.group(1).strip()
            r["largest_budget"]   = budget
            r["largest_done_pct"] = float(m.group(3))
    return r


def _rd(text: str) -> dict:
    r = {"total": None, "capitalized": None, "cap_rate": None}
    for pat in [
        r"研发投入(?:金额)?[（(][元][)）][^\d]*([\d,]+\.?\d+)",
        r"研发投入.*?([\d,]+\.?\d+).*?(?:元|亿|万)",
    ]:
        m = re.search(pat, text)
        if m:
            r["total"] = _num(m.group(1))
            break
    m = re.search(r"研发投入资本化(?:的)?金额[（(][元][)）][^\d]*([\d,]+\.?\d+)", text)
    if m:
        r["capitalized"] = _num(m.group(1))
    m = re.search(r"资本化研发投入占研发投入的比例[^\d]*([\d.]+)%", text)
    if m:
        r["cap_rate"] = float(m.group(1))
    elif r["total"] and r["capitalized"]:
        r["cap_rate"] = round(r["capitalized"] / r["total"] * 100, 2)
    return r


def _interest_cap(text: str) -> float | None:
    for pat in [
        r"本期利息资本化金额[^\d]*([\d,]+\.?\d+)",
        r"利息资本化.*?合计[^\d]*([\d,]+\.?\d+)",
        r"资本化利息.*?([\d,]+\.?\d+)",
    ]:
        m = re.search(pat, text)
        if m:
            return _num(m.group(1))
    return None


def _customer_conc(text: str) -> dict:
    r = {"top5_pct": None, "related_pct": None}
    m = re.search(r"前五名客户.*?(?:合计|销售额)[^\d]*([\d.]+)%", text, re.DOTALL)
    if m:
        r["top5_pct"] = float(m.group(1))
    m = re.search(r"关联方.*?占.*?([\d.]+)%", text)
    if m:
        r["related_pct"] = float(m.group(1))
    return r


def _non_recurring(text: str) -> float | None:
    m = re.search(r"(?:非经常性损益)?合计[^\d\-]*([\-\d,]+\.?\d+)", text)
    if m:
        return _num(m.group(1))
    m = re.search(r"非经常性损益.*?合计.*?([\d,]+\.?\d+)", text, re.DOTALL)
    if m:
        return _num(m.group(1))
    return None


def _goodwill(text: str) -> float | None:
    m = re.search(r"商誉\s+([\d,]+\.?\d+)\s+[\d,]+\.?\d+", text)
    return _num(m.group(1)) if m else None


def _bank(text: str) -> dict:
    r = {"npl_ratio": None, "provision_coverage": None, "nim": None, "attention_ratio": None}
    for key, pat in [
        ("npl_ratio",          r"不良贷款率[^\d]*([\d.]+)%"),
        ("provision_coverage", r"拨备覆盖率[^\d]*([\d.]+)%"),
        ("nim",                r"净息差[^\d]*([\d.]+)%"),
        ("attention_ratio",    r"关注类.*?占比[^\d]*([\d.]+)%"),
    ]:
        m = re.search(pat, text)
        if m:
            r[key] = float(m.group(1))
    return r


# ── 单文件提取 ────────────────────────────────────────────────────────────────

def extract_one(path: Path) -> dict:
    text    = path.read_text("utf-8", errors="ignore")
    ts_code = ts_code_from_path(path)
    cl = _contract_liab(text)
    ci = _construction(text)
    rd = _rd(text)
    cc = _customer_conc(text)
    bk = _bank(text)

    record = {
        "ts_code":                ts_code,
        "source":                 "plumber",
        "contract_liab_end":      cl["end"],
        "contract_liab_start":    cl["start"],
        "construction_end":       ci["end"],
        "construction_start":     ci["start"],
        "largest_project_name":   ci["largest_name"],
        "largest_project_budget": ci["largest_budget"],
        "largest_project_done":   ci["largest_done_pct"],
        "rd_total":               rd["total"],
        "rd_capitalized":         rd["capitalized"],
        "rd_cap_rate":            rd["cap_rate"],
        "interest_capitalized":   _interest_cap(text),
        "customer_top5_pct":      cc["top5_pct"],
        "customer_related_pct":   cc["related_pct"],
        "non_recurring_total":    _non_recurring(text),
        "goodwill":               _goodwill(text),
        "npl_ratio":              bk["npl_ratio"],
        "provision_coverage":     bk["provision_coverage"],
        "nim":                    bk["nim"],
        "attention_ratio":        bk["attention_ratio"],
    }

    tier1   = ["contract_liab_end", "construction_end", "rd_total",
               "interest_capitalized", "non_recurring_total"]
    missing = [f for f in tier1 if record.get(f) is None]
    record["missing_fields"] = ",".join(missing)
    record["confidence"]     = "high" if not missing else ("mid" if len(missing) <= 2 else "low")
    return record


# ── 批量 + 入库 ───────────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO annual_report_supplements
  (ts_code, end_date, report_year, source, confidence, missing_fields,
   contract_liab_end, contract_liab_start,
   construction_end, largest_project_name,
   largest_project_budget, largest_project_done,
   rd_total, rd_capitalized, rd_cap_rate,
   interest_capitalized, non_recurring_total, goodwill,
   npl_ratio, provision_coverage, nim, attention_loan_ratio)
VALUES (%(ts_code)s, '2025-12-31', 2025, %(source)s,
        %(confidence)s, %(missing_fields)s,
        %(contract_liab_end)s, %(contract_liab_start)s,
        %(construction_end)s, %(largest_project_name)s,
        %(largest_project_budget)s, %(largest_project_done)s,
        %(rd_total)s, %(rd_capitalized)s, %(rd_cap_rate)s,
        %(interest_capitalized)s, %(non_recurring_total)s,
        %(goodwill)s, %(npl_ratio)s, %(provision_coverage)s,
        %(nim)s, %(attention_ratio)s)
ON CONFLICT (ts_code, end_date) DO UPDATE SET
  source=EXCLUDED.source, confidence=EXCLUDED.confidence,
  missing_fields=EXCLUDED.missing_fields,
  contract_liab_end=EXCLUDED.contract_liab_end,
  construction_end=EXCLUDED.construction_end,
  rd_total=EXCLUDED.rd_total, rd_cap_rate=EXCLUDED.rd_cap_rate,
  interest_capitalized=EXCLUDED.interest_capitalized,
  non_recurring_total=EXCLUDED.non_recurring_total,
  report_year=2025, updated_at=NOW()
"""


def run(report_year: int = 2025) -> dict:
    files = list(config.MD_DIR.glob("*.md"))
    log.info(f"extract_supplements: 发现 {len(files)} 个 MD 文件")

    records = []
    stats   = defaultdict(int)
    for i, f in enumerate(files):
        r = extract_one(f)
        records.append(r)
        stats[r["confidence"]] += 1
        if (i + 1) % 200 == 0:
            log.info(f"进度 {i+1}/{len(files)}")

    conn = db.get_conn()
    ok = fail = 0
    try:
        with conn.cursor() as cur:
            for r in records:
                try:
                    cur.execute(_UPSERT_SQL, r)
                    conn.commit()
                    ok += 1
                except Exception as e:
                    conn.rollback()
                    fail += 1
                    if fail <= 5:
                        log.warning(f"插入失败 {r.get('ts_code')}: {e}")
    finally:
        db.put_conn(conn)

    log.info(
        f"extract_supplements 完成: high={stats['high']} mid={stats['mid']} "
        f"low={stats['low']} | 写入={ok} 失败={fail}"
    )
    return {"high": stats["high"], "mid": stats["mid"], "low": stats["low"],
            "ok": ok, "fail": fail}
