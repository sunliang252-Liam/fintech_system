-- ============================================================
-- annual_report_supplements
-- 存储三大报表覆盖不到的关键附注字段
-- 数据来源优先级：plumber原文提取 > DeepSeek结构化 > 人工录入
-- ============================================================

CREATE TABLE IF NOT EXISTS annual_report_supplements (
    -- 主键
    ts_code         VARCHAR(10)  NOT NULL,   -- 如 600435.SH
    end_date        DATE         NOT NULL,   -- 报告期末 如 2025-12-31
    
    -- ── 第一等级：直接影响DCF估值变量 ──────────────────────────

    -- 合同负债（收入领先指标）
    contract_liab_end       NUMERIC(18,2),  -- 期末余额（元）
    contract_liab_start     NUMERIC(18,2),  -- 期初余额（元）
    contract_liab_chg_pct   NUMERIC(8,4),   -- 变动率（%），可计算

    -- 在建工程（未来Capex承诺）
    construction_end        NUMERIC(18,2),  -- 在建工程期末账面价值（元）
    construction_start      NUMERIC(18,2),  -- 期初
    largest_project_name    VARCHAR(100),   -- 最大单项目名称
    largest_project_budget  NUMERIC(18,2),  -- 预计总投资（元）
    largest_project_done    NUMERIC(8,4),   -- 累计投入占预算比例（%）

    -- 研发资本化（调整真实Capex）
    rd_total                NUMERIC(18,2),  -- 研发投入总额（元，含资本化）
    rd_capitalized          NUMERIC(18,2),  -- 资本化金额（元）
    rd_cap_rate             NUMERIC(8,4),   -- 资本化率（%）

    -- 利息资本化（隐藏财务成本）
    interest_capitalized    NUMERIC(18,2),  -- 本期资本化利息（元）

    -- 非经常性损益（还原normalized利润）
    non_recurring_total     NUMERIC(18,2),  -- 非经常性损益合计（元，正=收益）
    non_recurring_detail    TEXT,           -- 主要项目描述，JSON格式

    -- ── 第二等级：影响假设质量 ──────────────────────────────────

    -- 客户集中度
    top5_customer_pct       NUMERIC(8,4),   -- 前五大客户销售额占比（%）
    top1_customer_pct       NUMERIC(8,4),   -- 最大单一客户占比（%）
    related_party_pct       NUMERIC(8,4),   -- 关联方占收入比例（%）

    -- 商誉（减值风险）
    goodwill                NUMERIC(18,2),  -- 商誉余额（元）
    goodwill_impairment     NUMERIC(18,2),  -- 本期减值（元）
    goodwill_discount_rate  NUMERIC(8,4),   -- 减值测试折现率（%）

    -- 受限资金（影响可用现金）
    restricted_cash         NUMERIC(18,2),  -- 受限货币资金（元）

    -- 银行专用字段
    npl_ratio               NUMERIC(8,4),   -- 不良贷款率（%）
    provision_coverage      NUMERIC(8,4),   -- 拨备覆盖率（%）
    nim                     NUMERIC(8,4),   -- 净息差（%）
    attention_loan_ratio    NUMERIC(8,4),   -- 关注类贷款占比（%）

    -- ── 第三等级：尾部风险标注 ──────────────────────────────────

    contingent_liab         TEXT,           -- 重大或有负债描述
    major_litigation        TEXT,           -- 重大诉讼/仲裁
    commitment_issues       TEXT,           -- 重大承诺事项（同业竞争等）

    -- ── 数据质量追踪 ────────────────────────────────────────────

    -- 数据来源（每个字段单独记录置信度太复杂，用整体标注）
    source                  VARCHAR(20)     -- 'plumber' | 'deepseek' | 'manual'
        DEFAULT 'deepseek',
    confidence              VARCHAR(10)     -- 'high' | 'mid' | 'low'
        DEFAULT 'mid',
    missing_fields          TEXT,           -- 未能提取的字段列表，逗号分隔
    updated_at              TIMESTAMP       DEFAULT NOW(),

    PRIMARY KEY (ts_code, end_date)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_suppl_ts_code ON annual_report_supplements(ts_code);
CREATE INDEX IF NOT EXISTS idx_suppl_end_date ON annual_report_supplements(end_date);
CREATE INDEX IF NOT EXISTS idx_suppl_source ON annual_report_supplements(source);

-- 注释
COMMENT ON TABLE annual_report_supplements IS
    '年报附注补充字段，存储三大报表覆盖不到的关键数据。
     与report_metrics表互补：report_metrics存DeepSeek叙事提取，
     本表存数字类附注字段。通过ts_code+end_date与stock_daily等关联。';

COMMENT ON COLUMN annual_report_supplements.contract_liab_end IS
    '合同负债期末余额。对消费品(经销商预付)、军工(预收款)是最强收入领先指标';
COMMENT ON COLUMN annual_report_supplements.interest_capitalized IS
    '本期资本化利息总额。重资产行业该值大，转固后变折旧，压缩未来EBIT';
COMMENT ON COLUMN annual_report_supplements.rd_cap_rate IS
    '研发资本化率=rd_capitalized/rd_total。激进公司高，保守公司趋近0';
