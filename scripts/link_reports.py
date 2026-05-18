#!/usr/bin/env python3
"""
年报知识库联网工具 v2
─────────────────────────────────────────────────────────────
解决问题：3700+ 个孤立 MD 文件，建立行业分类 + 双向链接网络

执行后产生的效果：
  1. 每个公司文件 头部 追加 YAML frontmatter（行业/代码/公司名/标签）
  2. 每个公司文件 尾部 追加「同行业公司」链接列表
  3. 生成 00_Company_Index.md（行业分组 + 每家公司的 wiki-link）
  4. 为每个行业生成独立的 行业_XXX.md 枢纽文件

Obsidian 图谱效果：
  00_Company_Index → 行业_银行 → 000001_SZ_深发展
                                ↕ (同行业互链)
                               000002_SZ_万科A
─────────────────────────────────────────────────────────────
"""

import os, re, json, time
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ══════════════════════════════════════════
#  配置区  ← 只需修改这里
# ══════════════════════════════════════════
VAULT_DIR    = "/home/liam-sun/Documents/Obsidian_Vault/02_Company_Analysis"
DRY_RUN      = False   # True=预览, False=真正写文件
USE_CACHE    = True    # 优先使用本地缓存（避免重复网络请求）
MAX_PEERS    = 10      # 每个公司文件底部，最多列出几个同行业伙伴
# ══════════════════════════════════════════


# ─── 工具函数 ─────────────────────────────

def safe_name(s: str) -> str:
    """去掉文件名非法字符"""
    return re.sub(r'[\\/:*?"<>|\s]', "_", s)


def log(msg, level="INFO"):
    icons = {"INFO": "  ", "OK": "✅", "SKIP": "⏭ ", "WARN": "⚠️ ", "ERR": "❌"}
    print(f"{icons.get(level, '  ')} {msg}")


# ─── Step 0: 获取股票基础信息 ─────────────────

def fetch_stock_info(vault: Path) -> dict:
    """
    返回 { "000001": {"name": "深发展", "industry": "银行", "market": "SZ"}, ... }
    优先读缓存，否则从 AKShare 获取
    """
    cache_path = vault / ".stock_cache.json"

    if USE_CACHE and cache_path.exists():
        log(f"读取本地缓存: {cache_path}")
        return json.loads(cache_path.read_text("utf-8"))

    try:
        import akshare as ak
    except ImportError:
        print("请先安装: pip install akshare")
        raise

    log("从 AKShare 获取股票名称列表...")
    df = ak.stock_info_a_code_name()   # code, name
    result = {}
    for _, row in df.iterrows():
        code = str(row["code"]).zfill(6)
        # 判断市场
        market = "SH" if code.startswith(("60", "68", "900")) else \
                 "BJ" if code.startswith(("43", "83", "87", "92")) else "SZ"
        result[code] = {"name": row["name"], "industry": "未分类", "market": market}

    # 获取行业分类（东财行业，整体一次拿到，最快）
    log("获取行业分类（东财）...")
    try:
        df_ind = ak.stock_individual_info_em   # 这个按股票查，太慢
        # 改用：申万行业指数成分（批量）
        # 实际最快方案：stock_board_industry_name_em 列出行业，再逐个拿成分
        df_boards = ak.stock_board_industry_name_em()
        total = len(df_boards)
        for i, row in df_boards.iterrows():
            ind_name = row["板块名称"]
            try:
                df_cons = ak.stock_board_industry_cons_em(symbol=ind_name)
                for code in df_cons["代码"].astype(str).str.zfill(6):
                    if code in result:
                        result[code]["industry"] = ind_name
                if i % 10 == 0:
                    log(f"行业进度 {i}/{total}: {ind_name}")
                time.sleep(0.15)
            except Exception as e:
                log(f"跳过行业 {ind_name}: {e}", "WARN")
    except Exception as e:
        log(f"行业分类获取失败: {e}", "WARN")

    # 写缓存
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    log(f"缓存已保存: {cache_path}", "OK")
    return result


# ─── Step 1: 扫描现有文件 ─────────────────────

FNAME_RE = re.compile(r"^(\d{6})_(SZ|SH|BJ)(?:_(.+))?\.md$")

