"""
run_deepseek_v3.py
==================
DeepSeek v3 批处理调用脚本

功能：
  1. 读取 plumber MD 文件
  2. 调用 DeepSeek API（使用 deepseek_prompt_v3.py 的 prompt）
  3. 解析输出，写入 PostgreSQL（report_metrics + causal_edges）
  4. 将分析结果追加回 Obsidian MD 文件

运行前配置：
  - 修改下方 CONFIG 区域的路径和数据库连接信息
  - DRY_RUN=True 时只打印，不写库、不改文件

运行方式：
  python run_deepseek_v3.py                  # 正式运行
  DRY_RUN=True python run_deepseek_v3.py     # 预览模式
"""

import os
import re
import time
import logging
import threading
import psycopg2
import psycopg2.extras
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI  # DeepSeek 兼容 OpenAI SDK

# ─── 配置区 ───────────────────────────────────────────────────────────────────

CONFIG = {
    # DeepSeek
    "api_key": os.getenv("DEEPSEEK_API_KEY", "sk-91e6c80c76ad465390a514c202a09fdc"),
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",

    # 文件路径
    "plumber_md_dir": "/home/liam-sun/上市公司年报_MD",
    "obsidian_vault_dir": "/home/liam-sun/Documents/Obsidian_Vault/02_Company_Analysis",
    "stock_cache": "/home/liam-sun/Documents/Obsidian_Vault/02_Company_Analysis/.stock_cache.json",

    # PostgreSQL
    "db": {
        "host": "localhost",
        "port": 5432,
        "user": "postgres",
        "password": "fintech123",
        "dbname": "fintech_db",
    },

    # 运行控制
    "dry_run": os.getenv("DRY_RUN", "False").lower() == "true",
    "sleep_between": 0.5,    # 每次 API 调用后等待秒数
    "max_tokens": 3000,       # 每次调用最大输出 token
    "skip_existing": True,    # True = 跳过 report_metrics 已有推理内容的公司
    "workers": 5,             # 并发线程数
}

# ─── Prompt（从 deepseek_prompt_v3.py 引入）──────────────────────────────────

SYSTEM_PROMPT = """
你是一位专业的A股投资研究员，专注于从年报中发现三大报表无法直接读出的结构性问题。
你的任务不是复述数字，而是发现矛盾、识别风险、给出判断。
所有结论必须有原文数字支撑，不得泛泛而谈。
"""

ANALYSIS_PROMPT = """
请分析以下年报内容，按照严格格式输出四个部分。

---

### 第一部分：因果逻辑链

格式：**[驱动因素]** -> [结果标签]: 具体说明（必须含原文数字）

要求：
- 6-8条，覆盖收入 / 利润 / 现金流 / 资产结构四个维度
- 每条必须包含具体数字，禁止纯定性描述
- 最后一条必须是：净利润与经营性现金流的关系判断
- 若存在季度利润严重集中（任一季度占全年超60%），必须单独列一条并标注风险

---

### 第二部分：风险警告

格式：⚠️ **风险标题（含关键数字）**
详细说明（2-3句，指出具体影响路径）

要求：
- 2-3条，按威胁程度从高到低排列
- 第一条必须是对未来12个月利润或现金流威胁最大的风险
- 必须有一条专门指出三大报表与附注之间的重大矛盾（若无，明确写"未发现重大矛盾"）

---

### 第三部分：分析师判断

**Q1 利润质量**
净利润与OCF的关系说明什么？扣非净利润占比是否正常？非经常性损益是否有异常项目？

**Q2 最大内部矛盾**
数据中最显著的一个自相矛盾之处是什么？

**Q3 资本支出真实规模**
结合在建工程、研发资本化、利息资本化，真实Capex是否被低估？

**Q4 首要追踪指标**
如果只能追踪一个指标判断未来12个月走势，应该追踪什么？为什么？

**Q5 行业补充**（非银行/特殊行业填"不适用"）
- 银行：拨备覆盖率趋势 + 关注类贷款占比 + NIM压缩幅度
- 重资产：在建工程转固节奏对折旧的影响
- 创新药：license-out收入确认节奏 + 合同负债递延金额

---

### 第四部分：综合评级

| 维度 | 评级（高/中/低） | 理由（一句话） |
|------|----------------|----------------|
| 利润可持续性 | ? | |
| 财务数据可信度 | ? | |
| 未来12个月现金流风险 | ? | |

---

年报内容如下：

{annual_report_content}
"""

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)


