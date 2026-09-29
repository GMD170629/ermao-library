from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_root: Path = Path("./data")
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""

    model_config = SettingsConfigDict(env_prefix="FEEDBACK_", extra="ignore")

    def validate_delivery(self) -> None:
        if not all((self.smtp_host, self.smtp_username, self.smtp_password, self.smtp_from, self.smtp_to)):
            raise RuntimeError("Feedback SMTP configuration is incomplete")
