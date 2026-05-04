# fintech_system · Claude Code 上下文

## 当前进度

L1 数据层重构完成，准备开始 L2 分析层（DCF 引擎）。

---

## 七层架构

| 层 | 名称 | 状态 |
|---|---|---|
| L1 | 数据层 | ✅ 完成 |
| L2 | 分析层 | 🔧 下一步 |
| L3 | Agent 层 | 待建（agents/ 目录为空）|
| L4 | 本地推理层 | 暂缓 |
| L5 | 工具与编排层 | 待建 |
| L6 | 记忆与叙事引擎 | 待建 |
| L7 | 部署与监控层 | 待建 |

---

## L1 数据层（已完成）

### 结构

```
data_layer/
├── main.py                   # 唯一入口：get_pro() / get_choice()
├── turshare_connector/
│   ├── __init__.py           # 暴露 pro_api, LocalProAPI
│   ├── client.py             # LocalProAPI：daily/pro_bar/stock_basic/adj_factor/trade_cal/query
│   └── db.py                 # PostgreSQL 连接管理，读 PG_* 环境变量
└── choice_connector/
    ├── __init__.py           # 暴露 ChoiceConnector, indicators
    ├── connector.py          # ChoiceConnector：login/css/csd/ctr/cps/cnq
    └── indicators.py         # 常用指标映射表（INCOME/BALANCE/CASHFLOW/RATIO...）
```

### 用法

```python
from data_layer.main import get_pro, get_choice

pro = get_pro()
df  = pro.daily(ts_code="600893.SH", start_date="20240101")
df  = pro.pro_bar(ts_code="600893.SH", adj="qfq")

choice = get_choice()
choice.login()
df = choice.get_css("600893.SH", ["NETPROFIT"], "20241231")
choice.logout()
```

### 已完成事项

- `data/statements/` 208个文件全部重命名为股票代码格式（Turshare HTTP API 补全映射）
- 根目录 44 个废弃脚本归档到 `_archive/`
- `data_layer/__init__.py` 统一对外暴露两个连接器
- `client.py` 补全 `pro_bar()`（前/后复权）和 `trade_cal()`

---

## 数据库

- **DB**: `fintech_db`，PostgreSQL，本地 localhost:5432
- **主要表**:
  - `stock_daily` — 列名全是中文（日期、股票代码、开盘、收盘...），股票代码无交易所后缀（如 `300590` 而非 `300590.SZ`）
  - `income_statement` — 有 ts_code（标准格式）和 company 字段
  - `balance_sheet` / `cash_flow_statement`
  - `annual_report_meta` — ts_code 字段实际存的是公司名（数据质量问题）
  - 其他：commodity_radar、macro_futures、stock_lhb_branches_3m 等
- **当前数据量**: stock_daily 有 72,715 行，只有 2 支股票（920111、300590）
- **不存在的表**: adj_factor、trade_cal、stock_basic（pro_bar 降级处理，adj_factor 缺失时返回不复权数据）

---

## 关键注意事项

- `turshare_connector/client.py` 的 `daily()` 已处理列名映射（中文→英文别名）和代码格式（`600893.SH` → `600893`）
- 每次运行前需要 source .env：`set -a && source config/.env && set +a`
- PYTHONPATH 需要设为项目根目录：`PYTHONPATH=. python3 ...`
- `annual_report_meta.ts_code` 字段存的是公司名，不是代码，这是已知数据质量问题

---

## 下一步

1. 开始 L2 分析层：DCF 引擎
