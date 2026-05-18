#!/usr/bin/env python3
"""
create_obsidian_new.py
为还没有 Obsidian 文件的新公司：
  1. 创建带 YAML frontmatter 的骨架 MD 文件
  2. 从 report_metrics 里读取已有分析结果，写入 v3 分析块
不重调 DeepSeek API。
"""

import json
import re
import psycopg2
import psycopg2.extras
from pathlib import Path
from datetime import date

VAULT_DIR  = Path.home() / "Documents/Obsidian_Vault/02_Company_Analysis"
CACHE_FILE = VAULT_DIR / ".stock_cache.json"
DB = dict(host="localhost", port=5432, dbname="fintech_db",
          user="postgres", password="fintech123")

OBSIDIAN_MARKER = "## 🤖 DeepSeek分析（v3"


def safe_filename(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]', "_", s)


def obsidian_path(code: str, market: str, name: str) -> Path:
    return VAULT_DIR / f"{code}_{market}_{safe_filename(name)}.md"


def skeleton(code: str, market: str, name: str, industry: str) -> str:
    today = date.today().isoformat()
    return f"""---
code: "{code}"
name: "{name}"
market: "{market}"
industry: "{industry}"
tags:
  - 年报
  - {industry}
  - {market}
date_indexed: "{today}"
---
<!-- annual_report_linked -->

# {code}.{market} 深度透视
"""


def v3_block(m: dict) -> str:
    profit  = m.get("profit_sustainability") or "?"
    cred    = m.get("data_credibility")      or "?"
    cash    = m.get("cashflow_risk")         or "?"
    metric  = (m.get("key_metric") or "").strip()[:200]
    risk1   = (m.get("risk_1") or "").split("\n")[0][:100]
    return f"""
---
{OBSIDIAN_MARKER} · 2025年报）

| 维度 | 评级 |
|------|------|
| 利润可持续性 | {profit} |
| 财务数据可信度 | {cred} |
| 现金流风险 | {cash} |

**首要追踪指标：** {metric}

**核心风险：** {risk1}

> 完整分析见 PostgreSQL report_metrics 表
"""


def main():
    # 加载股票缓存
    with open(CACHE_FILE, encoding="utf-8") as f:
        cache = json.load(f)

    # 从 DB 读取所有已完成推理的公司
    conn = psycopg2.connect(**DB)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""
        SELECT ts_code, code, market, key_contradiction,
               profit_sustainability, data_credibility, cashflow_risk,
               key_metric, risk_1
        FROM report_metrics
        WHERE key_contradiction IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()

    created = updated = skipped = 0

    for row in rows:
        ts_code = row["ts_code"]
        if not ts_code:
            skipped += 1
            continue

        code6  = ts_code[:6]
        market = row["market"] or (ts_code.split(".")[-1] if "." in ts_code else "SH")
        info   = cache.get(code6, {})
        name   = info.get("name", code6)
        industry = info.get("industry", "其他")

        obs_path = obsidian_path(code6, market, name)

        # 若文件不存在，创建骨架
        if not obs_path.exists():
            obs_path.write_text(skeleton(code6, market, name, industry),
                                encoding="utf-8")
            created += 1

        # 写入/更新 v3 分析块
        content = obs_path.read_text(encoding="utf-8")
        block   = v3_block(dict(row))

        if OBSIDIAN_MARKER in content:
            content = re.sub(
                rf"\n---\n{re.escape(OBSIDIAN_MARKER)}.+",
                "", content, flags=re.DOTALL
            )
            updated += 1
        else:
            updated += 1

        obs_path.write_text(content.rstrip() + "\n" + block, encoding="utf-8")

        if (created + updated) % 500 == 0:
            print(f"  进度: 已创建 {created} | 已回写 {updated}")

    print(f"\n完成 | 新建文件: {created} | 回写分析块: {updated} | 跳过: {skipped}")


if __name__ == "__main__":
    main()
