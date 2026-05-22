# Fintech System

A 股数据采集、财报分析、量化估值与策略回测系统。数据存储于 Docker 容器 `fintech_pg`（PostgreSQL 14，数据库 `fintech_db`）。

---

## 系统架构总览

```
fintech_system/
│
├── fintech_data/              ← 【主力】新版数据层（统一入口）
│   ├── config.py              配置中心（DB/Token/路径，读环境变量）
│   ├── db.py                  连接池 + upsert
│   ├── logger.py              日志工厂
│   ├── scheduler.py           CLI 主入口
│   │
│   ├── tushare/               行情数据采集（Tushare Pro）
│   │   ├── client.py          Tushare API 单例
│   │   ├── daily/             每日盘后任务
│   │   │   ├── stock_hist.py  日线增量（stock_daily_hist）
│   │   │   ├── macro.py       SHIBOR / 期货 / 全球指数
│   │   │   ├── index.py       6 大指数日线 + HS300
│   │   │   ├── lhb.py         龙虎榜滚动 3 个月
│   │   │   └── commodity.py   商品雷达
│   │   └── quarterly/         季度财报
│   │       ├── income.py      利润表
│   │       ├── balance_sheet.py
│   │       ├── cashflow.py
│   │       └── detector.py    缺口检测
│   │
│   ├── juchao/                年报处理（巨潮资讯）
│   │   ├── client.py          cninfo.com.cn HTTP 封装
│   │   ├── downloader.py      PDF 增量下载
│   │   ├── pdf_to_md.py       PDF → Markdown 多进程转换
│   │   ├── deepseek_infer.py  LLM 推理 → causal_edges + report_metrics
│   │   ├── extract_supplements.py  财务附注抽取
│   │   └── obsidian_sync.py   Obsidian 知识图谱链接重建
│   │
│   └── quant/                 【量化分析层】（2026-05-21 新增）
│       ├── bt_feed.py         backtrader 数据适配器 + 内置策略
│       ├── backtest.py        vectorbt 向量化回测
│       ├── alpha_factory.py   qlib 因子计算（Alpha158 扩展）
│       ├── pg_to_qlib.py      PostgreSQL → qlib 数据格式导出
│       └── vol_mktcap_analysis.py  量比 vs 市值变化分析
│
├── analysis_layer/            【估值分析层】（旧版，仍在用）
│   ├── dcf.py                 DCF 估值引擎
│   ├── valuation.py           多方法估值（行业自动选择）
│   ├── dcf_hs300_industry.py  HS300 行业细分估值（主力脚本，v2.3）
│   ├── hs300_valuation.py     HS300 一体化估值
│   ├── run_dcf_hs300.py       批量跑 DCF 并导出 CSV
│   ├── run_hs300_final.py     HS300 估值完整报告
│   ├── run_industry_agg.py    行业聚合报告
│   ├── run_valuation_hs300.py HS300 按行业估值汇总
│   └── _download_hs300.py     内部：补下载 HS300 财务数据
│
├── data_layer/                【旧版数据访问层】（analysis_layer 依赖，暂保留）
│   ├── main.py                统一入口
│   ├── turshare_connector/    LocalProAPI
│   └── choice_connector/      东方财富 Choice 接口
│
├── scripts/                   工具脚本（部分已迁移至 fintech_data/）
│
└── _archive/                  已归档，不再使用
```

---

## 量化层工具说明（`fintech_data/quant/`）

### 三个工具的定位

| 工具 | 类型 | 核心问题 | 适用场景 |
|------|------|---------|---------|
| **qlib** | 横截面（Cross-section） | 今天该买哪只票？ | ML 选股、因子挖掘 |
| **vectorbt** | 时间序列（Time-series） | 这只票什么时候买？ | 参数网格搜索、快速回测 |
| **backtrader** | 时间序列（事件驱动） | 这只票什么时候买？ | 单策略验证、逻辑严谨性 |

### 快速使用

```python
# backtrader：单股策略回测
from fintech_data.quant.bt_feed import run_strategy, MACrossStrategy, VolSurgeStrategy, RSIStrategy
result = run_strategy(MACrossStrategy, "600519.SH", start="2020-01-01")

# 多策略对比
from fintech_data.quant.bt_feed import compare_strategies
df = compare_strategies("600519.SH", start="2020-01-01")

# vectorbt：量比分析 + 组合回测
from fintech_data.quant.backtest import run_ma_cross, run_portfolio, grid_search_ma
pf = run_ma_cross("600519.SH", fast=10, slow=30, start="2020-01-01")
pf.stats()

# 成交量 vs 市值分析
python -m fintech_data.quant.vol_mktcap_analysis
```