def scan_files(vault: Path) -> list:
    """扫描 vault，解析所有年报 MD"""
    files = []
    for f in sorted(vault.glob("*.md")):
        if f.name.startswith("0_") or f.name.startswith("00_") \
           or f.name.startswith("行业_"):
            continue
        m = FNAME_RE.match(f.name)
        if m:
            files.append({
                "path":    f,
                "code":    m.group(1),
                "market":  m.group(2),
                "cn_name": m.group(3),   # 已有中文名（可能 None）
            })
    return files


# ─── Step 2: 为每个公司文件加 frontmatter + 同行链接 ────

FRONTMATTER_MARKER = "<!-- annual_report_linked -->"   # 防止重复写入

def patch_company_file(finfo: dict, info: dict, peers: list, dry_run: bool):
    """
    在公司 MD 文件头部插入 YAML frontmatter，尾部插入同行链接。
    info  = {"name":..., "industry":..., "market":...}
    peers = [{"code":..., "stem":..., "name":...}, ...]  同行业其他公司
    """
    path: Path = finfo["path"]
    original = path.read_text("utf-8")

    # 已经处理过，跳过
    if FRONTMATTER_MARKER in original:
        return False

    code     = finfo["code"]
    name     = info.get("name", finfo["cn_name"] or code)
    industry = info.get("industry", "未分类")
    market   = finfo["market"]

    # ── 构建 stem（用于链接目标名）──
    stem = f"{code}_{market}_{safe_name(name)}"

    # ── YAML frontmatter ──
    frontmatter = f"""---
code: "{code}"
name: "{name}"
market: "{market}"
industry: "{industry}"
tags:
  - 年报
  - {industry}
  - {market}
date_indexed: "{datetime.now().strftime('%Y-%m-%d')}"
---
{FRONTMATTER_MARKER}

"""

    # ── 同行业链接（底部）──
    peer_links = "\n".join(
        f"- [[{p['stem']}|{p['name']}]]"
        for p in peers[:MAX_PEERS]
        if p["code"] != code
    )
    related_section = f"""

---
## 🏭 同行业公司（{industry}）

> [[行业_{safe_name(industry)}|{industry} 行业总览]]

{peer_links}
"""

    new_content = frontmatter + original.rstrip() + related_section

    if dry_run:
        return True   # 只统计，不写
    else:
        path.write_text(new_content, "utf-8")
        return True


# ─── Step 3: 构建申万层级映射 ────────────────────

def build_sw_hierarchy() -> dict:
    """
    返回 { L3名称: {"l2": L2名称, "l1": L1名称} }
    从 AKShare 获取申万行业三级层级关系。失败时返回空字典（退化为平铺结构）。
    """
    try:
        import akshare as ak
        df3 = ak.sw_index_third_info()
        df2 = ak.sw_index_second_info()
        l2_to_l1 = dict(zip(df2["行业名称"], df2["上级行业"]))
        result = {}
        for _, row in df3.iterrows():
            l3 = row["行业名称"]
            l2 = row["上级行业"]
            result[l3] = {"l2": l2, "l1": l2_to_l1.get(l2, "其他")}
        log(f"申万层级加载完毕: {len(result)} 个三级行业", "OK")
        return result
    except Exception as e:
        log(f"申万层级获取失败，使用平铺结构: {e}", "WARN")
        return {}


def classify_unclassified(industry_dict: dict, stock_info: dict) -> dict:
    """
    对"未分类"公司，尝试从 PostgreSQL stock_basic（Tushare 110个行业）补充分类。
    将结果写回 industry_dict，返回修改后的 dict。
    """
    unclassified = industry_dict.get("未分类", [])
    if not unclassified:
        return industry_dict

    try:
        import psycopg2
        conn = psycopg2.connect(host="localhost", port=5432, dbname="fintech_db",
                                user="postgres", password="fintech123")
        cur = conn.cursor()
        codes = [s["code"] for s in unclassified]
        placeholders = ",".join(["%s"] * len(codes))
        cur.execute(f"SELECT symbol, industry FROM stock_basic WHERE symbol IN ({placeholders})", codes)
        db_map = {row[0]: row[1] for row in cur.fetchall() if row[1]}
        cur.close(); conn.close()

        still_unclassified = []
        for s in unclassified:
            db_ind = db_map.get(s["code"])
            if db_ind:
                new_ind = f"[Tushare]{db_ind}"
                industry_dict[new_ind].append(s)
            else:
                still_unclassified.append(s)

        industry_dict["未分类"] = still_unclassified
        if not still_unclassified:
            del industry_dict["未分类"]
        rescued = len(unclassified) - len(still_unclassified)
        log(f"未分类补救: {rescued} 家从数据库补充，剩余 {len(still_unclassified)} 家", "OK")
    except Exception as e:
        log(f"数据库补充分类失败: {e}", "WARN")

    return industry_dict


