"""
patch_risk_fields.py
从 Obsidian 文件的"风险警告"段落提取 risk_1/2/3，
补全 report_metrics 里缺失的风险字段，不重调 DeepSeek API。
"""

import re
import json
import psycopg2
from pathlib import Path

VAULT_DIR  = Path("/home/liam-sun/Documents/Obsidian_Vault/02_Company_Analysis")
CACHE_FILE = VAULT_DIR / ".stock_cache.json"
DB = dict(host="localhost", port=5432, dbname="fintech_db",
          user="postgres", password="fintech123")

# 风险段落正则：匹配 **标题** 正文，无需 ⚠️
RISK_PAT = re.compile(
    r'\*\*([^\n*]{5,120}?)\*\*[。：\s]*([^\n*][^*]{20,}?)(?=\n\n|\n\*\*|---|\Z)',
    re.DOTALL
)

def find_obsidian_file(ts_code: str) -> Path | None:
    code = ts_code[:6]
    matches = list(VAULT_DIR.glob(f"{code}_*.md"))
    return matches[0] if matches else None

def extract_risks(path: Path) -> list[str]:
    text = path.read_text("utf-8", errors="ignore")
    # 截取"风险警告"到下一个二级标题之间的内容
    m = re.search(r'## 风险警告\n(.+?)(?=\n## |\Z)', text, re.DOTALL)
    if not m:
        return []
    section = m.group(1)
    risks = []
    for title, detail in RISK_PAT.findall(section):
        combined = f"{title.strip()}\n{detail.strip()}"
        risks.append(combined[:800])
        if len(risks) == 3:
            break
    return risks

def main():
    conn = psycopg2.connect(**DB)
    cur  = conn.cursor()

    # 只处理 risk_1 为空的行（且已有 key_contradiction，说明 v3 跑过）
    cur.execute("""
        SELECT ts_code FROM report_metrics
        WHERE key_contradiction IS NOT NULL
          AND (risk_1 IS NULL OR risk_1 = '')
        ORDER BY ts_code
    """)
    rows = [r[0] for r in cur.fetchall()]
    print(f"待补全 risk_1 的公司: {len(rows)} 家")

    ok = fail = skip = 0
    for ts_code in rows:
        obs = find_obsidian_file(ts_code)
        if not obs:
            skip += 1
            continue

        risks = extract_risks(obs)
        if not risks:
            skip += 1
            continue

        update = {f"risk_{i+1}": risks[i] if i < len(risks) else None
                  for i in range(3)}
        cur.execute("""
            UPDATE report_metrics
            SET risk_1 = %(risk_1)s,
                risk_2 = %(risk_2)s,
                risk_3 = %(risk_3)s
            WHERE ts_code = %(ts_code)s
        """, {**update, "ts_code": ts_code})
        conn.commit()
        ok += 1
        if ok % 200 == 0:
            print(f"  进度: {ok}/{len(rows)}")

    cur.close(); conn.close()
    print(f"完成 | 已补全:{ok}  跳过:{skip}  失败:{fail}")

if __name__ == "__main__":
    main()
