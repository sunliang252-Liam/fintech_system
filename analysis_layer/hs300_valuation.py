"""
analysis_layer/hs300_valuation.py
-----------------------------------
HS300 多方法估值一体化脚本。
合并自 valuation.py + run_valuation_hs300.py，字段已对齐数据库实际结构。

估值方法：
  pb_roe    — 银行/保险/证券/地产：P/B + ROE 戈登增长模型
  dcf_capex — 重资产行业：FCF = 经营现金流 − 资本开支
  dcf_cycle — 强周期行业：FCF = 近3年(OCF−capex)均值平滑
  dcf_std   — 稳定行业（默认）：标准 DCF

字段修正对照：
  report_year        → end_date
  net_profit_parent  → n_income_attr_p
  operating_cashflow → n_cashflow_act
  capex              → c_pay_acq_const_fiolta
  cash               → money_cap
  short_term_debt    → st_borr
  long_term_debt     → lt_borr
  equity_parent      → total_hldr_eqy_exc_min_int
  total_equity       → total_hldr_eqy_inc_min_int

运行：
  TRADE_DATE=20260430 python3 analysis_layer/hs300_valuation.py
"""

import os, sys, json, urllib.request, csv
from collections import Counter
import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, "/home/liam-sun/fintech_system")
os.chdir("/home/liam-sun/fintech_system")

# ── 配置 ──────────────────────────────────────────────────────────────────
TOKEN      = os.getenv("TUSHARE_TOKEN", "")
TRADE_DATE = os.getenv("TRADE_DATE", "20260430")

DB_URL = (
    f"postgresql://{os.getenv('PG_USER','postgres')}:{os.getenv('PG_PASSWORD','fintech123')}"
    f"@{os.getenv('PG_HOST','localhost')}:{os.getenv('PG_PORT','5432')}"
    f"/{os.getenv('PG_DB','fintech_db')}"
)

WACC            = 0.09
TERMINAL_GROWTH = 0.02
YEARS           = 5

# ── 行业 → 估值方法映射 ────────────────────────────────────────────────────
INDUSTRY_METHOD: dict[str, str] = {
    # P/B + ROE（金融、地产、高杠杆行业）
    "银行": "pb_roe", "保险": "pb_roe", "证券": "pb_roe",
    "多元金融": "pb_roe", "全国地产": "pb_roe", "区域地产": "pb_roe",
    "园区开发": "pb_roe", "建筑工程": "pb_roe", "路桥": "pb_roe",
    # DCF 扣 capex（重资产行业）
    "半导体": "dcf_capex", "元器件": "dcf_capex", "电气设备": "dcf_capex",
    "新型电力": "dcf_capex", "火力发电": "dcf_capex", "水力发电": "dcf_capex",
    "航空": "dcf_capex", "空运": "dcf_capex", "通信设备": "dcf_capex",
    "运输设备": "dcf_capex", "铁路": "dcf_capex", "机场": "dcf_capex",
    "港口": "dcf_capex", "供气供热": "dcf_capex",
    # 穿越周期 DCF（强周期行业）
    "煤炭开采": "dcf_cycle", "石油开采": "dcf_cycle", "石油加工": "dcf_cycle",
    "黄金": "dcf_cycle", "铜": "dcf_cycle", "铝": "dcf_cycle",
    "小金属": "dcf_cycle", "普钢": "dcf_cycle", "特种钢": "dcf_cycle",
    "化工原料": "dcf_cycle", "农药化肥": "dcf_cycle", "化纤": "dcf_cycle",
    "水泥": "dcf_cycle", "玻璃": "dcf_cycle", "船舶": "dcf_cycle",
    # 其余行业默认 dcf_std
}


# ── 工具函数 ──────────────────────────────────────────────────────────────

def ts_get(api_name, **params):
    url     = "https://api.tushare.pro"
    payload = json.dumps({"api_name": api_name, "token": TOKEN, "params": params}).encode()
    req     = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    fields = res["data"]["fields"]
    return [dict(zip(fields, row)) for row in res["data"]["items"]]


