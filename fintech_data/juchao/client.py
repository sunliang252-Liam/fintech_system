"""juchao/client.py — 巨潮网 HTTP 客户端封装"""
from __future__ import annotations
import requests
from .. import config

_session: requests.Session | None = None

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "http://www.cninfo.com.cn/",
}


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def search_announcement(symbol: str, date: str, keyword: str = "年度报告") -> str | None:
    """在巨潮搜索指定股票某日的年报公告，返回 announcementId 或 None。"""
    f_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    params = {
        "stock":       symbol,
        "searchkey":   f"2025{keyword}",
        "category":    "category_ndbg_szsh",
        "pageNum":     1,
        "pageSize":    5,
        "tabName":     "fulltext",
        "seDate":      f"{f_date}~{f_date}",
    }
    url = f"{config.JUCHAO['base_url']}/new/disclosure"
    try:
        r = get_session().post(url, data=params, timeout=config.JUCHAO["timeout"])
        r.raise_for_status()
        for ann in r.json().get("announcements", []):
            title = ann.get("announcementTitle", "")
            if "2025" in title and "年度报告" in title and "摘要" not in title:
                return ann["announcementId"]
    except Exception:
        pass
    return None


def build_pdf_url(ann_id: str, date: str) -> str:
    formatted = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return f"{config.JUCHAO['static_url']}/finalpage/{formatted}/{ann_id}.PDF"
