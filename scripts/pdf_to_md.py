#!/usr/bin/env python3
"""
pdf_to_md.py
将 missing_pdf.csv 里列出的公司对应 PDF 用 pdfplumber 转换为 MD 文件。

用法：
  python pdf_to_md.py                          # 默认读 ~/下载/missing_pdf.csv
  python pdf_to_md.py --input-list /path/to/missing.csv --workers 4
"""

import argparse
import csv
import json
import logging
import re
import os
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

import pdfplumber

# ─── 配置 ────────────────────────────────────────────────────────────────────
PDF_DIR      = Path.home() / "上市公司年报1"          # 新批次 PDF，命名：ts_code_2025.pdf
MD_DIR       = Path.home() / "上市公司年报_MD"
CACHE_FILE   = Path.home() / "Documents/Obsidian_Vault/02_Company_Analysis/.stock_cache.json"
LOG_FILE     = Path.home() / "annual_reports/logs/pdf_to_md.log"
MAX_CHARS    = 150_000   # 每份 PDF 最多提取字符数

# ─── 日志 ─────────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    """返回 {normalized_name: ts_code} 和 {code6: info} 两个映射。"""
    with open(CACHE_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    name_to_ts, code_to_info = {}, {}
    for code, info in raw.items():
        name_to_ts[re.sub(r"\s+", "", info["name"])] = f"{code}.{info['market']}"
        code_to_info[code] = info
    return name_to_ts, code_to_info


def find_pdf(ts_code: str, cn_name: str) -> Path | None:
    """在 PDF_DIR 里找对应的 PDF 文件。
    新批次命名格式：000004.SZ_2025.pdf（直接含 ts_code）。
    """
    # 优先精确匹配 ts_code
    exact = PDF_DIR / f"{ts_code}_2025.pdf"
    if exact.exists():
        return exact

    # 备选：按6位代码前缀模糊匹配
    code6 = ts_code[:6]
    for p in PDF_DIR.glob(f"{code6}*.pdf"):
        return p

    return None


def md_output_path(cn_name: str) -> Path:
    """生成 MD 输出路径，格式：公司名：2025年年度报告.md"""
    safe = re.sub(r'[\\/*?"<>|]', "_", cn_name)
    return MD_DIR / f"{safe}：2025年年度报告.md"


# ─── 提取函数（子进程） ───────────────────────────────────────────────────────

def _extract_worker(args: tuple) -> tuple[str, str]:
    """
    args = (ts_code, cn_name, pdf_path_str, md_path_str)
    返回 (ts_code, 'ok' | 'skip' | 'error: ...')
    """
    ts_code, cn_name, pdf_path_str, md_path_str = args
    pdf_path = Path(pdf_path_str)
    md_path  = Path(md_path_str)

    if md_path.exists():
        return ts_code, "skip"

    try:
        parts, total = [], 0
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
                    total += len(t)
                if total >= MAX_CHARS:
                    parts.append("\n[文档过长，后续内容已截断]")
                    break

        if not parts:
            return ts_code, "error: 提取内容为空"

        content = f"# {cn_name} 2025年年度报告\n\n" + "\n\n".join(parts)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(content, encoding="utf-8")
        return ts_code, "ok"

    except Exception as e:
        return ts_code, f"error: {e}"


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-list", default=str(Path.home() / "下载/missing_pdf.csv"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    name_to_ts, code_to_info = load_cache()

    # 读取 missing 名单
    with open(args.input_list, encoding="utf-8") as f:
        missing = list(csv.DictReader(f))
    log.info(f"missing 名单: {len(missing)} 家")

    # 构建任务列表
    tasks, no_pdf = [], []
    for row in missing:
        ts_code = row["ts_code"]
        cn_name = row["name"]
        md_path = md_output_path(cn_name)

        pdf = find_pdf(ts_code, cn_name)
        if not pdf:
            no_pdf.append(ts_code)
            continue

        tasks.append((ts_code, cn_name, str(pdf), str(md_path)))

    log.info(f"本地找到 PDF: {len(tasks)} 家 | 无 PDF: {len(no_pdf)} 家")
    if not tasks:
        log.info("没有可处理的任务，退出。")
        return

    # 并行提取
    ok = skip = fail = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_extract_worker, t): t[0] for t in tasks}
        for i, future in enumerate(as_completed(futures), 1):
            ts_code, result = future.result()
            if result == "ok":
                ok += 1
            elif result == "skip":
                skip += 1
            else:
                fail += 1
                log.warning(f"[{ts_code}] {result}")

            if i % 50 == 0 or i == len(tasks):
                log.info(f"进度 {i}/{len(tasks)} | 成功:{ok} 跳过:{skip} 失败:{fail}")

    log.info(f"完成 | 成功:{ok} 跳过:{skip} 失败:{fail} 无PDF:{len(no_pdf)}")
    if no_pdf:
        log.info(f"无 PDF 的公司（前20）: {no_pdf[:20]}")


if __name__ == "__main__":
    main()
