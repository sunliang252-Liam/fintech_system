# Fintech System

一个专注于 A 股年报提取、数据分析和量化评估的金融科技系统。

## 核心功能

- **年报提取**：基于 `pdfplumber` 规则提取 A 股年报数据。
- **数据管理**：使用 PostgreSQL 存储三大财务报表（资产负债表、利润表、现金流量表）。
- **量化分析**：包含 DCF 估值、行业对比等分析模型。

## 项目结构

- `agents/`: 智能代理逻辑。
- `analysis_layer/`: 数据分析层。
- `config/`: 配置文件（包含 `.env.example`）。
- `data/`: 数据存放目录（CSV/PDF 等）。
- `data_layer/`: 数据库交互层。
- `notebooks/`: Jupyter Notebook 研究记录。
- `scripts/`: 工具脚本。

## 快速开始

1. 克隆项目。
2. 配置 `config/.env`（参考 `config/.env.example`）。
3. 运行 `manager.sh` 或相关脚本启动系统。

## 注意事项

- 请勿上传包含敏感信息的 `.env` 文件。
- 数据库连接信息请根据实际情况配置。
