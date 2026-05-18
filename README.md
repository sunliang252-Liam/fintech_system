# Fintech System

A 股数据采集、财报分析与量化估值系统。数据存储于 Docker 容器 `fintech_pg`（PostgreSQL 14，数据库 `fintech_db`）。

---

## 系统架构

```
fintech_system/          ← 旧版代码库（部分已迁移至 fintech_data/）
fintech_data/            ← 新版数据层（统一入口，正在建设）
```

---

## 数据库概览（fintech_db，共 29 张表，约 2.4 GB）

| 表名 | 行数 | 说明 |
|------|------|------|
| stock_daily_hist | 1180 万 | A股历史日线（2014至今），主表 |
| balance_sheet | ~5万 | 资产负债表（153列） |
| income_statement | ~5万 | 利润表（86列） |
| cash_flow_statement | ~5万 | 现金流量表（98列） |
| report_metrics | ~5000 | 年报综合指标（29列，DeepSeek推理结果） |
| causal_edges | 15335 | 年报因果逻辑链（LLM从年报提取） |
| stock_lhb_branches_3m | ~4万 | 龙虎榜营业部 |
| stock_top_list | ~4000 | 龙虎榜主表 |
| stock_top_inst | 660 | 机构席位 |
| stock_basic | 5512 | 股票基本信息 |
| annual_report_meta | 1 | 年报PDF元数据 |
| annual_report_supplements | 5356 | 年报补充数字字段 |
| statement_details | 4567 | 财务明细（规则抽取） |
| index_daily_data | 542 | 指数日线 |
| hs300_history | - | 沪深300历史行情 |
| index_components | - | 指数成分股 |
| index_info | - | 指数基本信息 |
| macro_shibor | - | SHIBOR利率 |
| macro_futures | - | 国内期货日线 |
| macro_global | - | 全球指数现货 |
| spot_proxy_daily | - | 现货代理日数据 |
| spot_data_final | - | 现货数据 |
| spot_finance_shibor | - | 现货+SHIBOR合并 |
| financials | - | 综合财务数据 |
| commodity_radar | - | 商品雷达 |
| top_customers | - | 前五大客户 |
| top_suppliers | - | 前五大供应商 |
| causal_edges | - | 见上 |
| test_stock_spot | - | 测试表，待清理 |

---

## 新版数据层 `fintech_data/`（主力，建设中）

```
fintech_data/
├── config.py            # 统一配置（DB/Token/路径，读环境变量）
├── db.py                # 连接池 + upsert
├── logger.py            # 日志工厂
├── scheduler.py         # CLI 主入口
├── tushare/
│   ├── client.py        # Tushare API 单例
│   ├── daily/
│   │   ├── stock_hist.py   # stock_daily_hist 增量（按交易日）
│   │   ├── macro.py        # SHIBOR/期货/全球指数
│   │   ├── index.py        # 6大指数日线 + hs300
│   │   └── lhb.py          # 龙虎榜滚动3个月
│   └── quarterly/
│       ├── detector.py     # 检测缺失年报的股票列表
│       ├── income.py       # 利润表
│       ├── balance_sheet.py
│       └── cashflow.py
└── juchao/
    ├── client.py        # cninfo.com.cn HTTP封装
    ├── downloader.py    # PDF增量下载
    ├── pdf_to_md.py     # PDF→MD 多进程转换
    ├── deepseek_infer.py  # 推理→causal_edges+report_metrics
    └── obsidian_sync.py   # Obsidian知识图谱链接重建
```

**常用命令：**
```bash
python -m fintech_data.scheduler --daily                          # 每日盘后
python -m fintech_data.scheduler --quarterly                      # 季度财报补全
python -m fintech_data.scheduler --annual-report \
    --disclosure-index ~/fintech_system/all_disclosure_dates.csv  # 年报全流程
python -m fintech_data.scheduler --only deepseek --dry-run        # 单模块测试
```

---

## 旧版文件清单（`fintech_system/`）

### `scripts/`（工具脚本）

| 文件 | 状态 | 说明 |
|------|------|------|
| `run_deepseek_v3.py` | ✅ 已迁移 | DeepSeek推理主脚本 → `fintech_data/juchao/deepseek_infer.py` |
| `pdf_to_md.py` | ✅ 已迁移 | PDF→MD转换 → `fintech_data/juchao/pdf_to_md.py` |
| `pipeline_new_batch.py` | ✅ 已迁移 | 流程串联 → `fintech_data/scheduler.py` |
| `fetch_stock_daily_hist.py` | ✅ 已迁移 | 日线增量拉取 → `fintech_data/tushare/daily/stock_hist.py` |
| `macro_command_center.py` | ✅ 已迁移 | 宏观数据 → `fintech_data/tushare/daily/macro.py` |
| `fetch_index_components.py` | ✅ 已迁移 | 指数成分股 → `fintech_data/tushare/daily/index.py` |
| `hs300_pipeline.py` | ✅ 已迁移 | HS300日线 → `fintech_data/tushare/daily/index.py` |
| `fetch_history_data.py` | ✅ 已迁移 | 龙虎榜 → `fintech_data/tushare/daily/lhb.py` |
| `deepseek_prompt_v2.py` | 🗑️ 可删 | 旧版Prompt，已内嵌到 deepseek_infer.py |
| `annual_report_supplements.sql` | 📦 保留 | 建表SQL，schema参考 |
| `extract_supplements.py` | ✅ 已迁移 | 提取年报附注字段 → `fintech_data/juchao/extract_supplements.py` |
| `create_obsidian_new.py` | 📦 保留 | 批量创建Obsidian笔记模板，尚未迁移 |
| `link_reports.py` | 📦 保留 | Obsidian内链整理，尚未迁移 |
| `rebuild_stock_cache.py` | 📦 保留 | 重建 .stock_cache.json → 已合并到 obsidian_sync.py |
| `rename_vault_files.py` | 📦 保留 | Obsidian文件批量重命名，偶发性工具 |
| `patch_risk_fields.py` | 📦 保留 | 补填 report_metrics 风险字段，一次性修复脚本 |
| `parse_reports.py` | 🗑️ 可删 | 旧版规则抽取，已被DeepSeek流程替代 |
| `download_missing.py` | 🗑️ 可删 | 旧版PDF补下载，被 fintech_data/juchao/downloader.py 替代 |
| `notify_email.py` | 📦 保留 | 邮件通知工具，scheduler 可选调用 |
| `gemini_fin_agent.py` | 🗑️ 可删 | Gemini实验，已弃用 |
| `test_gemini_hs300.py` | 🗑️ 可删 | Gemini测试，已弃用 |
| `scan_hs300_ma.py` | 📦 保留 | HS300均线扫描，分析工具 |
| `sync_commodity_radar.py` | ✅ 已迁移 | 商品雷达 → `fintech_data/tushare/daily/commodity.py` |
| `turshare_600893_to_pg.py` | 🗑️ 可删 | 单股测试脚本 |
| `progress.json` | 🗑️ 可删 | 旧流程断点文件 |