def get_db_conn():
    return psycopg2.connect(**CONFIG["db"])


def get_pending_files(conn) -> list[dict]:
    """
    返回需要处理的公司列表。
    skip_existing=True 时跳过 key_contradiction 和 cashflow_risk 均已填写的公司。
    """
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        if CONFIG["skip_existing"]:
            cur.execute("""
                SELECT DISTINCT s.ts_code, s.report_year
                FROM annual_report_supplements s
                LEFT JOIN report_metrics m
                  ON s.ts_code = m.ts_code AND s.report_year = m.report_year
                WHERE m.key_contradiction IS NULL
                   OR m.key_contradiction = ''
                   OR m.cashflow_risk IS NULL
                   OR m.cashflow_risk = '?'
                ORDER BY s.ts_code
            """)
        else:
            cur.execute("""
                SELECT DISTINCT ts_code, report_year
                FROM annual_report_supplements
                ORDER BY ts_code
            """)
        return cur.fetchall()


_PLUMBER_NAME_INDEX: dict[str, Path] | None = None

def _build_plumber_index() -> dict[str, Path]:
    """Build {normalized_company_name → path} index for plumber MD directory."""
    global _PLUMBER_NAME_INDEX
    if _PLUMBER_NAME_INDEX is not None:
        return _PLUMBER_NAME_INDEX
    idx = {}
    for p in Path(CONFIG["plumber_md_dir"]).glob("*.md"):
        # filename: "公司名：2025年年度报告.md"
        stem = p.stem  # "公司名：2025年年度报告"
        name_part = stem.split("：")[0]  # "公司名"
        normalized = re.sub(r"\s+", "", name_part)  # strip all whitespace
        idx[normalized] = p
    _PLUMBER_NAME_INDEX = idx
    return idx


def find_md_file(ts_code: str, report_year: int) -> Path | None:
    """在 plumber_md_dir 里找对应的 MD 文件，用股票缓存映射 ts_code → 公司名。"""
    import json
    code = ts_code[:6]
    try:
        cache = json.loads(Path(CONFIG["stock_cache"]).read_text("utf-8"))
        cn_name = cache.get(code, {}).get("name", "")
    except Exception:
        cn_name = ""

    if cn_name:
        idx = _build_plumber_index()
        normalized = re.sub(r"\s+", "", cn_name)
        if normalized in idx:
            return idx[normalized]

    # fallback: try glob by code prefix
    vault = Path(CONFIG["plumber_md_dir"])
    matches = list(vault.glob(f"*{code}*{report_year}*.md"))
    return matches[0] if matches else None


def find_obsidian_file(ts_code: str) -> Path | None:
    """在 Obsidian vault 里找对应的个股 MD 文件。"""
    vault = Path(CONFIG["obsidian_vault_dir"])
    patterns = [
        f"**/{ts_code[:6]}*.md",
        f"**/*{ts_code[:6]}*.md",
    ]
    for pattern in patterns:
        matches = list(vault.glob(pattern))
        if matches:
            return matches[0]
    return None


