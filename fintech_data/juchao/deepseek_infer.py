"""juchao/deepseek_infer.py — DeepSeek 推理 → report_metrics + causal_edges（整合自 run_deepseek_v3.py）"""
from __future__ import annotations
import re
import time
import json
import threading
import psycopg2
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from .. import config, db, logger

log = logger.get("deepseek_infer")

_SYSTEM_PROMPT = """
你是一位专业的A股投资研究员，专注于从年报中发现三大报表无法直接读出的结构性问题。
你的任务不是复述数字，而是发现矛盾、识别风险、给出判断。
所有结论必须有原文数字支撑，不得泛泛而谈。
"""

_USER_PROMPT = """
请分析以下年报内容，按照严格格式输出两个部分。

### 第一部分：因果逻辑链
格式：**[驱动因素]** -> [结果标签]: 具体说明（必须含原文数字）
要求：6-8条，覆盖收入/利润/现金流/资产结构四个维度

### 第二部分：三维评级表格
| 维度 | 评级 | 核心依据 |
|------|------|----------|
| 利润可持续性 | A/B/C/D | ... |
| 财务数据可信度 | A/B/C/D | ... |
| 现金流风险 | 低/中/高 | ... |

---
年报内容：
{content}
"""


def _get_client() -> OpenAI:
    return OpenAI(
        api_key  = config.DEEPSEEK["api_key"],
        base_url = config.DEEPSEEK["base_url"],
    )


def _call_api(content: str) -> str:
    client = _get_client()
    resp   = client.chat.completions.create(
        model      = config.DEEPSEEK["model"],
        max_tokens = config.DEEPSEEK["max_tokens"],
        messages   = [
            {"role": "system",  "content": _SYSTEM_PROMPT},
            {"role": "user",    "content": _USER_PROMPT.format(content=content[:120_000])},
        ],
    )
    return resp.choices[0].message.content or ""


def _parse_causal_edges(text: str, ts_code: str, report_year: int) -> list[dict]:
    edges = []
    pattern = r"\*\*\[(.+?)\]\*\*\s*->\s*\[(.+?)\]:\s*(.+)"
    for m in re.finditer(pattern, text):
        source, target, desc = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        edges.append({
            "ts_code":     ts_code,
            "report_year": report_year,
            "source_node": source[:200],
            "target_node": target[:200],
            "description": desc[:500],
            "has_number":  bool(re.search(r"\d", desc)),
        })
    return edges


def _parse_rating(text: str, label: str) -> str | None:
    m = re.search(rf"\|\s*{label}\s*\|\s*(\S+)\s*\|", text)
    return m.group(1) if m else None


def _upsert_edges(conn, edges: list[dict]):
    if not edges:
        return
    with conn.cursor() as cur:
        for e in edges:
            cur.execute("""
                INSERT INTO causal_edges
                    (ts_code, report_year, source_node, target_node, description, has_number)
                VALUES
                    (%(ts_code)s, %(report_year)s, %(source_node)s,
                     %(target_node)s, %(description)s, %(has_number)s)
                ON CONFLICT (ts_code, report_year, source_node)
                DO UPDATE SET description = EXCLUDED.description,
                              has_number  = EXCLUDED.has_number
            """, e)
    conn.commit()


def _upsert_metrics(conn, ts_code: str, report_year: int, text: str):
    profit  = _parse_rating(text, "利润可持续性")
    credib  = _parse_rating(text, "财务数据可信度")
    cf_risk = _parse_rating(text, "现金流风险")
    if not any([profit, credib, cf_risk]):
        return
    code6  = ts_code[:6]
    market = "SH" if ts_code.endswith("SH") else "SZ"
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO report_metrics (code, market, ts_code, report_year,
                profit_sustainability, data_credibility, cashflow_risk)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                ts_code               = EXCLUDED.ts_code,
                report_year           = EXCLUDED.report_year,
                profit_sustainability = EXCLUDED.profit_sustainability,
                data_credibility      = EXCLUDED.data_credibility,
                cashflow_risk         = EXCLUDED.cashflow_risk
        """, (code6, market, ts_code, report_year, profit, credib, cf_risk))
    conn.commit()


def _find_md(ts_code: str, report_year: int) -> Path | None:
    for p in config.MD_DIR.glob(f"*{report_year}年年度报告.md"):
        if ts_code[:6] in p.stem or ts_code in p.stem:
            return p
    return None


def _get_pending(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.ts_code, a.report_year
            FROM annual_report_meta a
            LEFT JOIN report_metrics r ON a.ts_code = r.ts_code
            WHERE r.profit_sustainability IS NULL OR r.ts_code IS NULL
            ORDER BY a.ts_code
        """)
        return [{"ts_code": row[0], "report_year": row[1]} for row in cur.fetchall()]


_obsidian_lock = threading.Lock()


def _write_obsidian(ts_code: str, report_year: int, text: str):
    profit = _parse_rating(text, "利润可持续性") or "?"
    credib = _parse_rating(text, "财务数据可信度") or "?"
    cf     = _parse_rating(text, "现金流风险") or "?"
    block  = (
        f"\n---\n## DeepSeek分析（v3 · {report_year}年报）\n\n"
        f"| 维度 | 评级 |\n|------|------|\n"
        f"| 利润可持续性 | {profit} |\n"
        f"| 财务数据可信度 | {credib} |\n"
        f"| 现金流风险 | {cf} |\n"
    )
    marker = "## DeepSeek分析（v3"
    for obs_file in config.OBSIDIAN_DIR.glob(f"*{ts_code[:6]}*.md"):
        with _obsidian_lock:
            content = obs_file.read_text(encoding="utf-8")
            content = re.sub(rf"\n---\n{re.escape(marker)}.+", "", content, flags=re.DOTALL)
            obs_file.write_text(content.rstrip() + "\n" + block, encoding="utf-8")
        break


def _process_one(row: dict, dry_run: bool) -> str:
    ts_code     = row["ts_code"]
    report_year = row["report_year"]

    md_file = _find_md(ts_code, report_year)
    if not md_file:
        return "skipped"
    if dry_run:
        log.info(f"[DRY_RUN] {ts_code}")
        return "dry"

    conn = psycopg2.connect(**config.DB)
    try:
        content  = md_file.read_text(encoding="utf-8")
        raw_text = _call_api(content)
        edges    = _parse_causal_edges(raw_text, ts_code, report_year)

        _upsert_edges(conn, edges)
        _upsert_metrics(conn, ts_code, report_year, raw_text)
        _write_obsidian(ts_code, report_year, raw_text)

        log.info(f"[{ts_code}] 完成 | 因果链 {len(edges)} 条")
        time.sleep(config.DEEPSEEK["sleep_between"])
        return "success"
    except Exception as e:
        log.error(f"[{ts_code}] 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return "failed"
    finally:
        conn.close()


def run(dry_run: bool = False) -> dict:
    conn    = db.get_conn()
    pending = _get_pending(conn)
    db.put_conn(conn)
    log.info(f"deepseek_infer: 待处理 {len(pending)} 家")

    success = skipped = failed = 0
    workers = config.DEEPSEEK["workers"]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_process_one, dict(row), dry_run): row for row in pending}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result == "success":
                success += 1
            elif result == "skipped":
                skipped += 1
            else:
                failed += 1
            if i % 50 == 0 or i == len(pending):
                log.info(f"进度 {i}/{len(pending)} | 成功={success} 跳过={skipped} 失败={failed}")

    log.info(f"deepseek_infer 完成: 成功={success} 跳过={skipped} 失败={failed}")
    return {"success": success, "skipped": skipped, "failed": failed}