def _to_float(val) -> float:
    """安全转换 float，兼容 text 类型、字符串 'NaN' 和 NULL。"""
    v = pd.to_numeric(val, errors="coerce")
    return 0.0 if pd.isna(v) else float(v)


# ── 数据库查询 ────────────────────────────────────────────────────────────

def _fetch_income(conn, ts_code: str, n: int = 5) -> pd.DataFrame:
    return pd.read_sql(text("""
        SELECT end_date, revenue, n_income_attr_p
        FROM income_statement
        WHERE ts_code = :c ORDER BY end_date DESC LIMIT :n
    """), conn, params={"c": ts_code, "n": n}).fillna(0)


def _fetch_cashflow(conn, ts_code: str, n: int = 5) -> pd.DataFrame:
    return pd.read_sql(text("""
        SELECT end_date, n_cashflow_act, c_pay_acq_const_fiolta
        FROM cash_flow_statement
        WHERE ts_code = :c ORDER BY end_date DESC LIMIT :n
    """), conn, params={"c": ts_code, "n": n}).fillna(0)


def _fetch_balance(conn, ts_code: str) -> pd.Series:
    df = pd.read_sql(text("""
        SELECT money_cap, st_borr, lt_borr,
               total_hldr_eqy_exc_min_int, total_hldr_eqy_inc_min_int
        FROM balance_sheet
        WHERE ts_code = :c ORDER BY end_date DESC LIMIT 1
    """), conn, params={"c": ts_code})
    return df.iloc[0] if not df.empty else pd.Series(dtype=float)