### `data_layer/`（旧版数据访问层）

| 文件/目录 | 状态 | 说明 |
|-----------|------|------|
| `main.py` | 📦 保留 | 统一入口，analysis_layer 仍在使用 |
| `downloader.py` | ✅ 已迁移 | 三大财报下载 → `fintech_data/tushare/quarterly/` |
| `turshare_connector/` | 📦 保留 | LocalProAPI，analysis_layer 依赖 |
| `choice_connector/` | 📦 保留 | 东方财富Choice接口（需大陆IP） |

### `analysis_layer/`（估值分析层，未迁移）

| 文件 | 说明 |
|------|------|
| `dcf.py` | DCF估值引擎 |
| `valuation.py` | 多方法估值引擎（行业自动选择） |
| `hs300_valuation.py` | HS300一体化估值 |
| `run_dcf_hs300.py` | 批量跑DCF并导出CSV |
| `run_hs300_final.py` | HS300估值完整报告 |
| `run_industry_agg.py` | 行业聚合报告 |
| `run_valuation_hs300.py` | HS300按行业估值汇总 |
| `_download_hs300.py` | 内部：补下载HS300财务数据 |

### `_archive/`（归档，原则上不再使用）

| 类别 | 文件 | 说明 |
|------|------|------|
| PDF下载迭代 | `download_v3_safe.py` ~ `download_v8_final.py` | 历次迭代，v8为最终版，已整合 |
| PDF下载迭代 | `download_final.py`, `download_missing_v2.py`, `download_one_by_one.py` | 同上 |
| 规则抽取迭代 | `financial_extractor_v2.py`, `financial_extractor_v3.py`, `layer1_extractor.py` | 旧版规则抽取，已弃用 |
| 批量入库 | `mass_loader_v2.py`, `mass_loader_v3_fast.py`, `mass_loader_facts.py` | 历史补数据，已完成 |
| Pipeline迭代 | `pipeline_v4.py`, `pipeline_final_strict.py`, `pipeline_gemini_pro.py`, `pipeline_deepseek_v4_concurrent.py` | 历次流程，已整合 |
| Gemini实验 | `llm_gemini.py`, `compare_gemini_models.py`, `pipeline_gemini_pro.py` | 已弃用 |
| 数据库维护 | `upgrade_db_v2.py`, `check_db_status.py`, `verify_data_flow.py` | 一次性维护脚本 |
| Tushare接口 | `batch_sync_turshare_100.py`, `download_turshare_pure.py`, `download_via_turshare.py` | 旧版，已整合 |
| 工具杂项 | `back.py`, `onekey_sync.py`, `sync.py` | 备份/同步shell脚本 |
| 调试/测试 | `debug_guangbai_extraction.py`, `run_3_1_test.py`, `compare_rule_vs_deepseek.py` | 调试用，可删 |
| 分析工具 | `stock_analyzer.py`, `query_top_roe.py`, `strategies_ma_cross.py` | 分析脚本，按需保留 |
| 数据导出 | `export_statements.py`, `fetch_financial_data.py`, `local_pro_api.py` | 已被新层替代 |

---

## 清理建议

**可直接删除（`🗑️`）：**
- `scripts/`：`deepseek_prompt_v2.py`, `parse_reports.py`, `download_missing.py`, `gemini_fin_agent.py`, `test_gemini_hs300.py`, `turshare_600893_to_pg.py`, `progress.json`
- `_archive/`：全目录（已归档即可删除，或整体压缩留存）

**等迁移完成后再删（`📦`）：**
- `scripts/extract_supplements.py` → 待迁移到 `fintech_data/juchao/`
- `scripts/sync_commodity_radar.py` → 待迁移到 `fintech_data/tushare/`
- `data_layer/` → analysis_layer 完成迁移后整体清理

---

## 下一步

- [x] `fintech_data/juchao/extract_supplements.py` 迁移完成
- [x] `fintech_data/tushare/daily/commodity.py` 迁移完成
- [ ] `analysis_layer/` 接入 `fintech_data` 新数据层（替换旧 `data_layer`）
- [ ] 配置 crontab 执行每日 `--daily` 任务
- [ ] 清理 `scripts/` 中标注为 `🗑️` 的文件
