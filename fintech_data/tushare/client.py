"""fintech_data/tushare/client.py — Tushare API 单例"""
from __future__ import annotations
import json
import time
import urllib.request
from .. import config

_pro = None


def get_pro():
    """返回 tushare pro_api 实例（懒加载）。"""
    global _pro
    if _pro is None:
        import tushare as ts
        ts.set_token(config.TUSHARE_TOKEN)
        _pro = ts.pro_api()
    return _pro


def ts_post(api_name: str, **params) -> list[dict]:
    """直接走 HTTP POST，不依赖 tushare 包，用于无 SDK 环境。"""
    url = "https://api.tushare.pro"
    payload = json.dumps({
        "api_name": api_name,
        "token": config.TUSHARE_TOKEN,
        "params": params,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    if res.get("code") != 0:
        raise RuntimeError(f"[{api_name}] {res.get('msg')}")
    fields = res["data"]["fields"]
    return [dict(zip(fields, row)) for row in res["data"]["items"]]
