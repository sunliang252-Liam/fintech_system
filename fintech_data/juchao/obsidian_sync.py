"""juchao/obsidian_sync.py — 知识图谱同步（Obsidian 链接重建）"""
from __future__ import annotations
import json
import re
from pathlib import Path
from .. import config, db, logger

log = logger.get("obsidian_sync")


def _load_cache() -> dict:
    if not config.STOCK_CACHE.exists():
        return {}
    with config.STOCK_CACHE.open(encoding="utf-8") as f:
        return json.load(f)


def _refresh_cache(conn) -> dict:
    """从 stock_basic 重建 .stock_cache.json。"""
    with conn.cursor() as cur:
        cur.execute("SELECT ts_code, name, area, industry FROM stock_basic")
        rows = cur.fetchall()

    cache = {}
    for ts_code, name, area, industry in rows:
        code6  = ts_code[:6]
        market = "SH" if ts_code.endswith("SH") else "SZ"
        cache[code6] = {"name": name, "market": market, "area": area, "industry": industry}

    config.STOCK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    config.STOCK_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"stock_cache 已刷新: {len(cache)} 只")
    return cache


def _ensure_links(md_file: Path, ts_code: str, cache: dict) -> bool:
    """确保 Obsidian MD 文件里有 ts_code 标签和行业链接，返回是否修改。"""
    code6  = ts_code[:6]
    info   = cache.get(code6, {})
    if not info:
        return False

    content = md_file.read_text(encoding="utf-8")
    changed = False

    tag = f"#{code6}"
    if tag not in content:
        content = content.rstrip() + f"\n\n{tag}\n"
        changed = True

    industry = info.get("industry", "")
    if industry and f"[[{industry}]]" not in content:
        content = content.rstrip() + f"\n[[{industry}]]\n"
        changed = True

    if changed:
        md_file.write_text(content, encoding="utf-8")
    return changed


def run(refresh_cache: bool = False) -> dict:
    conn  = db.get_conn()
    cache = _refresh_cache(conn) if refresh_cache else _load_cache()
    db.put_conn(conn)

    updated = 0
    for md_file in config.OBSIDIAN_DIR.glob("*.md"):
        m = re.search(r"(\d{6})", md_file.stem)
        if not m:
            continue
        code6   = m.group(1)
        ts_code = code6 + (".SH" if code6.startswith(("6", "5", "9")) else ".SZ")
        if _ensure_links(md_file, ts_code, cache):
            updated += 1

    log.info(f"obsidian_sync 完成: {updated} 个文件已更新")
    return {"updated": updated}
