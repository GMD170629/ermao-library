from __future__ import annotations

import json
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import Settings
from .contracts import Submission


def send_feedback(settings: Settings, receipt_id: str, submission: Submission, files: list[tuple[str, str, Path]]) -> None:
    settings.validate_delivery()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = settings.smtp_to
    category = "Problem report / 问题反馈" if submission.kind == "issue" else "Feature suggestion / 功能建议"
    message["Subject"] = f"[Ermao feedback / 二毛图书反馈] {receipt_id} · {category}"
    message["Message-ID"] = f"<{receipt_id.lower()}@embook.xyz>"
    body = (
        f"Feedback ID / 反馈编号：{receipt_id}\nType / 类型：{category}\n"
        f"QQ：{submission.contact.qq or 'Not provided / 未填写'}\n"
        f"Official group nickname / 官方交流群昵称：{submission.contact.group_name or 'Not provided / 未填写'}\n"
        f"Contact email / 联系邮箱：{submission.contact.email or 'Not provided / 未填写'}\n\n"
        f"{submission.markdown}\n\n"
        f"Diagnostics / 诊断信息：\n{json.dumps(submission.diagnostics, ensure_ascii=False, indent=2)}\n"
    )
    message.set_content(body)
    for filename, media_type, path in files:
        major, minor = media_type.split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=major, subtype=minor, filename=filename)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=25) as client:
        client.starttls(context=ssl.create_default_context())
        client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