def _revenue_cagr(income_df: pd.DataFrame) -> float:
    if len(income_df) < 2:
        return 0.05
    revs = income_df["revenue"].values[::-1]
    if revs[0] <= 0:
        return 0.05
    cagr = (revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1
    return float(max(min(cagr, 0.25), -0.10))


def _dcf_ev(base_fcf: float, g: float) -> float:
    pv    = sum(base_fcf * (1 + g) ** t / (1 + WACC) ** t for t in range(1, YEARS + 1))
    tv_pv = (base_fcf * (1 + g) ** YEARS * (1 + TERMINAL_GROWTH)
             / (WACC - TERMINAL_GROWTH)) / (1 + WACC) ** YEARS
    return pv + tv_pv


# ── 估值方法 ──────────────────────────────────────────────────────────────

def _pb_roe(conn, ts_code: str, total_shares_wan: float, current_price: float = None) -> dict:
    """P/B + ROE 戈登增长（银行/保险/证券/地产）。"""
    income_df = _fetch_income(conn, ts_code, 3)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty or bs.empty:
        return {"error": "缺少净资产或利润数据"}

    equity = _to_float(bs.get("total_hldr_eqy_exc_min_int")) or \
             _to_float(bs.get("total_hldr_eqy_inc_min_int"))
    if equity <= 0:
        return {"error": "净资产为零或负"}

    net_profit = float(income_df.iloc[0]["n_income_attr_p"])
    roe        = net_profit / equity
    g          = TERMINAL_GROWTH
    fair_pb    = (roe - g) / (WACC - g) if (WACC > g and roe > g) else 1.0
    fair_pb    = max(0.3, min(fair_pb, 6.0))

    total_shares   = total_shares_wan * 1e4
    book_per_share = equity / total_shares
    fair_per_share = fair_pb * book_per_share
    cur_pb         = (current_price / book_per_share) if (current_price and book_per_share > 0) else None

    return {
        "方法":          "P/B+ROE",
        "公式":          "合理P/B = (ROE - g) / (WACC - g); 价值 = P/B × 每股净资产",
        "fair_per_share": round(fair_per_share, 2),
        "fair_pb":        round(fair_pb, 2),
        "cur_pb":         round(cur_pb, 2) if cur_pb else None,
        "roe_pct":        round(roe * 100, 1),
        "book_per_share": round(book_per_share, 2),
        "base_fcf_yi":    round(net_profit / 1e8, 2),
        "growth_rate":    g,
        "ev_yi": None, "cash_yi": None, "debt_yi": None,
    }


def _dcf_capex(conn, ts_code: str, total_shares_wan: float) -> dict:
    """DCF 扣减资本开支（重资产行业）。"""
    income_df = _fetch_income(conn, ts_code)
    cf_df     = _fetch_cashflow(conn, ts_code)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    fcf = 0.0
    if not cf_df.empty:
        ocf   = float(cf_df.iloc[0]["n_cashflow_act"] or 0)
        capex = abs(float(cf_df.iloc[0]["c_pay_acq_const_fiolta"] or 0))
        fcf   = ocf - capex
    if fcf <= 0:
        fcf = float(income_df.iloc[0]["n_income_attr_p"]) * 0.6

    g    = _revenue_cagr(income_df)
    ev   = _dcf_ev(fcf, g)
    cash = _to_float(bs.get("money_cap")) if not bs.empty else 0
    debt = (_to_float(bs.get("st_borr")) + _to_float(bs.get("lt_borr"))) if not bs.empty else 0

    equity_val     = ev + cash - debt
    fair_per_share = equity_val / (total_shares_wan * 1e4) if total_shares_wan > 0 else None

    return {
        "方法":          "DCF(OCF−capex)",
        "公式":          "FCF = 经营现金流 - 资本支出; 价值 = 折现FCF + 净现金",
        "fair_per_share": round(fair_per_share, 2) if fair_per_share else None,
        "base_fcf_yi":   round(fcf / 1e8, 2),
        "growth_rate":   round(g, 4),
        "ev_yi":         round(ev / 1e8, 1),
        "cash_yi":       round(cash / 1e8, 1),
        "debt_yi":       round(debt / 1e8, 1),
    }


def _dcf_cycle(conn, ts_code: str, total_shares_wan: float) -> dict:
    """穿越周期 DCF（强周期行业，取近3年FCF均值平滑）。"""
    income_df = _fetch_income(conn, ts_code, 5)
    cf_df     = _fetch_cashflow(conn, ts_code, 5)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    fcf_list = []
    for _, row in cf_df.head(3).iterrows():
        ocf   = float(row["n_cashflow_act"] or 0)
        capex = abs(float(row["c_pay_acq_const_fiolta"] or 0))
        f     = ocf - capex
        if f > 0:
            fcf_list.append(f)

    if fcf_list:
        fcf = sum(fcf_list) / len(fcf_list)
    else:
        net_profit = float(income_df.iloc[0]["n_income_attr_p"])
        fcf = max(net_profit * 0.4, 0.0)

    g  = max(min(_revenue_cagr(income_df), 0.12), -0.05)
    ev = _dcf_ev(fcf, g)

    cash = _to_float(bs.get("money_cap")) if not bs.empty else 0
    debt = (_to_float(bs.get("st_borr")) + _to_float(bs.get("lt_borr"))) if not bs.empty else 0

    equity_val     = ev + cash - debt
    fair_per_share = equity_val / (total_shares_wan * 1e4) if total_shares_wan > 0 else None

    return {
        "方法":          f"穿越周期DCF(n={len(fcf_list)}年均值)",
        "公式":          "FCF = 近3年(OCF - 资本支出)均值; 价值 = 折现FCF + 净现金",
        "fair_per_share": round(fair_per_share, 2) if fair_per_share else None,
        "base_fcf_yi":   round(fcf / 1e8, 2),
        "growth_rate":   round(g, 4),
        "ev_yi":         round(ev / 1e8, 1),
        "cash_yi":       round(cash / 1e8, 1),
        "debt_yi":       round(debt / 1e8, 1),
    }


def _dcf_std(conn, ts_code: str, total_shares_wan: float) -> dict:
    """标准 DCF（稳定现金流行业）。"""
    income_df = _fetch_income(conn, ts_code)
    cf_df     = _fetch_cashflow(conn, ts_code)
    bs        = _fetch_balance(conn, ts_code)

    if income_df.empty:
        return {"error": "缺少利润数据"}

    fcf = 0.0
    if not cf_df.empty:
        ocf = float(cf_df.iloc[0]["n_cashflow_act"] or 0)
        if ocf > 0:
            fcf = ocf
    if fcf <= 0:
        fcf = float(income_df.iloc[0]["n_income_attr_p"]) * 0.8

    g  = _revenue_cagr(income_df)
    ev = _dcf_ev(fcf, g)

    cash = _to_float(bs.get("money_cap")) if not bs.empty else 0
    debt = (_to_float(bs.get("st_borr")) + _to_float(bs.get("lt_borr"))) if not bs.empty else 0

    equity_val     = ev + cash - debt
    fair_per_share = equity_val / (total_shares_wan * 1e4) if total_shares_wan > 0 else None

    return {
        "方法":          "标准DCF",
        "公式":          "FCF = 经营现金流; 价值 = 折现FCF + 净现金",
        "fair_per_share": round(fair_per_share, 2) if fair_per_share else None,
        "base_fcf_yi":   round(fcf / 1e8, 2),
        "growth_rate":   round(g, 4),
        "ev_yi":         round(ev / 1e8, 1),
        "cash_yi":       round(cash / 1e8, 1),
        "debt_yi":       round(debt / 1e8, 1),
    }


# ── 统一估值入口 ──────────────────────────────────────────────────────────

class UnifiedValuation:
    def __init__(self):
        self.engine = create_engine(DB_URL)

    def calc(self, ts_code: str, industry: str,
             total_shares_wan: float, current_price: float = None) -> dict:
        method = INDUSTRY_METHOD.get(industry, "dcf_std")
        with self.engine.connect() as conn:
            try:
                if method == "pb_roe":
                    r = _pb_roe(conn, ts_code, total_shares_wan, current_price)
                elif method == "dcf_capex":
                    r = _dcf_capex(conn, ts_code, total_shares_wan)
                elif method == "dcf_cycle":
                    r = _dcf_cycle(conn, ts_code, total_shares_wan)
                else:
                    r = _dcf_std(conn, ts_code, total_shares_wan)
            except Exception as e:
                r = {"error": str(e)}
        r["ts_code"]  = ts_code
        r["industry"] = industry
        r.setdefault("方法", method)
        return r


# ── 从数据库读取行情和基础信息 ────────────────────────────────────────────

def load_market_data(db_engine) -> dict:
    """从 stock_daily_hist 取最新收盘价，从 balance_sheet 取最新总股本。"""
    with db_engine.connect() as conn:
        # 最新一日收盘价
        price_df = pd.read_sql(text("""
            SELECT ts_code, close
            FROM stock_daily_hist
            WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_hist)
        """), conn)
        # 最新总股本（单位：股 → 转万股）
        share_df = pd.read_sql(text("""
            SELECT DISTINCT ON (ts_code) ts_code,
                   total_share / 1e4 AS total_share_wan
            FROM balance_sheet
            WHERE total_share IS NOT NULL
            ORDER BY ts_code, end_date DESC
        """), conn)
    price_map = dict(zip(price_df["ts_code"], price_df["close"].astype(float)))
    share_map = dict(zip(share_df["ts_code"], share_df["total_share_wan"].astype(float)))
    return price_map, share_map


def load_stock_info(db_engine) -> dict:
    """从 stock_basic 读取股票名称和行业。"""
    with db_engine.connect() as conn:
        df = pd.read_sql(text("SELECT ts_code, name, industry FROM stock_basic"), conn)
    return {r["ts_code"]: r for r in df.to_dict("records")}


def load_hs300_codes(db_engine) -> list:
    """从 index_components 读取沪深300成分股。"""
    with db_engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT ts_code FROM index_components
            WHERE index_code = '000300.SH'
            ORDER BY weight DESC
        """), conn)
    return df["ts_code"].tolist()


# ── 主流程：HS300 批量估值 ────────────────────────────────────────────────

if __name__ == "__main__":
    from sqlalchemy import create_engine as _ce
    _db = _ce(DB_URL)

    print("1. 读取最新行情（收盘价 + 总股本）...")
    price_map, share_map = load_market_data(_db)
    print(f"   收盘价 {len(price_map)} 只 / 股本 {len(share_map)} 只")

    print("2. 读取股票名称和行业...")
    stock_info = load_stock_info(_db)
    print(f"   共 {len(stock_info)} 只")

    print("3. 读取沪深300成分股名单...")
    codes = load_hs300_codes(_db)
    print(f"   共 {len(codes)} 只\n")

    print("4. 批量估值中...\n")
    engine  = UnifiedValuation()
    results = []

    for i, code in enumerate(codes, 1):
        price  = price_map.get(code)
        shares = share_map.get(code)
        if not price or not shares:
            print(f"[{i:>3}/{len(codes)}] {code}  缺少行情或股本数据，跳过")
            continue

        si       = stock_info.get(code, {})
        name     = si.get("name", "")
        industry = si.get("industry", "")

        r   = engine.calc(code, industry, shares, current_price=price)
        if "error" in r:
            print(f"[{i:>3}/{len(codes)}] {code}  {r['error']}")
            continue

        fv     = r["fair_per_share"]
        gap    = round((fv / price - 1) * 100, 1) if (fv is not None and price) else None
        mc_yi  = round(price * shares * 1e4 / 1e8, 1)
        results.append({
            "ts_code":        code,
            "名称":           name,
            "行业":           industry,
            "估值方法":       r["方法"],
            "当前价":         price,
            "估值":           fv,
            "空间%":          gap,
            "市值亿":         mc_yi,
            "基准FCF/净利亿": r.get("base_fcf_yi"),
            "增长率%":        round(r.get("growth_rate", 0) * 100, 1) if r.get("growth_rate") is not None else None,
            "EV亿":           r.get("ev_yi"),
            "净债务亿":       round((r.get("debt_yi") or 0) - (r.get("cash_yi") or 0), 1)
                              if r.get("debt_yi") is not None else None,
            "当前PB":         r.get("cur_pb"),
            "合理PB":         r.get("fair_pb"),
            "ROE%":           r.get("roe_pct"),
            "每股净资产":     r.get("book_per_share"),
        })
        print(f"[{i:>3}/{len(codes)}] {code} {name:<6} [{r['方法'][:10]}]  "
              f"现价={price}  估值={fv}  空间={gap}%", flush=True)

    # ── 排序输出 ──────────────────────────────────────────────────────────
    results.sort(key=lambda x: x["空间%"] or -999, reverse=True)

    print(f"\n{'='*80}")
    print(f"  HS300 多方法估值汇总（按上行空间排序）共 {len(results)} 只")
    print(f"{'='*80}")
    print(f"{'代码':<12}{'名称':<8}{'行业':<8}{'方法':<14}{'当前价':>7}{'估值':>8}{'空间':>7}")
    print("-" * 70)
    for r in results:
        gap_s = f"{r['空间%']:+.1f}%" if r['空间%'] is not None else "N/A"
        fv_s  = f"{r['估值']:.2f}"   if r['估值']  is not None else "N/A"
        print(f"{r['ts_code']:<12}{r['名称']:<8}{r['行业']:<8}"
              f"{r['估值方法'][:12]:<14}{r['当前价']:>6.2f}元"
              f"{fv_s:>8}元  {gap_s:>7}")

    # ── 导出 CSV ──────────────────────────────────────────────────────────
    os.makedirs("data", exist_ok=True)
    out = "data/valuation_hs300.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=results[0].keys())
        w.writeheader()
        w.writerows(results)
    print(f"\n已导出: {out}")

    # ── 方法分布统计 ──────────────────────────────────────────────────────
    method_cnt = Counter(r["估值方法"].split("(")[0].strip() for r in results)
    print("\n估值方法分布：")
    for m, c in method_cnt.most_common():
        print(f"  {m:<20} {c} 只")
