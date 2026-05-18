"""juchao/pdf_to_md.py — PDF → MD 批量转换（整合自 scripts/pdf_to_md.py）"""
from __future__ import annotations
import re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from .. import config, logger

log = logger.get("pdf_to_md")

MAX_CHARS = 150_000


def _md_path(ts_code: str, cn_name: str) -> Path:
    safe = re.sub(r'[\\/*?"<>|]', "_", cn_name)
    return config.MD_DIR / f"{safe}：2025年年度报告.md"


def _find_pdf(ts_code: str) -> Path | None:
    exact = config.PDF_DIR / f"{ts_code}_2025.pdf"
    if exact.exists():
        return exact
    code6 = ts_code[:6]
    for p in config.PDF_DIR.glob(f"{code6}*.pdf"):
        return p
    return None


def _extract_worker(args: tuple) -> tuple[str, str]:
    ts_code, cn_name, pdf_str, md_str = args
    import pdfplumber

    md_path = Path(md_str)
    if md_path.exists():
        return ts_code, "skip"

    try:
        parts, total = [], 0
        with pdfplumber.open(pdf_str) as pdf:
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


def run(codes: list[tuple[str, str]], workers: int = 4) -> dict:
    """
    codes: [(ts_code, cn_name), ...]
    """
    config.MD_DIR.mkdir(parents=True, exist_ok=True)
    tasks, no_pdf = [], []

    for ts_code, cn_name in codes:
        pdf = _find_pdf(ts_code)
        if not pdf:
            no_pdf.append(ts_code)
            continue
        md = _md_path(ts_code, cn_name)
        tasks.append((ts_code, cn_name, str(pdf), str(md)))

    log.info(f"pdf_to_md: 找到 PDF {len(tasks)} 份，无 PDF {len(no_pdf)} 份")

    ok = skip = fail = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
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
            if i % 100 == 0 or i == len(tasks):
                log.info(f"进度 {i}/{len(tasks)} | ok={ok} skip={skip} fail={fail}")

    log.info(f"pdf_to_md 完成: ok={ok} skip={skip} fail={fail} no_pdf={len(no_pdf)}")
    return {"ok": ok, "skip": skip, "fail": fail, "no_pdf": len(no_pdf)}
