"""
data_layer/main.py — L1 数据层统一入口

用法：
    from data_layer.main import get_pro, get_choice

    # Turshare（本地 PostgreSQL）
    pro = get_pro()
    df  = pro.daily(ts_code="600893.SH", start_date="20240101")
    df  = pro.pro_bar(ts_code="600893.SH", adj="qfq")
    df  = pro.income(ts_code="600893.SH")

    # Choice（东方财富，需在大陆 IP 环境）
    choice = get_choice()
    choice.login()
    df = choice.get_css("600893.SH", ["NETPROFIT", "CONTRACTLIABILITY"], "20241231")
    choice.logout()
"""

from .turshare_connector import pro_api, LocalProAPI
from .choice_connector import ChoiceConnector
from .downloader import download_stock, download_batch


def get_pro(**pg_kwargs) -> LocalProAPI:
    """返回本地 PostgreSQL 数据接口实例。"""
    return pro_api(**pg_kwargs)


def get_choice() -> ChoiceConnector:
    """返回东方财富 Choice 数据接口实例（需手动调用 login）。"""
    return ChoiceConnector()
