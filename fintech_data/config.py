"""fintech_data/config.py — 统一配置，所有模块从这里读"""
import os
from pathlib import Path

# ── 数据库 ────────────────────────────────────────────────────────────────────
DB = dict(
    host     = os.getenv("PG_HOST",     "localhost"),
    port     = int(os.getenv("PG_PORT", "5432")),
    dbname   = os.getenv("PG_DB",       "fintech_db"),
    user     = os.getenv("PG_USER",     "postgres"),
    password = os.getenv("PG_PASSWORD", "fintech123"),
)

# ── Tushare ───────────────────────────────────────────────────────────────────
TUSHARE_TOKEN = os.getenv(
    "TUSHARE_TOKEN",
    "291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a"
)

# ── DeepSeek ──────────────────────────────────────────────────────────────────
DEEPSEEK = dict(
    api_key  = os.getenv("DEEPSEEK_API_KEY", "sk-91e6c80c76ad465390a514c202a09fdc"),
    base_url = "https://api.deepseek.com",
    model    = "deepseek-chat",
    max_tokens   = 3000,
    workers      = 5,
    sleep_between = 0.5,
)

# ── 文件路径 ──────────────────────────────────────────────────────────────────
PDF_DIR     = Path(os.getenv("PDF_DIR",  str(Path.home() / "上市公司年报")))
MD_DIR      = Path(os.getenv("MD_DIR",   str(Path.home() / "上市公司年报_MD")))
LOG_DIR     = Path(os.getenv("LOG_DIR",  str(Path.home() / "annual_reports/logs")))
OBSIDIAN_DIR = Path(os.getenv("OBSIDIAN_DIR",
    str(Path.home() / "Documents/Obsidian_Vault/02_Company_Analysis")))
STOCK_CACHE = OBSIDIAN_DIR / ".stock_cache.json"

# ── 巨潮网 ────────────────────────────────────────────────────────────────────
JUCHAO = dict(
    base_url   = "http://www.cninfo.com.cn",
    static_url = "http://static.cninfo.com.cn",
    timeout    = 30,
    delay      = 1.0,
)

# ── 历史起始日期（stock_daily_hist）────────────────────────────────────────────
HIST_START_DATE = "20140101"
