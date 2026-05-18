# 年报分析系统 · 完整工作流总结

> 最后更新：2026-05-08
> 负责人：Claude Code + liam-sun

---

## 系统概览

| 指标 | 数值 |
|------|------|
| A股覆盖公司总数 | 5,513 家 |
| Obsidian 公司文件 | 5,583 个 |
| Obsidian 行业枢纽文件 | 493 个 |
| DeepSeek 已推理公司 | 5,188 家 |
| 因果逻辑链条数 | 15,335 条 |
| 财报数字字段行数 | 5,356 行 |
| 申万三级行业分类 | 347 个（现役） |

---

## 任务一：第一批年报处理（~3,700家）

### 数据来源
- PDF 存放目录：`~/上市公司年报/`（旧批次，已完成转换）
- Plumber MD 文件：`~/上市公司年报_MD/`（共 ~3,700 份）

### 执行步骤

#### Step 1：正则提取数字字段
```bash
python3 scripts/extract_supplements.py
```
- 从 MD 文件中正则匹配利息资本化、研发资本化、合同负债、在建工程进度、非经常性损益等字段
- 结果写入 PostgreSQL `annual_report_supplements` 表
- 入库约 3,528 行

#### Step 2：DeepSeek 推理分析
```bash
python3 scripts/run_deepseek_v3.py
```
- 调用 DeepSeek API（deepseek-chat，sk-91e6c80c...）
- 5 个并发线程，每公司约 1.5s
- 输出写入：
  - `report_metrics`：矛盾分析、评级（高/中/低）、核心风险、追踪指标
  - `causal_edges`：因果逻辑链（source_node → target_node + 描述）
  - Obsidian 对应 MD 文件末尾：`## 🤖 DeepSeek分析（v3 · 2025年报）` 评级摘要块

#### Step 3：知识图谱联网
```bash
python3 scripts/link_reports.py
```
- 为每个公司 MD 文件写入 YAML frontmatter + 同行业链接
- 生成行业枢纽文件 `行业_XXX.md`
- 生成总索引 `00_Company_Index.md`

---

## 任务二：第二批年报处理（~2,077家）

### 数据来源
- 新 PDF 存放目录：`~/上市公司年报1/`
- 命名规则：`{ts_code}_2025.pdf`（如 `000004.SZ_2025.pdf`）

### 执行步骤

#### Step 1：PDF → Markdown 转换
```bash
python3 scripts/pdf_to_md.py --workers 4
```
- 输入：`~/上市公司年报1/*.pdf`（2,077 个）
- 输出：`~/上市公司年报_MD/{公司名}：2025年年度报告.md`
- 使用 pdfplumber，4进程并行，每份 PDF 最多提取 150,000 字符
- 结果：成功 2,071 / 失败 6（提取内容为空）/ 无PDF 21

#### Step 2：自动化流水线
```bash
# 等待 pdf_to_md 完成后自动触发后续步骤
python3 scripts/pipeline_new_batch.py
```
流水线顺序：
1. `extract_supplements.py`：提取数字字段（约 8 分钟）
2. `run_deepseek_v3.py`：DeepSeek 推理（约 160 分钟）
3. 发邮件通知（Gmail + QQ 双通道）

#### Step 3：创建 Obsidian 文件
```bash
python3 scripts/create_obsidian_new.py
```
- 为 report_metrics 中有推理结果但无 Obsidian 文件的新公司创建骨架 MD
- 从数据库读取分析结果，写入 v3 分析块（不重调 API）
- 本次新建：1,737 个文件

---

## 今日工作：Obsidian 整合 + 行业分类重建（2026-05-08）

### 一、Obsidian 文件整合

| 步骤 | 脚本 | 结果 |
|------|------|------|
| 创建新公司骨架文件 | `create_obsidian_new.py` | 新建 1,737 个 |
| 修复 BJ 股票重复文件 | 手动删除 | 删除 200 个错误的 `_SZ_` 副本 |
| 知识图谱联网 | `link_reports.py` | 493 个行业枢纽文件 |

**BJ 股票重复问题根因：**
- 920xxx 代码在 DB 中 ts_code 存为 `920000.SZ`（后缀误标）
- `create_obsidian_new.py` 从 ts_code 后缀取市场，导致生成 `_SZ_` 副本
- 修复：改为优先读 `row["market"]` 列（值为 `BJ`），再回退到 ts_code 后缀

### 二、行业分类重建（东财 → 申万三级）

#### 问题发现
- 原 stock_cache.json（东财行业，296个）中东财 API 永久断连
- BJ 股票（920xxx）的市场字段全部错标为 SZ
- 总索引结构平铺，无父子层级，"其他类"含义不明