def call_deepseek(content: str) -> str:
    """调用 DeepSeek API，返回原始文本输出。"""
    client = OpenAI(api_key=CONFIG["api_key"], base_url=CONFIG["base_url"])
    prompt = ANALYSIS_PROMPT.replace("{annual_report_content}", content[:12000])  # 截断控制 token
    response = client.chat.completions.create(
        model=CONFIG["model"],
        max_tokens=CONFIG["max_tokens"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


# ─── 解析函数 ─────────────────────────────────────────────────────────────────

def parse_causal_edges(text: str, ts_code: str, report_year: int) -> list[dict]:
    """从第一部分（或全文）提取因果逻辑链。"""
    edges = []
    # 尝试从第一部分提取，失败则在全文搜索
    section = extract_section(text, "第一部分") or extract_section(text, "因果逻辑链") or text
    pattern = r"\*\*\[(.+?)\]\*\*\s*->\s*\[(.+?)\]:\s*(.+)"
    for m in re.finditer(pattern, section):
        detail = m.group(3).strip()
        edges.append({
            "ts_code": ts_code,
            "report_year": report_year,
            "source_node": m.group(1).strip()[:200],
            "target_node": m.group(2).strip()[:200],
            "description": detail[:500],
            "has_number": bool(re.search(r"\d", detail)),
        })
    return edges


def parse_report_metrics(text: str, ts_code: str, report_year: int) -> dict:
    """从第二、三、四部分提取 report_metrics 字段。"""
    # code and market derived from ts_code (e.g. "000001.SZ" → code="000001", market="SZ")
    parts = ts_code.split(".")
    metrics = {
        "ts_code": ts_code,
        "report_year": report_year,
        "code": parts[0] if parts else ts_code[:6],
        "market": parts[1] if len(parts) > 1 else "SH",
    }

    # 风险警告
    risk_section = extract_section(text, "第二部分")
    risks = re.findall(r"⚠️\s*\*\*(.+?)\*\*\n(.+?)(?=⚠️|\Z)", risk_section or "", re.DOTALL)
    for i, (title, detail) in enumerate(risks[:3], 1):
        metrics[f"risk_{i}"] = f"{title.strip()}\n{detail.strip()}"

    # 分析师判断
    for q_num, field in [("Q1", "profit_quality"), ("Q2", "key_contradiction"),
                          ("Q3", "capex_adj"), ("Q4", "key_metric"), ("Q5", "industry_supplement")]:
        pattern = rf"\*\*{q_num}[^\n]*\*\*\n(.+?)(?=\*\*Q|\Z)"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            metrics[field] = m.group(1).strip()[:500]

    # 综合评级（维度名称允许前缀，评级单元格允许 **高** 等粗体标记）
    for dimension, field in [("利润可持续性", "profit_sustainability"),
                              ("财务数据可信度", "data_credibility"),
                              ("现金流风险", "cashflow_risk")]:
        pattern = rf"\|[^|]*{re.escape(dimension)}[^|]*\|[^|]*([高中低])[^|]*\|"
        m = re.search(pattern, text)
        if m:
            metrics[field] = m.group(1).strip()

    # "?" 视为未提取到，置 None 避免写入脏数据
    if metrics.get("cashflow_risk") == "?":
        metrics["cashflow_risk"] = None

    return metrics


def extract_section(text: str, section_name: str) -> str | None:
    """提取指定部分的文本内容（兼容不同 Markdown 标题层级）。"""
    pattern = rf"#{1,4} {section_name}[^\n]*\n(.+?)(?=#{1,4} 第|$)"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def build_obsidian_block(text: str, report_year: int) -> str:
    """构建写回 Obsidian 的分析区块。"""
    # 提取评级
    ratings = {}
    for dimension, key in [("利润可持续性", "profit"), ("财务数据可信度", "credibility"), ("现金流风险", "cashflow")]:
        m = re.search(rf"\|\s*{dimension}\s*\|\s*(\S+)\s*\|", text)
        ratings[key] = m.group(1) if m else "?"

    # 提取首要追踪指标
    q4 = ""
    m = re.search(r"\*\*Q4[^\n]*\*\*\n(.+?)(?=\*\*Q5|\Z)", text, re.DOTALL)
    if m:
        q4 = m.group(1).strip()[:200]

    # 提取第一条风险
    risk1 = ""
    m = re.search(r"⚠️\s*\*\*(.+?)\*\*", text)
    if m:
        risk1 = m.group(1).strip()

    block = f"""
---
## 🤖 DeepSeek分析（v3 · {report_year}年报）

| 维度 | 评级 |
|------|------|
| 利润可持续性 | {ratings['profit']} |
| 财务数据可信度 | {ratings['credibility']} |
| 现金流风险 | {ratings['cashflow']} |

**首要追踪指标：** {q4}

**核心风险：** {risk1}

> 完整分析见 PostgreSQL report_metrics 表
"""
    return block


# ─── 数据库写入 ───────────────────────────────────────────────────────────────

def upsert_causal_edges(conn, edges: list[dict]):
    if not edges:
        return
    with conn.cursor() as cur:
        for e in edges:
            cur.execute("""
                INSERT INTO causal_edges (ts_code, report_year, source_node, target_node, description, has_number)
                VALUES (%(ts_code)s, %(report_year)s, %(source_node)s, %(target_node)s, %(description)s, %(has_number)s)
                ON CONFLICT (ts_code, report_year, source_node) DO UPDATE
                SET description = EXCLUDED.description, has_number = EXCLUDED.has_number
            """, e)
    conn.commit()


def upsert_report_metrics(conn, metrics: dict):
    # v3 analysis fields only (exclude identity fields from SET clause)
    _identity = {"ts_code", "report_year", "code", "market"}
    v3_fields = [k for k in metrics if k not in _identity]
    if not v3_fields:
        return
    # ON CONFLICT on primary key (code), update v3 fields + ts_code/report_year
    update_fields = ["ts_code", "report_year"] + v3_fields
    set_clause = ", ".join(f"{f} = EXCLUDED.{f}" for f in update_fields)
    all_fields = ["code", "market", "ts_code", "report_year"] + v3_fields
    placeholders = ", ".join(f"%({f})s" for f in all_fields)
    col_names = ", ".join(all_fields)
    with conn.cursor() as cur:
        cur.execute(f"""
            INSERT INTO report_metrics ({col_names})
            VALUES ({placeholders})
            ON CONFLICT (code) DO UPDATE SET {set_clause}
        """, metrics)
    conn.commit()


# ─── Obsidian 回写 ────────────────────────────────────────────────────────────

OBSIDIAN_MARKER = "## 🤖 DeepSeek分析（v3"

def write_back_to_obsidian(ts_code: str, report_year: int, block: str):
    """将分析块追加或替换到 Obsidian MD 文件末尾。"""
    obs_file = find_obsidian_file(ts_code)
    if not obs_file:
        log.warning(f"[Obsidian] 找不到 {ts_code} 的 MD 文件，跳过回写")
        return

    content = obs_file.read_text(encoding="utf-8")

    # 若已有 v3 分析块则替换，否则追加
    if OBSIDIAN_MARKER in content:
        # 删除旧块
        content = re.sub(
            rf"\n---\n{re.escape(OBSIDIAN_MARKER)}.+",
            "",
            content,
            flags=re.DOTALL
        )

    content = content.rstrip() + "\n" + block

    if CONFIG["dry_run"]:
        log.info(f"[DRY_RUN] 将写入 Obsidian: {obs_file.name}\n{block[:200]}...")
    else:
        obs_file.write_text(content, encoding="utf-8")
        log.info(f"[Obsidian] ✅ 已回写: {obs_file.name}")


# ─── 主流程 ───────────────────────────────────────────────────────────────────

_obsidian_lock = threading.Lock()  # Obsidian 文件写入锁

def process_one(row: dict) -> str:
    """处理单家公司，每个线程独立 DB 连接。返回状态字符串。"""
    ts_code = row["ts_code"]
    report_year = row["report_year"]

    md_file = find_md_file(ts_code, report_year)
    if not md_file:
        log.warning(f"[{ts_code}] 找不到 MD 文件，跳过")
        return "skipped"

    log.info(f"[{ts_code} {report_year}] 开始处理: {md_file.name}")

    if CONFIG["dry_run"]:
        log.info(f"[DRY_RUN] 将调用 DeepSeek API for {ts_code}")
        return "dry"

    conn = get_db_conn()
    try:
        content = md_file.read_text(encoding="utf-8")
        raw_output = call_deepseek(content)

        edges = parse_causal_edges(raw_output, ts_code, report_year)
        metrics = parse_report_metrics(raw_output, ts_code, report_year)
        obs_block = build_obsidian_block(raw_output, report_year)

        upsert_causal_edges(conn, edges)
        upsert_report_metrics(conn, metrics)

        with _obsidian_lock:
            write_back_to_obsidian(ts_code, report_year, obs_block)

        log.info(f"[{ts_code}] ✅ 完成 | 因果链:{len(edges)}条 | 评级:{metrics.get('profit_sustainability','?')}")
        time.sleep(CONFIG["sleep_between"])
        return "success"

    except Exception as e:
        log.error(f"[{ts_code}] ❌ 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return "failed"
    finally:
        conn.close()


def main():
    log.info(f"启动 run_deepseek_v3.py | DRY_RUN={CONFIG['dry_run']} | workers={CONFIG['workers']}")
    conn = get_db_conn()
    pending = get_pending_files(conn)
    conn.close()
    log.info(f"待处理公司数: {len(pending)}")

    success, skipped, failed = 0, 0, 0

    with ThreadPoolExecutor(max_workers=CONFIG["workers"]) as executor:
        futures = {executor.submit(process_one, dict(row)): row for row in pending}
        for future in as_completed(futures):
            result = future.result()
            if result == "success":
                success += 1
            elif result == "skipped":
                skipped += 1
            elif result == "failed":
                failed += 1
            # 每完成 50 家打印一次进度
            done = success + skipped + failed
            if done % 50 == 0:
                log.info(f"进度: {done}/{len(pending)} | 成功:{success} 跳过:{skipped} 失败:{failed}")

    log.info(f"完成 | 成功:{success} 跳过:{skipped} 失败:{failed}")


if __name__ == "__main__":
    main()
