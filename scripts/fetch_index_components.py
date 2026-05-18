"""
scripts/fetch_index_components.py
-----------------------------------
从 Tushare 拉取主要指数列表及成分股名单，存入数据库并导出 JSON。

目标指数：
  000300.SH  沪深300
  000016.SH  上证50
  000905.SH  中证500
  000852.SH  中证1000
  399006.SZ  创业板指
  000688.SH  科创50

建表：
  index_info       — 指数基本信息
  index_components — 指数成分股（含权重）

JSON 输出：
  /tmp/index_components.json   — 全量 {指数代码: [成分股列表]}
  /tmp/hs300_codes.json        — HS300 成分股列表（供 DCF 脚本直接使用）
"""

import os, sys, json, time, urllib.request
sys.path.insert(0, "/home/liam-sun/fintech_system")
os.chdir("/home/liam-sun/fintech_system")

from sqlalchemy import create_engine, text
import pandas as pd

TOKEN = os.getenv("TUSHARE_TOKEN", "291ce212f1392ef6a603bd2e73e1be6607aae109657cebb16491c30a")
DB_URL = (
    f"postgresql://{os.getenv('PG_USER','postgres')}:{os.getenv('PG_PASSWORD','fintech123')}"
    f"@{os.getenv('PG_HOST','localhost')}:{os.getenv('PG_PORT','5432')}"
    f"/{os.getenv('PG_DB','fintech_db')}"
)

TARGET_INDEXES = [
    ("000300.SH", "沪深300"),
    ("000016.SH", "上证50"),
    ("000905.SH", "中证500"),
    ("000852.SH", "中证1000"),
    ("399006.SZ", "创业板指"),
    ("000688.SH", "科创50"),
]


def ts_get(api_name, **params):
    url     = "https://api.tushare.pro"
    payload = json.dumps({"api_name": api_name, "token": TOKEN, "params": params}).encode()
    req     = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    if res.get("code") != 0:
        raise RuntimeError(f"Tushare 错误: {res.get('msg')}")
    fields = res["data"]["fields"]
    return [dict(zip(fields, row)) for row in res["data"]["items"]]


def init_tables(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS index_info (
                ts_code   VARCHAR(20) PRIMARY KEY,
                name      TEXT,
                market    TEXT,
                category  TEXT,
                update_time TIMESTAMP DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS index_components (
                index_code  VARCHAR(20) NOT NULL,
                ts_code     VARCHAR(20) NOT NULL,
                trade_date  VARCHAR(10),
                weight      NUMERIC(8,4),
                update_time TIMESTAMP DEFAULT now(),
                PRIMARY KEY (index_code, ts_code)
            )
        """))
    print("数据表就绪\n")


def fetch_index_info(engine):
    print("── 拉取指数基本信息 ──")
    all_rows = []
    for market in ["SSE", "SZSE", "SW"]:
        try:
            rows = ts_get("index_basic", market=market,
                          fields="ts_code,name,market,category")
            all_rows.extend(rows)
        except Exception as e:
            print(f"  {market} 拉取失败: {e}")
        time.sleep(0.3)

    # 只保留目标指数
    target_codes = {code for code, _ in TARGET_INDEXES}
    rows = [r for r in all_rows if r["ts_code"] in target_codes]

    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO index_info (ts_code, name, market, category)
                VALUES (:ts_code, :name, :market, :category)
                ON CONFLICT (ts_code) DO UPDATE
                SET name=EXCLUDED.name, market=EXCLUDED.market,
                    category=EXCLUDED.category, update_time=now()
            """), r)
    print(f"  已写入 {len(rows)} 条指数信息\n")
    return rows


def fetch_components(engine, index_code: str, index_name: str, trade_date: str = "20260430") -> list:
    print(f"── {index_name}（{index_code}）成分股 ──")
    try:
        rows = ts_get("index_weight", index_code=index_code, trade_date=trade_date,
                      fields="index_code,con_code,trade_date,weight")
    except Exception as e:
        print(f"  拉取失败: {e}")
        return []

    if not rows:
        print(f"  {trade_date} 无数据，尝试上月末...")
        try:
            rows = ts_get("index_weight", index_code=index_code, trade_date="20260328",
                          fields="index_code,con_code,trade_date,weight")
        except Exception as e2:
            print(f"  再次失败: {e2}")
            return []

    codes = [r["con_code"] for r in rows]
    print(f"  成分股 {len(codes)} 只")

    with engine.begin() as conn:
        # 先清旧数据
        conn.execute(text("DELETE FROM index_components WHERE index_code = :c"),
                     {"c": index_code})
        for r in rows:
            conn.execute(text("""
                INSERT INTO index_components (index_code, ts_code, trade_date, weight)
                VALUES (:index_code, :ts_code, :trade_date, :weight)
                ON CONFLICT (index_code, ts_code) DO UPDATE
                SET trade_date=EXCLUDED.trade_date, weight=EXCLUDED.weight, update_time=now()
            """), {
                "index_code": r["index_code"],
                "ts_code":    r["con_code"],
                "trade_date": r["trade_date"],
                "weight":     r["weight"],
            })
    print(f"  已写入数据库\n")
    return codes


if __name__ == "__main__":
    engine = create_engine(DB_URL)
    init_tables(engine)
    fetch_index_info(engine)

    all_components = {}
    for index_code, index_name in TARGET_INDEXES:
        codes = fetch_components(engine, index_code, index_name)
        all_components[index_code] = codes
        time.sleep(0.5)

    # 导出 JSON
    os.makedirs("/tmp", exist_ok=True)

    with open("/tmp/index_components.json", "w", encoding="utf-8") as f:
        json.dump(all_components, f, ensure_ascii=False, indent=2)
    print("已导出: /tmp/index_components.json")

    hs300 = all_components.get("000300.SH", [])
    with open("/tmp/hs300_codes.json", "w", encoding="utf-8") as f:
        json.dump(hs300, f, ensure_ascii=False, indent=2)
    print(f"已导出: /tmp/hs300_codes.json（{len(hs300)} 只）")

    # 汇总
    print("\n── 汇总 ──")
    for code, name in TARGET_INDEXES:
        n = len(all_components.get(code, []))
        print(f"  {name}（{code}）: {n} 只")
