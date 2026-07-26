from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Backup:
    status: str
    postgres_major: int
    app_version: str

    def assert_restorable(self, *, expected_app: str, expected_postgres: int) -> None:
        if self.status != "ready":
            raise ValueError("backup is not ready")
        if self.postgres_major != expected_postgres:
            raise ValueError("backup PostgreSQL major version is incompatible")
        if not self.app_version.startswith(expected_app):
            raise ValueError("backup application version is incompatible")
