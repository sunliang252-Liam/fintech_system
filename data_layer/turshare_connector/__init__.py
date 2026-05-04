"""
data_layer/turshare_connector/
─────────────────────────────
本地 Turshare-like 查询接口，底层读 PostgreSQL。

快速开始：
    from data_layer.turshare_connector import pro_api
    pro = pro_api()
    df  = pro.daily(ts_code="600893.SH", start_date="20240101")
    df  = pro.pro_bar(ts_code="600893.SH", adj="qfq")
    df  = pro.income(ts_code="600893.SH", period="20241231")
"""

from .client import LocalProAPI, pro_api
from . import db

__all__ = ["pro_api", "LocalProAPI", "db"]
