"""fintech_data/db.py — 连接池 + upsert 工具"""
from __future__ import annotations
import psycopg2
import psycopg2.pool
from psycopg2.extras import execute_values
from . import config

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **config.DB)
    return _pool


def get_conn():
    return _get_pool().getconn()


def put_conn(conn):
    _get_pool().putconn(conn)


def upsert(conn, table: str, rows: list[dict], conflict_cols: tuple[str, ...]) -> int:
    """批量 upsert，同一批次内按 conflict_cols 去重，保留最后一条。"""
    if not rows:
        return 0
    seen, deduped = set(), []
    for r in rows:
        key = tuple(r[c] for c in conflict_cols)
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    cols = list(deduped[0].keys())
    vals = [[r[c] for c in cols] for r in deduped]
    q    = lambda c: f'"{c}"'  # noqa: E731  — quote every identifier
    conf = ", ".join(q(c) for c in conflict_cols)
    upd  = ", ".join(f"{q(c)}=EXCLUDED.{q(c)}" for c in cols if c not in conflict_cols)
    sql  = (
        f"INSERT INTO {table} ({', '.join(q(c) for c in cols)}) VALUES %s "
        f"ON CONFLICT ({conf}) DO UPDATE SET {upd}"
    )
    with conn.cursor() as cur:
        execute_values(cur, sql, vals)
    conn.commit()
    return len(deduped)
