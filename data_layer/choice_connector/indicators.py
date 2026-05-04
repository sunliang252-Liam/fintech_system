"""
Choice常用财务指标简称对照表
用于fintech_system财报分析模块
"""

# ── 利润表 ────────────────────────────────────────────────────────────────
INCOME = {
    "TOTALOPERATEREVE":       "营业总收入",
    "OPERATEREVE":            "营业收入",
    "OPERATECOST":            "营业成本",
    "GROSSPROFIT":            "毛利润",
    "NETPROFIT":              "净利润",
    "PARENTNETPROFIT":        "归母净利润",
    "DEDUCTNETPROFIT":        "扣非净利润",
    "BASICEPS":               "基本EPS",
    "DILUTEDEPS":             "稀释EPS",
}

# ── 资产负债表 ─────────────────────────────────────────────────────────────
BALANCE = {
    "TOTALASSETS":            "总资产",
    "TOTALLIAB":              "总负债",
    "CONTRACTLIABILITY":      "合同负债",          # 核心指标：航发动力
    "ADVANCERECEIPTBIL":      "预收账款",
    "TOTALCURRENTASSETS":     "流动资产合计",
    "TOTALCURRENTLIAB":       "流动负债合计",
    "EQUITY":                 "净资产",
    "TOTALSHARE":             "总股本",
    "FREESHARE":              "流通股本",
    "INTERESTBEARDEBT":       "有息负债",
}

# ── 现金流量表 ─────────────────────────────────────────────────────────────
CASHFLOW = {
    "OPERATECASHFLOW":        "经营现金流净额",
    "INVESTCASHFLOW":         "投资现金流净额",
    "FINANCECASHFLOW":        "筹资现金流净额",
    "CAPITALEXPEND":          "资本支出",
    "FREECASHFLOW":           "自由现金流",
}

# ── 财务比率 ──────────────────────────────────────────────────────────────
RATIO = {
    "ROEAVG":                 "ROE（平均）",
    "ROAAVG":                 "ROA（平均）",
    "GROSSPROFITMARGIN":      "毛利率",
    "NETPROFITMARGIN":        "净利率",
    "ASSETSLIABILITYRATIO":   "资产负债率",
    "CURRENTRATIO":           "流动比率",
    "DEBTTOEBITDA":           "有息债务/EBITDA",
}

# ── 估值指标 ──────────────────────────────────────────────────────────────
VALUATION = {
    "PE":                     "市盈率（TTM）",
    "PELYR":                  "市盈率（静态）",
    "PB":                     "市净率",
    "PS":                     "市销率",
    "MARKETCAP":              "总市值",
    "NEGOTIABLEMV":           "流通市值",
}

# ── 增长率 ────────────────────────────────────────────────────────────────
GROWTH = {
    "NETPROFITRATE":          "净利润同比增长率",
    "OPERATEREVEGRADE":       "营收同比增长率",
    "CONTRACTLIABILITYRATE":  "合同负债同比增长率",  # 航发动力核心监控
    "EPSGROWTH":              "EPS增长率",
}

# ── 预设组合（常用于fintech_system） ─────────────────────────────────────

# 航发动力核心监控指标组
AEROENGINE_CORE = [
    "NETPROFIT",
    "PARENTNETPROFIT",
    "DEDUCTNETPROFIT",
    "CONTRACTLIABILITY",
    "CONTRACTLIABILITYRATE",
    "OPERATECASHFLOW",
    "GROSSPROFITMARGIN",
    "ROEAVG",
    "PE",
    "PB",
]

# 航空公司监控指标组（春秋航空601021）
AIRLINE_CORE = [
    "OPERATEREVE",
    "OPERATECOST",
    "NETPROFIT",
    "GROSSPROFITMARGIN",
    "NETPROFITMARGIN",
    "ASSETSLIABILITYRATIO",
    "OPERATECASHFLOW",
    "FREECASHFLOW",
    "PE",
]

# 通用财报快照组
REPORT_SNAPSHOT = [
    "OPERATEREVE",
    "NETPROFIT",
    "DEDUCTNETPROFIT",
    "CONTRACTLIABILITY",
    "OPERATECASHFLOW",
    "GROSSPROFITMARGIN",
    "ROEAVG",
    "ASSETSLIABILITYRATIO",
    "BASICEPS",
    "PE",
    "PB",
]

# ── 板块代码 ──────────────────────────────────────────────────────────────
SECTORS = {
    "全部A股":      "B_001004",
    "上证A股":      "B_001005",
    "深证A股":      "B_001006",
    "创业板":       "B_001010",
    "沪深300":      "B_009006195",
    "中证500":      "B_009006062",
    "中证1000":     "B_009007552",
    "上证50":       "B_009007063",
    "沪股通":       "B_001038",
    "深股通":       "B_001041",
}
