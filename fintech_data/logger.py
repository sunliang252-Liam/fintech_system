"""fintech_data/logger.py — 统一日志工厂"""
import logging
from pathlib import Path
from . import config


def get(name: str) -> logging.Logger:
    """返回已配置好的 logger，同时写文件和 stdout。"""
    log_file = config.LOG_DIR / f"{name}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"fintech.{name}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger
