# 数据资产清单

> 最后更新：2026-05-08
> 数据库：PostgreSQL · localhost:5432 · fintech_db

---

## 一、核心年报分析数据

### report_metrics（AI 推理结果）
- **规模**：5,357 行 · 20 MB · 29 个字段
- **来源**：DeepSeek v3 对 2025 年年报逐份推理生成
- **覆盖**：5,188 家已完成推理（169 家待补充）

| 字段 | 说明 |
|------|------|
| ts_code / code / market | 股票代码、6位代码、市场（SH/SZ/BJ） |
| key_contradiction | 核心矛盾分析（自然语言） |
| profit_sustainability | 利润可持续性评级（高/中/低） |
| cashflow_risk | 现金流风险评级（高/中/低） |
| data_credibility | 财务数据可信度评级（高/中/低） |
| key_metric | 首要追踪指标 |
| risk_1 / risk_2 / risk_3 | 核心风险描述（前三条） |
| capex_adj | 资本开支调整说明 |
| industry_supplement | 行业补充分析 |
| profit_quality | 利润质量说明 |

**评级分布：**

| 维度 | 高 | 中 | 低 |
|------|-----|-----|-----|
| 利润可持续性 | 176 家 | 997 家 | 4,096 家 |
| 现金流风险 | 2,837 家 | 1,161 家 | 1,270 家 |
| 数据可信度 | 906 家 | 3,414 家 | 949 家 |

---

### causal_edges（因果逻辑链）
- **规模**：15,335 条 · 7 MB · 8 个字段
- **来源**：DeepSeek 推理时提取的财务因果关系
- **含具体数字的条目**：12,471 条（81%）

| 字段 | 说明 |
|------|------|
| ts_code | 股票代码 |
| report_year | 年报年份（2025） |
| source_node | 因（事件/指标名称） |
| target_node | 果（事件/指标名称） |
| description | 因果关系描述 |
| evidence | 支撑数据/证据 |
| has_number | 是否含量化数据（Boolean） |

---

### annual_report_supplements（年报数字字段）
- **规模**：5,356 行 · 1.5 MB · 35 个字段
- **来源**：正则表达式从 MD 文件中提取

| 字段组 | 包含字段 |
|--------|----------|
| 合同负债 | contract_liab_end / start / chg_pct |
| 在建工程 | construction_end / start / largest_project_name / budget / done |
| 研发支出 | rd_total / rd_capitalized / rd_cap_rate |
| 利息资本化 | interest_capitalized |
| 非经常性损益 | non_recurring_total / non_recurring_detail |
| 客户集中度 | top5_customer_pct / top1_customer_pct / related_party_pct |
| 商誉 | goodwill / goodwill_impairment / goodwill_discount_rate |
| 受限资金 | restricted_cash |
| 银行专项 | npl_ratio / provision_coverage / nim / attention_loan_ratio |
| 或有负债 | contingent_liab / major_litigation / commitment_issues |

---

## 二、财务三表（Tushare 历史数据）

| 表名 | 行数 | 大小 | 时间范围 | 公司数 |
|------|------|------|----------|--------|
| balance_sheet 资产负债表 | 49,614 | 38 MB | 2017-12-31 ~ 2025-12-31 | 5,788 家 |
| cash_flow_statement 现金流量表 | 49,384 | 33 MB | 2017-12-31 ~ 2025-12-31 | 5,785 家 |
| income_statement 利润表 | 49,431 | 22 MB | 2017-12-31 ~ 2025-12-31 | 5,788 家 |

> 三表覆盖 A 股全量公司 8 年财报数据，每家公司通常含年报、中报、季报多期数据。

**balance_sheet 主要字段（共 153 个）：**
货币资金、交易性金融资产、应收票据及应收账款、预付款项、存货、固定资产、在建工程、无形资产、商誉、长期股权投资、短期借款、应付账款、合同负债、长期借款、应付债券、实收资本、未分配利润、少数股东权益、资产总计、负债合计……

---

## 三、市场行情数据

### stock_basic（股票基本信息）
- **规模**：5,512 行 · 784 KB · 6 个字段
- ts_code / symbol / name / area / industry / list_date

### stock_lhb_branches_3m（龙虎榜营业部近3月）
- **规模**：42,391 行 · 9 MB
- **时间范围**：2026-01-26 ~ 2026-04-23
- **覆盖**：1,367 只股票

### stock_top_list（龙虎榜明细）
- **规模**：4,026 行 · 904 KB
- **时间范围**：2026-01-26 ~ 2026-04-23

### stock_top_inst（龙虎榜机构席位）
- **规模**：168 KB
- **时间范围**：2026-04-23（单日）· 61 只股票

### hs300_history（沪深300历史）
- **规模**：73 行
- **时间范围**：2026-01-05 ~ 2026-04-24

### index_daily_data（指数日线）
- **规模**：542 行
- **时间范围**：2024-01-02 ~ 2026-04-01

---

## 四、宏观与商品数据（数据量较少）

| 表名 | 行数 | 时间范围 | 说明 |
|------|------|----------|------|
| macro_futures | 110 | 2026-03-25 ~ 2026-04-24 | 商品期货日线，5个品种 |
| commodity_radar | 174 | 2026-03-16 ~ 2026-04-24 | 商品价格雷达 |
| macro_shibor | 22 | 2026-03-25 ~ 2026-04-24 | Shibor 利率各期限 |
| macro_global | 16 KB | — | 全球宏观指标（数据极少） |
| spot_proxy_daily | 208 KB | — | 现货代理日线 |
| spot_finance_shibor | 16 KB | — | 金融现货+Shibor |
| spot_data_final | 16 KB | — | 现货最终数据 |

---

## 五、其他辅助数据

| 表名 | 行数 | 说明 |
|------|------|------|
| statement_details | 4,567 | 报表明细，覆盖 109 家公司 |
| financials | 少量 | 综合财务指标 |
| top_customers | 1 | 前五大客户（基本未填充） |
| top_suppliers | 0 | 前五大供应商（空表） |
| annual_report_meta | 1 | 年报元数据（基本未填充） |
| test_stock_spot | 56 KB | 测试用现货数据 |

---

## 六、Obsidian 知识图谱（文件系统）

> 路径：`~/Documents/Obsidian_Vault/02_Company_Analysis/`

| 类型 | 数量 | 说明 |
|------|------|------|
| 公司分析文件 | 5,583 个 | 每文件含 YAML frontmatter + DeepSeek v3 分析块 + 同行链接 |
| 行业枢纽文件 | 493 个 | 申万三级（347个）+ Tushare补充行业 |
| 总索引 | 1 个 | `00_Company_Index.md`，三级层级结构（一级→二级→三级） |
| stock_cache.json | 1 个 | 5,513 家公司的名称/行业/市场映射，申万三级分类 |

---

## 七、原始 Markdown 文件（文件系统）

> 路径：`~/上市公司年报_MD/`

- **文件数**：5,599 个
- **来源**：pdfplumber 从 PDF 提取
- **格式**：`{公司名}：2025年年度报告.md`
- **内容**：年报全文，每份最多 150,000 字符

---

## 待补充数据

| 项目 | 当前状态 | 备注 |
|------|----------|------|
| top_suppliers / top_customers | 基本为空 | 需从年报附注提取 |
| annual_report_meta | 仅 1 行 | 年报发布日期、审计机构等元数据 |
| macro_global | 数据极少 | 全球宏观指标未系统拉取 |
| 股价日线 stock_daily | 数据极少 | 全量历史行情未入库 |
| DCF 估值 | 未执行 | 指令3，暂缓 |
