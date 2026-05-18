#!/usr/bin/env python3
"""
从plumber转化的原始MD文件中提取第一等级附注字段
补充已有DeepSeek分析文件里缺失的数字

适用场景：
  - 已有3700份DeepSeek分析MD（第二、三等级数据）
  - 已有对应的plumber转化MD（原始年报文本）
  - 需要补充第一等级数字字段入 annual_report_supplements 表
"""

import re, json, os
from pathlib import Path
from collections import defaultdict

# ══════════════════════════════════════════
# 配置
# ══════════════════════════════════════════
PLUMBER_DIR  = "/home/liam-sun/上市公司年报_MD"
DEEPSEEK_DIR = "/home/liam-sun/Documents/Obsidian_Vault/02_Company_Analysis"
OUTPUT_JSON  = "/home/liam-sun/annual_reports/supplements.json"
STOCK_CACHE  = "/home/liam-sun/Documents/Obsidian_Vault/02_Company_Analysis/.stock_cache.json"
DB_WRITE     = True
# ══════════════════════════════════════════

# 构建 normalized_name → ts_code 映射
_NAME_TO_TSCODE: dict = {}

def _load_name_map():
    global _NAME_TO_TSCODE
    if _NAME_TO_TSCODE:
        return
    try:
        cache = json.loads(Path(STOCK_CACHE).read_text("utf-8"))
        for code, info in cache.items():
            name = re.sub(r"\s+", "", info.get("name", ""))
            market = info.get("market", "SH")
            _NAME_TO_TSCODE[name] = f"{code}.{market}"
    except Exception as e:
        print(f"  警告：无法加载股票缓存: {e}")


def ts_code_from_filename(path: Path) -> str:
    """从文件名解析 ts_code：先按中文名查股票缓存，再尝试正则匹配数字代码。"""
    _load_name_map()
    stem = path.stem  # e.g. "平安银行：2025年年度报告"
    # 提取冒号前的公司名
    cn_name = stem.split("：")[0].split(":")[0]
    normalized = re.sub(r"\s+", "", cn_name)
    if normalized in _NAME_TO_TSCODE:
        return _NAME_TO_TSCODE[normalized]
    # fallback: 数字代码格式
    m = re.compile(r'(\d{6})[-_\.]?(SH|SZ|BJ)', re.IGNORECASE).search(path.stem)
    if m:
        return f"{m.group(1)}.{m.group(2).upper()}"
    return f"UNKNOWN_{normalized[:10]}"


# ─── 正则模式 ─────────────────────────────

def _num(s):
    """字符串转数字，处理逗号、万、亿等单位"""
    if not s:
        return None
    s = s.replace(',', '').replace('，', '').strip()
    multiplier = 1
    if '亿' in s:
        multiplier = 1e8
        s = s.replace('亿', '')
    elif '万' in s:
        multiplier = 1e4
        s = s.replace('万', '')
    try:
        return float(s) * multiplier
    except:
        return None


