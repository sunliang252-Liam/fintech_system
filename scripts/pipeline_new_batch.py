#!/usr/bin/env python3
"""
pipeline_new_batch.py
等待 pdf_to_md 完成后，依次执行：
  1. extract_supplements.py  — 提取数字字段入库
  2. run_deepseek_v3.py      — DeepSeek 推理 + Obsidian 回写
  3. 发邮件通知
"""

import subprocess
import sys
import time
import logging
import psutil
from pathlib import Path
from datetime import datetime

SCRIPTS = Path(__file__).parent
LOG     = Path.home() / "annual_reports/logs/pipeline_new_batch.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG, encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)


def is_running(script_name: str) -> bool:
    for p in psutil.process_iter(["cmdline"]):
        try:
            if any(script_name in c for c in p.info["cmdline"]):
                return True
        except Exception:
            pass
    return False


def run_step(name: str, script: str):
    log.info(f"▶ 开始: {name}")
    t0 = time.time()
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script)],
        cwd=str(SCRIPTS)
    )
    elapsed = (time.time() - t0) / 60
    if result.returncode == 0:
        log.info(f"✅ 完成: {name}（{elapsed:.1f} 分钟）")
    else:
        log.error(f"❌ 失败: {name}（returncode={result.returncode}）")
    return result.returncode == 0


def notify(subject: str, body: str):
    try:
        sys.path.insert(0, str(SCRIPTS))
        from notify_email import send
        send(subject, body)
    except Exception as e:
        log.error(f"邮件发送失败: {e}")


def main():
    log.info("=" * 50)
    log.info("pipeline_new_batch 启动")

    # Step 0: 等待 pdf_to_md 跑完
    log.info("等待 pdf_to_md.py 完成...")
    while is_running("pdf_to_md.py"):
        time.sleep(30)
    log.info("pdf_to_md.py 已完成，开始后续流程")

    results = {}

    # Step 1: extract_supplements
    results["supplements"] = run_step(
        "提取附注数字字段", "extract_supplements.py"
    )

    # Step 2: run_deepseek_v3
    results["deepseek"] = run_step(
        "DeepSeek 推理分析", "run_deepseek_v3.py"
    )

    # 汇总并发送通知
    ok = all(results.values())
    status = "✅ 全部完成" if ok else "⚠️ 部分失败"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    body = f"""fintech 年报分析系统流水线完成

时间：{now}
pdf→MD 转换：✅
附注字段提取：{"✅" if results.get("supplements") else "❌"}
DeepSeek 推理：{"✅" if results.get("deepseek") else "❌"}

日志路径：{LOG}
"""
    notify(f"{status} — fintech 年报分析流水线", body)
    log.info("pipeline 结束")


if __name__ == "__main__":
    main()