# ─── Step 4: 生成行业枢纽文件 ────────────────────

def write_industry_hub(vault: Path, industry: str, stocks: list, dry_run: bool):
    """生成 行业_银行.md 这样的枢纽文件，公司名带 wiki-link"""
    ind_safe = safe_name(industry)
    path = vault / f"行业_{ind_safe}.md"

    lines = [
        f"# {industry}",
        "",
        f"> [[00_Company_Index|← 返回总索引]]  |  共 **{len(stocks)}** 家公司",
        "",
        "## 成分公司",
        "",
        "| 代码 | 公司名称 | 市场 |",
        "|------|----------|------|",
    ]
    for s in stocks:
        lines.append(
            f"| {s['code']} | [[{s['stem']}|{s['name']}]] | {s['market']} |"
        )

    content = "\n".join(lines) + "\n"

    if not dry_run:
        path.write_text(content, "utf-8")
    log(f"行业文件: {path.name} ({len(stocks)} 家)", "OK" if not dry_run else "SKIP")


# ─── Step 5: 生成总索引（三级层级结构） ──────────────

def write_master_index(vault: Path, industry_dict: dict, total: int,
                       hierarchy: dict, dry_run: bool):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 按申万三级层级分组: l1 → l2 → [l3_name, ...]
    from collections import OrderedDict
    l1_l2_l3 = defaultdict(lambda: defaultdict(list))
    no_hierarchy = {}   # 没有层级信息的行业（Tushare补充 or 未分类）

    for ind in industry_dict:
        if ind in hierarchy:
            h = hierarchy[ind]
            l1_l2_l3[h["l1"]][h["l2"]].append(ind)
        else:
            no_hierarchy[ind] = industry_dict[ind]

    # L1 内按公司总数降序排列
    l1_sorted = sorted(l1_l2_l3.keys(),
                       key=lambda l1: sum(len(industry_dict.get(l3, []))
                                          for l2s in l1_l2_l3[l1].values()
                                          for l3 in l2s),
                       reverse=True)

    n_industries = len(industry_dict)
    lines = [
        "---",
        "tags: [索引, 年报数据库]",
        "---",
        "",
        "# 📚 上市公司年报知识库索引",
        "",
        f"> 自动生成 · {now} · **{total}** 家公司 · **{n_industries}** 个行业",
        "",
        "## 一级行业导航",
        "",
    ]

    # 顶部快速导航：只列一级行业，锚点与正文标题完全一致
    for l1 in l1_sorted:
        cnt = sum(len(industry_dict.get(l3, []))
                  for l2s in l1_l2_l3[l1].values() for l3 in l2s)
        heading = f"{l1}（{cnt}家）"
        lines.append(f"- [[#{heading}|{heading}]]")
    if no_hierarchy:
        cnt = sum(len(v) for v in no_hierarchy.values())
        heading = f"其他分类（{cnt}家）"
        lines.append(f"- [[#{heading}|{heading}]]")

    lines += ["", "---", ""]

    # 正文：一级 → 二级 → 三级 → 公司列表
    for l1 in l1_sorted:
        l1_total = sum(len(industry_dict.get(l3, []))
                       for l2s in l1_l2_l3[l1].values() for l3 in l2s)
        lines.append(f"## {l1}（{l1_total}家）")
        lines.append("")

        for l2 in sorted(l1_l2_l3[l1].keys(),
                         key=lambda x: sum(len(industry_dict.get(l3, []))
                                           for l3 in l1_l2_l3[l1][x]),
                         reverse=True):
            l2_total = sum(len(industry_dict.get(l3, [])) for l3 in l1_l2_l3[l1][l2])
            lines.append(f"### {l2}（{l2_total}家）")
            lines.append("")

            for l3 in sorted(l1_l2_l3[l1][l2],
                              key=lambda x: len(industry_dict.get(x, [])),
                              reverse=True):
                stocks = industry_dict.get(l3, [])
                if not stocks:
                    continue
                ind_safe = safe_name(l3)
                lines.append(f"#### [[行业_{ind_safe}|{l3}]]（{len(stocks)}家）")
                lines.append("")
                row = []
                for s in stocks:
                    row.append(f"[[{s['stem']}|{s['name']}]]")
                    if len(row) == 5:
                        lines.append(" · ".join(row))
                        row = []
                if row:
                    lines.append(" · ".join(row))
                lines.append("")

    # 末尾：无层级行业（Tushare补充 + 未分类）
    if no_hierarchy:
        no_total = sum(len(v) for v in no_hierarchy.values())
        lines.append(f"## 其他分类（{no_total}家）")
        lines.append("")
        lines.append("> 以下公司未收录于申万三级体系，以Tushare行业或未分类标注。")
        lines.append("")
        for ind, stocks in sorted(no_hierarchy.items()):
            ind_safe = safe_name(ind)
            lines.append(f"### [[行业_{ind_safe}|{ind}]]（{len(stocks)}家）")
            lines.append("")
            row = []
            for s in stocks:
                row.append(f"[[{s['stem']}|{s['name']}]]")
                if len(row) == 5:
                    lines.append(" · ".join(row))
                    row = []
            if row:
                lines.append(" · ".join(row))
            lines.append("")

    content = "\n".join(lines)
    path = vault / "00_Company_Index.md"

    if not dry_run:
        path.write_text(content, "utf-8")
    log(f"总索引: {path.name} ({len(lines)} 行)", "OK" if not dry_run else "SKIP")


