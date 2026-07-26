from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "二毛图书 API"
    app_version: str = "0.4.0"
    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr("postgresql+psycopg://shuku:shuku@postgres:5432/shuku_v2")
    session_secret: SecretStr = SecretStr("development-only-change-me")
    storage_root: Path = Path("/app/storage")
    monitor_root: Path | None = Path("/monitor")
    secure_cookies: bool = False
    cookie_path: str = "/"
    allowed_origins: tuple[str, ...] = ()
    default_locale: Literal["zh-CN", "en-US"] = "zh-CN"
    session_ttl_seconds: int = Field(default=30 * 24 * 60 * 60, ge=300)
    password_reset_ttl_seconds: int = Field(default=30 * 60, ge=300, le=24 * 60 * 60)
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    worker_lease_seconds: int = Field(default=300, ge=30, le=3600)
    monitor_stability_seconds: float = Field(default=2.0, ge=0, le=300)
    monitor_refresh_interval_ms: int = Field(default=60_000, ge=500, le=86_400_000)
    file_streams_per_user_limit: int = Field(default=8, ge=1, le=128)
    migration_lock_id: int = 830_400
    worker_lock_id: int = 830_401
    backup_lock_id: int = 830_402
    smtp_timeout_seconds: int = Field(default=30, ge=1, le=300)
    external_http_timeout_seconds: int = Field(default=20, ge=1, le=120)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if not url.startswith(("postgresql+psycopg://", "postgresql://")):
            raise ValueError("appv2 requires PostgreSQL through psycopg")
        return value

    @property
    def database_dsn(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def v2_storage_root(self) -> Path:
        return self.storage_root.expanduser().resolve() / "v2"

    @property
    def covers_root(self) -> Path:
        return self.v2_storage_root / "covers"

    @property
    def conversions_root(self) -> Path:
        return self.v2_storage_root / "conversions"

    @property
    def temp_root(self) -> Path:
        return self.v2_storage_root / "temp"

    @property
    def backups_root(self) -> Path:
        return self.v2_storage_root / "backups"

    @property
    def control_root(self) -> Path:
        return self.v2_storage_root / "control"

    @property
    def logs_root(self) -> Path:
        return self.v2_storage_root / "logs"

    @property
    def secrets_root(self) -> Path:
        return self.v2_storage_root / "secrets"


@lru_cache
def get_settings() -> Settings:
    return Settings()
