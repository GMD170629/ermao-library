from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "二毛图书 API"
    app_version: str = "0.5.5"
    session_secret: str | None = None
    storage_root: str = "/app/storage"
    secure_cookies: bool = False
    cookie_path: str = "/"
    download_queue_enabled: bool = True
    download_queue_interval_seconds: int = Field(default=5, ge=1)
    kindle_send_queue_enabled: bool = True
    kindle_send_queue_interval_seconds: int = Field(default=5, ge=1)
    import_queue_interval_seconds: int = Field(default=2, ge=1)
    library_scan_interval_ms: int | None = Field(default=None, ge=1)
    metadata_opf_queue_max_pending: int = Field(default=50_000, ge=1, le=1_000_000)
    audiobook_max_file_bytes: int = Field(
        default=8 * 1024 * 1024 * 1024, ge=1024 * 1024
    )
    audiobook_max_bundle_bytes: int = Field(
        default=8 * 1024 * 1024 * 1024, ge=1024 * 1024
    )
    file_streams_per_user_limit: int = Field(default=8, ge=0, le=128)
    opds_page_size: int = Field(default=50, ge=1, le=100)
    opds_max_page_size: int = Field(default=100, ge=1, le=100)
    opds_auth_cache_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    opds_auth_cache_capacity: int = Field(default=4096, ge=1, le=65536)
    opds_auth_identity_failures: int = Field(default=5, ge=1, le=100)
    opds_auth_identity_window_seconds: int = Field(default=300, ge=1, le=3600)
    opds_auth_ip_failures: int = Field(default=30, ge=1, le=1000)
    opds_auth_ip_window_seconds: int = Field(default=60, ge=1, le=3600)
    qbittorrent_url: str | None = None
    qbittorrent_username: str | None = None
    qbittorrent_password: str | None = None
    qbittorrent_category: str | None = None
    qbittorrent_save_path: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_opds_configuration(self) -> Settings:
        if self.opds_page_size > self.opds_max_page_size:
            raise ValueError("OPDS_PAGE_SIZE cannot exceed OPDS_MAX_PAGE_SIZE")
        return self

    @property
    def resolved_storage_root(self) -> Path:
        return Path(self.storage_root).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self.resolved_storage_root / "database" / "shuku.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