def extract_contract_liabilities(text):
    """
    合同负债：寻找"合同负债"科目的期末/期初余额
    常见格式：
      | 预收经销商货款 | 4,120,582,373.62 | 4,319,562,511.03 |
      合同负债合计  4,128,488,829.61  4,335,313,046.53
    """
    result = {"end": None, "start": None}

    # 模式1：表格行，预收经销商货款或合同负债合计
    patterns = [
        r'预收经销商货款[^\d]*?([\d,]+\.?\d*)[^\d\n]+([\d,]+\.?\d*)',
        r'合同负债.*?合计[^\d]*?([\d,]+\.?\d*)[^\d\n]+([\d,]+\.?\d*)',
        r'合同负债\n.*?([\d,]+\.?\d*)\n.*?([\d,]+\.?\d*)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.MULTILINE)
        if m:
            result["end"]   = _num(m.group(1))
            result["start"] = _num(m.group(2))
            return result

    # 模式2：直接搜索科目行（资产负债表里）
    m = re.search(r'合同负债\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)', text)
    if m:
        result["end"]   = _num(m.group(1))
        result["start"] = _num(m.group(2))
    return result


def extract_construction_in_progress(text):
    """
    在建工程：期末余额 + 最大项目预算/进度
    """
    result = {
        "end": None, "start": None,
        "largest_name": None, "largest_budget": None,
        "largest_done_pct": None
    }

    # 资产负债表中的在建工程期末/期初
    m = re.search(r'在建工程\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)', text)
    if m:
        result["end"]   = _num(m.group(1))
        result["start"] = _num(m.group(2))

    # 在建工程明细表：找预算最大的项目
    # 典型格式：项目名称 | 账面余额 | ... | 预计总投 | 累计投入占预算比例
    budget_pattern = re.compile(
        r'([^\|\n]{4,30})\s*\|[^\|]*\|[^\|]*\|[^\|]*\|([\d,]+\.?\d+)[^\|]*\|'
        r'[^\|]*\|[^\|]*\|([\d.]+)%'
    )
    best_budget = 0
    for m in budget_pattern.finditer(text):
        budget = _num(m.group(2))
        if budget and budget > best_budget:
            best_budget = budget
            result["largest_name"]       = m.group(1).strip()
            result["largest_budget"]     = budget
            result["largest_done_pct"]   = float(m.group(3))

    return result


def extract_rd_info(text):
    """
    研发投入总额和资本化金额
    典型格式：
      研发投入金额（元）   9,576,440,840.12
      资本化研发投入占研发投入的比例  13.49%
    """
    result = {"total": None, "capitalized": None, "cap_rate": None}

    # 研发投入总额
    patterns_total = [
        r'研发投入(?:金额)?[（(][元][)）][^\d]*([\d,]+\.?\d+)',
        r'研发投入.*?([\d,]+\.?\d+).*?(?:元|亿|万)',
    ]
    for pat in patterns_total:
        m = re.search(pat, text)
        if m:
            result["total"] = _num(m.group(1))
            break

    # 资本化金额
    m = re.search(r'研发投入资本化(?:的)?金额[（(][元][)）][^\d]*([\d,]+\.?\d+)', text)
    if m:
        result["capitalized"] = _num(m.group(1))

    # 资本化率
    m = re.search(r'资本化研发投入占研发投入的比例[^\d]*([\d.]+)%', text)
    if m:
        result["cap_rate"] = float(m.group(1))
    elif result["total"] and result["capitalized"]:
        result["cap_rate"] = round(result["capitalized"] / result["total"] * 100, 2)

    return result


def extract_interest_capitalized(text):
    """
    本期利息资本化金额
    典型位置：在建工程明细表最后一列"本期利息资本化金额"的合计
    """
    patterns = [
        r'本期利息资本化金额[^\d]*([\d,]+\.?\d+)',
        r'利息资本化.*?合计[^\d]*([\d,]+\.?\d+)',
        r'资本化利息.*?([\d,]+\.?\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return _num(m.group(1))
    return None


def extract_customer_concentration(text):
    """
    前五大客户集中度
    典型格式：前五名客户合计 / 占年度销售总额比例 xx%
    """
    result = {"top5_pct": None, "top1_pct": None, "related_pct": None}

    # 前五名合计占比
    m = re.search(
        r'前五名客户.*?(?:合计|销售额)[^\d]*([\d.]+)%',
        text, re.DOTALL
    )
    if m:
        result["top5_pct"] = float(m.group(1))

    # 关联方占比（如北方导航）
    m = re.search(r'关联方.*?占.*?([\d.]+)%', text)
    if m:
        result["related_pct"] = float(m.group(1))

    return result


def extract_non_recurring(text):
    """
    非经常性损益合计
    """
    m = re.search(r'(?:非经常性损益)?合计[^\d\-]*([\-\d,]+\.?\d+)', text)
    if m:
        return _num(m.group(1))

    # 备选：找"合计 x.xx亿"格式
    m = re.search(r'非经常性损益.*?合计.*?([\d,]+\.?\d+)', text, re.DOTALL)
    if m:
        return _num(m.group(1))
    return None


def extract_goodwill(text):
    """商誉余额"""
    m = re.search(r'商誉\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)', text)
    if m:
        return {"end": _num(m.group(1)), "start": _num(m.group(2))}
    return {"end": None, "start": None}


def extract_bank_fields(text):
    """银行专用字段"""
    result = {
        "npl_ratio": None,
        "provision_coverage": None,
        "nim": None,
        "attention_ratio": None
    }
    patterns = {
        "npl_ratio":          r'不良贷款率[^\d]*([\d.]+)%',
        "provision_coverage": r'拨备覆盖率[^\d]*([\d.]+)%',
        "nim":                r'净息差[^\d]*([\d.]+)%',
        "attention_ratio":    r'关注类.*?占比[^\d]*([\d.]+)%',
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            result[key] = float(m.group(1))
    return result


# ─── 主提取函数 ────────────────────────────

def extract_from_plumber_md(path: Path) -> dict:
    """从单个plumber MD文件提取所有第一等级字段"""
    text = path.read_text("utf-8", errors="ignore")
    ts_code = ts_code_from_filename(path)

    cl = extract_contract_liabilities(text)
    ci = extract_construction_in_progress(text)
    rd = extract_rd_info(text)

    record = {
        "ts_code":              ts_code,
        "source":               "plumber",
        # 合同负债
        "contract_liab_end":    cl["end"],
        "contract_liab_start":  cl["start"],
        # 在建工程
        "construction_end":     ci["end"],
        "construction_start":   ci["start"],
        "largest_project_name": ci["largest_name"],
        "largest_project_budget": ci["largest_budget"],
        "largest_project_done": ci["largest_done_pct"],
        # 研发
        "rd_total":             rd["total"],
        "rd_capitalized":       rd["capitalized"],
        "rd_cap_rate":          rd["cap_rate"],
        # 利息资本化
        "interest_capitalized": extract_interest_capitalized(text),
        # 客户集中度
        **{f"customer_{k}": v
           for k, v in extract_customer_concentration(text).items()},
        # 非经常性损益
        "non_recurring_total":  extract_non_recurring(text),
        # 商誉
        "goodwill":             extract_goodwill(text)["end"],
        # 银行字段
        **extract_bank_fields(text),
    }

    # 统计缺失字段
    tier1 = ["contract_liab_end", "construction_end", "rd_total",
             "interest_capitalized", "non_recurring_total"]
    missing = [f for f in tier1 if record.get(f) is None]
    record["missing_fields"] = ",".join(missing)
    record["confidence"]     = (
        "high" if len(missing) == 0 else
        "mid"  if len(missing) <= 2 else "low"
    )

    return record


def batch_extract(plumber_dir: Path, output_path: Path):
    """批量处理所有plumber MD文件"""
    files = list(plumber_dir.glob("*.md"))
    print(f"发现 {len(files)} 个plumber MD文件")

    results = []
    conf_stats = defaultdict(int)

    for i, f in enumerate(files):
        r = extract_from_plumber_md(f)
        results.append(r)
        conf_stats[r["confidence"]] += 1
        if (i+1) % 200 == 0:
            print(f"  已处理 {i+1}/{len(files)}...")

    # 输出JSON
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), "utf-8"
    )
    print(f"\n提取完成:")
    print(f"  ✅ high: {conf_stats['high']}")
    print(f"  🔶 mid:  {conf_stats['mid']}")
    print(f"  ❌ low:  {conf_stats['low']}")
    print(f"  输出: {output_path}")

    if DB_WRITE:
        write_to_postgres(results)

    return results


def write_to_postgres(records):
    import psycopg2
    # 读取数据库配置（复用fintech_system配置）
    conn = psycopg2.connect(
        host="localhost", port=5432,
        dbname="fintech_db", user="postgres", password="fintech123"
    )
    cur = conn.cursor()

    upsert = """
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
      contract_liab_start=EXCLUDED.contract_liab_start,
      construction_end=EXCLUDED.construction_end,
      rd_total=EXCLUDED.rd_total, rd_cap_rate=EXCLUDED.rd_cap_rate,
      interest_capitalized=EXCLUDED.interest_capitalized,
      non_recurring_total=EXCLUDED.non_recurring_total,
      report_year=2025, updated_at=NOW();
    """
    ok, fail = 0, 0
    for r in records:
        try:
            cur.execute(upsert, r)
            conn.commit()
            ok += 1
        except Exception as e:
            conn.rollback()
            fail += 1
            if fail <= 10:
                print(f"  插入失败 {r.get('ts_code')}: {e}")
    cur.close(); conn.close()
    print(f"  ✅ 已写入PostgreSQL: {ok} 条（失败 {fail} 条）")


if __name__ == "__main__":
    plumber = Path(PLUMBER_DIR)
    output  = Path(OUTPUT_JSON)
    batch_extract(plumber, output)
