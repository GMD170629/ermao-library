from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, text

from appv2.modules.operations.contracts import HealthStatus


class DatabaseHealth:
    name = "database"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def check(self) -> HealthStatus:
        checked_at = datetime.now(UTC)
        try:
            with self._engine.connect() as connection:
                version = str(connection.execute(text("SHOW server_version")).scalar_one())
            major = int(version.split(".", 1)[0])
            status = "healthy" if major == 18 else "degraded"
            return HealthStatus(
                name=self.name,
                status=status,
                checked_at=checked_at,
                detail={"serverVersion": version, "requiredMajor": 18},
            )
        except Exception as error:
            return HealthStatus(
                name=self.name,
                status="failed",
                checked_at=checked_at,
                detail={"error": type(error).__name__},
            )
