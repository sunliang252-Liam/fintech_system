-- ============================================================
-- fintech_system PostgreSQL Schema
-- 执行：psql -d fintech -f schema.sql
-- ============================================================

-- 交易日历
CREATE TABLE IF NOT EXISTS trade_cal (
    exchange        VARCHAR(10)  NOT NULL,
    cal_date        CHAR(8)      NOT NULL,
    is_open         SMALLINT     NOT NULL,   -- 1 交易日 / 0 休市
    pretrade_date   CHAR(8),
    PRIMARY KEY (exchange, cal_date)
);

-- 股票基础信息
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code         VARCHAR(12)  NOT NULL PRIMARY KEY,
    symbol          VARCHAR(8),
    name            VARCHAR(20),
    area            VARCHAR(20),
    industry        VARCHAR(30),
    list_status     CHAR(1),                 -- L 上市 / D 退市 / P 暂停
    list_date       CHAR(8),
    delist_date     CHAR(8),
    exchange        VARCHAR(10)
);

-- 日线行情（原始，不复权）
CREATE TABLE IF NOT EXISTS stock_daily (
    ts_code         VARCHAR(12)  NOT NULL,
    trade_date      CHAR(8)      NOT NULL,
    open            NUMERIC(12,4),
    high            NUMERIC(12,4),
    low             NUMERIC(12,4),
    close           NUMERIC(12,4),
    pre_close       NUMERIC(12,4),
    change          NUMERIC(12,4),
    pct_chg         NUMERIC(10,4),
    vol             NUMERIC(20,4),
    amount          NUMERIC(20,4),
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_date
    ON stock_daily (trade_date);

-- 复权因子
CREATE TABLE IF NOT EXISTS adj_factor (
    ts_code         VARCHAR(12)  NOT NULL,
    trade_date      CHAR(8)      NOT NULL,
    adj_factor      NUMERIC(16,6) NOT NULL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_adj_factor_date
    ON adj_factor (trade_date);

-- 同步状态记录
CREATE TABLE IF NOT EXISTS sync_meta (
    table_name      VARCHAR(30)  NOT NULL PRIMARY KEY,
    last_sync_date  CHAR(8),
    last_sync_at    TIMESTAMP    DEFAULT NOW(),
    rows_affected   INTEGER
);
