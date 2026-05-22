# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

**Python**: conda environment `fintech` (Python 3.11). Always prefix commands with `conda run -n fintech` or activate first.

**PYTHONPATH**: Must be set to the project root for intra-package imports:
```bash
PYTHONPATH=. conda run -n fintech python ...
# or within an activated env:
export PYTHONPATH=/home/liam-sun/fintech_system
```

**Environment variables**: Load before running any module that touches the DB or APIs:
```bash
set -a && source config/.env && set +a
```
Defaults (hardcoded fallbacks in `fintech_data/config.py`) work for local dev without `.env`.

**Database**: PostgreSQL 14 in Docker container `fintech_pg`, database `fintech_db`.
```bash
docker start fintech_pg          # start DB
docker stop fintech_pg           # stop DB
docker exec -it fintech_pg psql -U postgres -d fintech_db   # psql shell
```

**System check**: `./check_config.sh` — verifies Docker, conda env, Python imports, Ollama, GPU.

---

## Common Commands

```bash
# Daily market data (post-market, cron target)
conda run -n fintech python -m fintech_data.scheduler --daily

# Quarterly financials (run during earnings season)
conda run -n fintech python -m fintech_data.scheduler --quarterly

# Annual report full pipeline (download → PDF→MD → DeepSeek → Obsidian)
conda run -n fintech python -m fintech_data.scheduler --annual-report \
    --disclosure-index ~/fintech_system/all_disclosure_dates.csv

# Run a single daily module
conda run -n fintech python -m fintech_data.scheduler --only stock_hist
# other --only values: macro, index, lhb, quarterly, download, pdf_to_md, deepseek, obsidian

# DCF valuation (HS300, uses analysis_layer which still depends on data_layer)
cd /home/liam-sun/fintech_system && conda run -n fintech python analysis_layer/dcf_hs300_industry.py

# Quantitative analysis
conda run -n fintech python -m fintech_data.quant.vol_mktcap_analysis

# Export PostgreSQL data to qlib format
conda run -n fintech python -m fintech_data.quant.pg_to_qlib --qlib-dir ~/qlib_data --start 20200101
```

---

## Architecture

The system has three functional layers. **`fintech_data/`** is the canonical modern layer; `data_layer/` and `scripts/` are legacy holdovers.

### `fintech_data/` — Primary Data Layer

- **`config.py`**: Single config source. Reads env vars with hardcoded defaults. All modules import from here.
- **`db.py`**: Thread-safe psycopg2 connection pool (1–10 connections). `get_conn()` / `put_conn()` for manual lifecycle; `upsert(conn, table, rows, conflict_cols)` for all DB writes.
- **`logger.py`**: Factory `get("name")` returns a logger writing to both `~/annual_reports/logs/<name>.log` and stdout.
- **`scheduler.py`**: CLI entry point (`python -m fintech_data.scheduler`). Orchestrates all pipeline stages.

**`tushare/`** — Market data via Tushare Pro API (token in config):
- `client.py`: Singleton `get_pro()`. `ts_post()` is an HTTP fallback that bypasses the tushare SDK.
- `daily/`: Five modules (`stock_hist`, `macro`, `index`, `lhb`, `commodity`), each exposes `run()`.
- `quarterly/`: Three financials modules + `detector.py` which diffs `stock_basic` vs `income_statement` to find gaps.

**`juchao/`** — Annual report processing (cninfo.com.cn):
- Pipeline: `downloader` → `pdf_to_md` → `extract_supplements` → `deepseek_infer` → `obsidian_sync`
- `deepseek_infer.py`: 5-thread pool calling DeepSeek v3 API (openai-compatible). Writes to `report_metrics` (ratings + risk), `causal_edges` (causal chains), and appends a block to Obsidian MD files. Skips already-processed companies by default (`skip_existing=True`).
- `obsidian_sync.py`: Rebuilds industry hub files and the `00_Company_Index.md` three-level hierarchy using Tushare 申万三级 classification (not 东财, which is permanently disconnected).

**`quant/`** — Quantitative backtesting (added 2026-05-21):
- `bt_feed.py`: backtrader adapter. `PGFeed.from_pg(symbol, start)` loads from DB. Built-in strategies: `MACrossStrategy`, `VolSurgeStrategy`, `RSIStrategy`. Use `run_strategy()` / `compare_strategies()` for quick results.
- `backtest.py`: vectorbt layer. `run_ma_cross()`, `run_rsi_strategy()`, `run_portfolio()`, `grid_search_ma()` — all read from `stock_daily_hist`.
- `alpha_factory.py`: qlib factor computation (requires prior `pg_to_qlib.py` export).
- `pg_to_qlib.py`: Exports `stock_daily_hist` → qlib CSV provider. Code mapping: `600519.SH` → `SH600519`.

### `analysis_layer/` — Valuation Engine (Legacy, Still Active)

8-method DCF/valuation engine for HS300. Key file: `dcf_hs300_industry.py` (v2.3). Methods auto-selected by industry:
- `pb_roe`: banks, insurance, brokers, real estate, regulated power
- `dcf_capex`: heavy capex (auto, telecom, machinery)
- `dcf_cycle` / `dcf_cycle_soft`: cyclical/semi-cyclical industries
- `pe_consumer`: consumer monopolies (liquor, beer, dairy)
- `dcf_pharma` / `ps_biotech`: pharma and biotech
- `dcf_std`: default for stable industries

**Known issue**: `analysis_layer/` still imports from `data_layer/` (the old layer), not `fintech_data/`. Migration is a pending TODO.

### `data_layer/` — Legacy Data Access (Do Not Extend)

Used only by `analysis_layer/`. Provides `get_pro()` (LocalProAPI wrapping Tushare) and `get_choice()` (东方财富 Choice API — currently disconnected). New code should use `fintech_data/` instead.

---

## Key Data Facts

- **Primary market data table**: `stock_daily_hist` (~11.8M rows, 2014–present, 2.25 GB) — unadjusted prices.
- **ts_code format**: `XXXXXX.SH` / `XXXXXX.SZ` / `XXXXXX.BJ`. BJ stocks with prefix `920xxx` are stored correctly in `stock_basic.market = 'BJ'` but may have incorrect `.SZ` ts_code suffixes — always use `market` column, not ts_code suffix, to determine exchange.
- **Tushare rate limits**: `index_member` API is 200 calls/min; use `sleep=0.35s`.
- **DeepSeek**: Uses openai-compatible SDK pointed at `https://api.deepseek.com`. Model: `deepseek-chat`. Content truncated to 120,000 chars per annual report.
- **Obsidian stock cache**: `~/Documents/Obsidian_Vault/02_Company_Analysis/.stock_cache.json` — 5,513 company name/industry/market mappings. Rebuilt by `scripts/rebuild_stock_cache.py`.
- **Annual report MD files**: `~/上市公司年报_MD/{公司名}：2025年年度报告.md` — 5,599 files, max 150,000 chars each.

---

## Pending TODOs (from README/CHANGELOG)

- `analysis_layer/` needs migration to `fintech_data/` (currently uses legacy `data_layer/`)
- `pg_to_qlib.py` export not yet run — `alpha_factory.py` cannot be used until complete
- crontab for `--daily` not yet configured
- HS300 full valuation re-run pending (needs three-scenario columns + industry WACC)
- Cleanup `scripts/` files marked 🗑️ in README