---

## 数据库概览（fintech_db，共 30 张表，约 2.8 GB）

| 表名 | 大小 | 说明 |
|------|------|------|
| stock_daily_hist | 2255 MB | A 股历史日线（2014 至今，约 1180 万行），主表 |
| tdx_etf_daily | 147 MB | TDX 本地 ETF / 可转债日线（2021 至今，约 128 万行）|
| tdx_industry_index_daily | 145 MB | TDX 申万行业指数日线（2021 至今，约 122 万行）|
| balance_sheet | 38 MB | 资产负债表（153 列，含 lease_liab）|
| cash_flow_statement | 33 MB | 现金流量表（98 列）|
| income_statement | 22 MB | 利润表（86 列）|
| report_metrics | 20 MB | 年报综合指标（29 列，DeepSeek 推理结果）|
| stock_lhb_branches_3m | 15 MB | 龙虎榜营业部 |
| stock_top_inst | 15 MB | 机构席位 |
| causal_edges | 7 MB | 年报因果逻辑链（LLM 从年报提取）|
| stock_top_list | 3 MB | 龙虎榜主表 |
| annual_report_supplements | 1.5 MB | 年报补充数字字段 |
| statement_details | 1.4 MB | 财务明细（规则抽取）|
| stock_basic | 784 KB | 股票基本信息（5512 只）|
| index_daily_data | 432 KB | 指数日线 |
| index_components | 304 KB | 指数成分股（含权重）|
| 其余 14 张表 | < 200 KB | 宏观/现货/商品/测试等 |

---

## 文件存储

| 路径 | 内容 | 大小 |
|------|------|------|
| `~/上市公司年报/` | 年报 PDF 文件 | 2.5 MB（样本）|
| `~/annual_reports/` | 处理中间产物（MD / 日志 / 进度）| 7.9 MB |
| `~/Obsidians/` | Obsidian 知识库 | 8 KB |
| `fintech_system/data/` | 估值结果 CSV | 按需生成 |

---

## 常用命令

```bash
# 数据采集
python -m fintech_data.scheduler --daily                     # 每日盘后行情
python -m fintech_data.scheduler --quarterly                 # 季度财报补全
python -m fintech_data.scheduler --annual-report \
    --disclosure-index ~/fintech_system/all_disclosure_dates.csv

# 估值分析
cd fintech_system && conda run -n fintech python analysis_layer/dcf_hs300_industry.py

# 量化回测
conda run -n fintech python -m fintech_data.quant.vol_mktcap_analysis
```

---

## Python 环境

| 项目 | 说明 |
|------|------|
| 环境 | conda `fintech`，Python 3.11 |
| 主要包 | pandas 2.3.3 / numpy 2.4.4 / psycopg2 / tushare |
| 量化包 | pyqlib 0.9.7 / vectorbt 1.0.0 / backtrader 1.9.78 |
| AI 包 | openai / google-genai / ollama |

---

## 旧版文件状态（`scripts/`）

| 文件 | 状态 |
|------|------|
| `run_deepseek_v3.py` `pdf_to_md.py` `pipeline_new_batch.py` `fetch_stock_daily_hist.py` `macro_command_center.py` `fetch_index_components.py` `hs300_pipeline.py` `fetch_history_data.py` `extract_supplements.py` `sync_commodity_radar.py` | ✅ 已迁移至 `fintech_data/` |
| `create_obsidian_new.py` `link_reports.py` `rename_vault_files.py` `patch_risk_fields.py` `notify_email.py` `scan_hs300_ma.py` `sync_tdx_to_pg.py` | 📦 保留备用 |
| `deepseek_prompt_v2.py` `parse_reports.py` `download_missing.py` `gemini_fin_agent.py` `test_gemini_hs300.py` `turshare_600893_to_pg.py` | 🗑️ 可删除 |

---

## 待办事项

- [ ] `analysis_layer/` 接入 `fintech_data` 新数据层（替换旧 `data_layer` 引用）
- [ ] 配置 crontab，每日盘后自动执行 `--daily`
- [ ] 清理 `scripts/` 中标注为 🗑️ 的文件
- [ ] `pg_to_qlib.py` 完成数据导出，初始化 qlib provider
- [ ] 重新跑 HS300 全量估值（含新增三情景列、行业 WACC）
