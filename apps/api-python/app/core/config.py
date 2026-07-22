from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "二毛图书 API"
    app_version: str = "0.2.1"
    session_secret: str | None = None
    monitor_root: str | None = "/monitor"
    storage_root: str = "/app/storage"
    secure_cookies: bool = False
    cookie_path: str = "/"
    download_queue_enabled: bool = True
    download_queue_interval_seconds: int = Field(default=5, ge=1)
    kindle_send_queue_enabled: bool = True
    kindle_send_queue_interval_seconds: int = Field(default=5, ge=1)
    import_queue_interval_seconds: int = Field(default=2, ge=1)
    libmobi_bin: str = "mobitool"
    ebook_conversion_enabled: bool = True
    ebook_conversion_timeout_seconds: int = Field(default=600, ge=10, le=3600)
    ebook_conversion_max_output_bytes: int = Field(default=768 * 1024 * 1024, ge=1024 * 1024)
    audiobook_max_file_bytes: int = Field(default=8 * 1024 * 1024 * 1024, ge=1024 * 1024)
    audiobook_max_bundle_bytes: int = Field(default=8 * 1024 * 1024 * 1024, ge=1024 * 1024)
    file_streams_per_user_limit: int = Field(default=8, ge=0, le=128)
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

    @property
    def resolved_storage_root(self) -> Path:
        return Path(self.storage_root).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self.resolved_storage_root / "database" / "shuku.sqlite3"

    @property
    def resolved_monitor_root(self) -> Path | None:
        if not self.monitor_root:
            return None
        return Path(self.monitor_root).expanduser().resolve()

    @property
    def conversion_root(self) -> Path:
        return self.resolved_storage_root / "conversions"

    @property
    def conversion_temp_root(self) -> Path:
        return self.resolved_storage_root / "temp" / "conversions"


@lru_cache
def get_settings() -> Settings:
    return Settings()
