"""
notify_email.py — 发送任务完成通知邮件
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

RECEIVERS = ["sunliang252@gmail.com", "8407020@qq.com"]

ACCOUNTS = [
    {"host": "smtp.gmail.com", "port": 465,
     "user": "sunliang252@gmail.com", "password": "byunvkndsegjkktx"},
    {"host": "smtp.qq.com",    "port": 465,
     "user": "8407020@qq.com",        "password": "rqpkzvkguebqcbbd"},
]


def send(subject: str, body: str):
    msg = MIMEMultipart()
    msg["To"]      = ", ".join(RECEIVERS)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for acc in ACCOUNTS:
        try:
            msg["From"] = acc["user"]
            with smtplib.SMTP_SSL(acc["host"], acc["port"]) as s:
                s.login(acc["user"], acc["password"])
                s.sendmail(acc["user"], RECEIVERS, msg.as_string())
            print(f"[notify] 邮件已发送 via {acc['host']}: {subject}")
            return
        except Exception as e:
            print(f"[notify] {acc['host']} 失败: {e}，尝试下一个...")
    print("[notify] ❌ 所有邮件账号均失败")


if __name__ == "__main__":
    send(
        subject="✅ 测试邮件",
        body=f"fintech 系统通知测试 — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