#### 解决过程
```
东财 API 断连
  → 尝试 AKShare sw_index_third_cons → AKShare API Bug，失败
  → 尝试 stock_industry_clf_hist_sw → 有代码无名称，失败
  → 改用 Tushare index_member（申万三级指数成分）→ 成功
```

#### 执行命令
```bash
# 重建 stock_cache.json（约 30 分钟，限速 0.35s/次）
python3 scripts/rebuild_stock_cache.py

# 重新生成行业枢纽文件 + 总索引
python3 scripts/link_reports.py
```

#### 行业分类结果
| 来源 | 行业数 | 说明 |
|------|--------|------|
| 东财（原版） | 296 | API 已断连，不可用 |
| 申万三级（Tushare） | 349 | 现役 330 + 退市但有存量 19 |
| 申万三级全量 | 463 | 含 133 个退市行业 |

### 三、总索引结构改进

**改前（平铺）：**
```
## 行业导航
- IT服务Ⅲ（81）
- LED（25）
- 其他专用设备（79）  ← 含义不明
...
```

**改后（三级层级）：**
```
## 一级行业导航
- 机械设备（461家）   ← 可点击跳转
- 电子（421家）

## 机械设备（461家）
### 专用设备（152家）
#### 其他专用设备（79家）  ← 归属清晰
  公司A · 公司B · ...
#### 能源及重型设备（43家）
  ...
```

**其他改进：**
- 行业枢纽文件（`行业_*.md`）公司名列改为 `[[code_market_name|公司名]]` wiki-link
- 一级行业导航链接锚点与正文标题完全一致，点击可跳转
- "未分类"公司从 PostgreSQL `stock_basic` 补充 Tushare 行业（110个）兜底

---

## 脚本清单

```
scripts/
├── pdf_to_md.py              # PDF → Markdown（pdfplumber，多进程）
├── extract_supplements.py    # 正则提取数字字段 → annual_report_supplements
├── run_deepseek_v3.py        # DeepSeek 推理 → report_metrics + causal_edges + Obsidian
├── create_obsidian_new.py    # 为新公司创建 Obsidian 骨架 + v3分析块（不调API）
├── link_reports.py           # 行业分类联网 → 枢纽文件 + 总索引（三级层级）
├── rebuild_stock_cache.py    # 重建 stock_cache.json（Tushare 申万三级）
├── pipeline_new_batch.py     # 自动化流水线（extract → deepseek → 邮件通知）
├── patch_risk_fields.py      # 从 Obsidian v1 文件回填 risk_1/2/3 字段
└── notify_email.py           # 邮件通知（Gmail + QQ 双通道）
```

---

## 关键配置

| 配置项 | 值 |
|--------|-----|
| PostgreSQL | localhost:5432 / fintech_db / postgres / fintech123 |
| DeepSeek API Key | sk-91e6c80c76ad465390a514c202a09fdc |
| Tushare Token | 291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a |
| Gmail | sunliang252@gmail.com / byunvkndsegjkktx（应用密码）|
| QQ邮箱 | 8407020@qq.com / rqpkzvkguebqcbbd（授权码）|
| PDF 目录（第一批） | ~/上市公司年报/ |
| PDF 目录（第二批） | ~/上市公司年报1/ |
| MD 文件目录 | ~/上市公司年报_MD/ |
| Obsidian Vault | ~/Documents/Obsidian_Vault/02_Company_Analysis/ |
| stock_cache | ~/Documents/Obsidian_Vault/02_Company_Analysis/.stock_cache.json |

---

## 注意事项

| 问题 | 说明 |
|------|------|
| BJ 股票市场字段 | 920xxx 代码不在 `43/83/87` 前缀内，需额外加 `92` 判断 |
| 东财 API | stock_board_industry_name_em 已断连，改用 Tushare 申万三级 |
| Tushare 限速 | index_member 接口 200次/分钟，sleep 设为 0.35s |
| 行业"其他类" | 官方申万分类，非系统错误，在三级层级中归属清晰 |
| skip_existing | run_deepseek_v3.py 默认跳过已有推理结果的公司，重跑安全 |
| Obsidian 回写锁 | 多线程写入使用 threading.Lock() 保护，不会竞争 |
| 银行类公司 | DCF 估值不适用，暂不处理 |

---

## 下次运行（新一批年报）

```bash
# 1. 将新 PDF 放入 ~/上市公司年报1/（命名：ts_code_2025.pdf）
# 2. 生成待处理名单
# 3. 运行一键流水线
python3 scripts/pipeline_new_batch.py

# 4. 创建新公司 Obsidian 文件
python3 scripts/create_obsidian_new.py

# 5. 更新行业图谱
python3 scripts/link_reports.py
```