# ══════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════

def main():
    vault = Path(VAULT_DIR).expanduser().resolve()
    assert vault.exists(), f"路径不存在: {vault}"

    print(f"\n{'='*55}")
    print(f"  年报知识库联网工具")
    print(f"  Vault: {vault}")
    print(f"  模式:  {'🔍 预览（DRY RUN）' if DRY_RUN else '⚡ 执行写入'}")
    print(f"{'='*55}\n")

    # Step 0: 获取股票数据
    stock_info = fetch_stock_info(vault)
    log(f"股票信息加载完毕，共 {len(stock_info)} 条")

    # Step 1: 扫描文件
    files = scan_files(vault)
    log(f"发现年报文件: {len(files)} 个")

    # Step 2: 构建行业分组 + stem 映射
    industry_dict = defaultdict(list)   # industry → list of stock dicts
    for f in files:
        code = f["code"]
        info = stock_info.get(code, {})
        name     = info.get("name") or f["cn_name"] or code
        industry = info.get("industry", "未分类")
        market   = info.get("market") or f["market"]
        stem     = f"{code}_{market}_{safe_name(name)}"
        industry_dict[industry].append({
            "code": code, "name": name,
            "market": market, "stem": stem,
            "path": f["path"],
        })

    # 行业内按代码排序
    for ind in industry_dict:
        industry_dict[ind].sort(key=lambda x: x["code"])

    # Step 3: patch 每个公司文件
    print(f"\n── 阶段1: 为 {len(files)} 个公司文件添加链接 ──")
    patched, skipped = 0, 0
    for ind, stocks in industry_dict.items():
        for s in stocks:
            finfo = next(f for f in files if f["code"] == s["code"])
            info  = stock_info.get(s["code"], {})
            peers = stocks   # 同行业全部公司作为 peers
            ok = patch_company_file(finfo, info, peers, dry_run=DRY_RUN)
            if ok: patched += 1
            else:  skipped += 1
    log(f"已处理: {patched}  跳过（已有）: {skipped}", "OK")

    # Step 2.5: 申万层级 + 未分类补救
    hierarchy = build_sw_hierarchy()
    industry_dict = classify_unclassified(industry_dict, stock_info)

    # Step 4: 行业枢纽文件
    print(f"\n── 阶段2: 生成 {len(industry_dict)} 个行业枢纽文件 ──")
    for ind, stocks in sorted(industry_dict.items()):
        write_industry_hub(vault, ind, stocks, dry_run=DRY_RUN)

    # Step 5: 总索引
    print(f"\n── 阶段3: 更新总索引 ──")
    write_master_index(vault, industry_dict, len(files), hierarchy, dry_run=DRY_RUN)

    # 汇总
    print(f"\n{'='*55}")
    if DRY_RUN:
        print(f"  预览完成。确认结果后将 DRY_RUN 改为 False 再次运行。")
    else:
        print(f"  ✅ 全部完成！")
        print(f"     · 公司文件已加链接: {patched} 个")
        print(f"     · 行业枢纽文件: {len(industry_dict)} 个")
        print(f"     · 总索引: 00_Company_Index.md")
        print(f"  Obsidian 打开后，图谱视图即可看到完整连接网络")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
