from __future__ import annotations

import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from appv2.modules.delivery.contracts import DeliverableFile, SmtpConfiguration, SmtpPort


class SmtpAdapter(SmtpPort):
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout = timeout_seconds

    def test(self, configuration: SmtpConfiguration, recipient: str) -> None:
        message = EmailMessage()
        message["From"] = configuration.sender
        message["To"] = recipient
        message["Subject"] = "Shuku Starship SMTP test"
        message.set_content("SMTP configuration is working.")
        self._send_message(configuration, message)

    def send(
        self,
        configuration: SmtpConfiguration,
        *,
        recipient: str,
        subject: str,
        file: DeliverableFile,
    ) -> None:
        path = Path(file.path)
        message = EmailMessage()
        message["From"] = configuration.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content("Sent by Shuku Starship.")
        media_type = (
            file.media_type or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        )
        main_type, sub_type = media_type.split("/", 1)
        with path.open("rb") as source:
            message.add_attachment(
                source.read(),
                maintype=main_type,
                subtype=sub_type,
                filename=file.name,
            )
        self._send_message(configuration, message)

    def _send_message(self, configuration: SmtpConfiguration, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        with smtplib.SMTP(configuration.host, configuration.port, timeout=self._timeout) as client:
            if configuration.use_tls:
                client.starttls(context=context)
            if configuration.username:
                client.login(configuration.username, configuration.password or "")
            client.send_message(message)
