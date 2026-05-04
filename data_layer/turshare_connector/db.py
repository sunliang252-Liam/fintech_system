"""
data_layer/turshare_connector/db.py
───────────────────────────────────
PostgreSQL 连接管理。
所有数据库 I/O 都通过这里，client.py 不直接碰连接细节。
"""

from __future__ import annotations

import os

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

_DEFAULT_DSN = {
    "host":     os.getenv("PG_HOST",     "localhost"),
    "port":     int(os.getenv("PG_PORT", "5432")),
    "dbname":   os.getenv("PG_DB",       "fintech"),
    "user":     os.getenv("PG_USER",     "postgres"),
    "password": os.getenv("PG_PASSWORD", ""),
}


def get_conn(**kwargs) -> psycopg2.extensions.connection:
    """创建 PostgreSQL 连接，kwargs 可覆盖默认 DSN。"""
    dsn = {**_DEFAULT_DSN, **kwargs}
    return psycopg2.connect(**dsn)


def query(sql: str, params: tuple = (), conn=None) -> pd.DataFrame:
    """
    执行参数化 SQL，返回 DataFrame。
    conn=None 时自动开关连接；传入 conn 则由调用方管理生命周期。
    """
    _conn = conn or get_conn()
    try:
        with _conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    finally:
        if conn is None:
            _conn.close()
