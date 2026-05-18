#!/usr/bin/env python3
"""
将 Obsidian vault 中的公司分析文件从 000001_SZ.md 重命名为 000001_SZ_平安银行.md
使用 .stock_cache.json 中的公司名称
"""

import re, json
from pathlib import Path

VAULT_DIR   = Path("/home/liam-sun/Documents/Obsidian_Vault/02_Company_Analysis")
CACHE_FILE  = VAULT_DIR / ".stock_cache.json"
FNAME_RE    = re.compile(r"^(\d{6})_(SZ|SH|BJ)\.md$")

def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]', "_", s)

def main():
    cache = json.loads(CACHE_FILE.read_text("utf-8"))
    # 建立 code → name 映射
    code_name = {code: info["name"] for code, info in cache.items()}

    files = [f for f in VAULT_DIR.glob("*.md") if FNAME_RE.match(f.name)]
    print(f"待重命名文件: {len(files)} 个\n")

    ok, skip, fail = 0, 0, 0
    for f in sorted(files):
        m = FNAME_RE.match(f.name)
        code, market = m.group(1), m.group(2)
        name = code_name.get(code)
        if not name:
            print(f"  ⚠️  找不到公司名: {f.name}")
            fail += 1
            continue

        new_name = f"{code}_{market}_{safe_name(name)}.md"
        new_path = VAULT_DIR / new_name

        if new_path.exists():
            skip += 1
            continue

        f.rename(new_path)
        ok += 1

    print(f"重命名完成: {ok} 个 | 已存在跳过: {skip} 个 | 找不到名称: {fail} 个")

if __name__ == "__main__":
    main()
