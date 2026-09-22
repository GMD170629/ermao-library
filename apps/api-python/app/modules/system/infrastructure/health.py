"""Lightweight system health probe checks."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exception_diagnostics import record_exception
from app.models.library import Library
from app.modules.system.domain.health import (
    HealthCheckFailure,
    health_check_item,
    overall_health_status,
)


def _env_check(name: str, value: str | None, required: bool = True) -> dict[str, str]:
    if required and not value:
        record_exception(
            logging.getLogger(__name__),
            "system.health_configuration_missing",
            HealthCheckFailure(f"Required configuration {name} is absent"),
            context={"stage": "health_configuration", "resource_id": name},
        )
        return health_check_item(name, "error", f"{name} 未配置")
    return health_check_item(
        name, "ok" if value else "unknown", "已配置" if value else "未配置"
    )


def _check_libraries(paths: list[tuple[str, Path]]) -> dict[str, str]:
    if not paths:
        return health_check_item("libraryRootsReadable", "unknown", "未启用书库")
    for library_id, path in paths:
        if not path.exists() or not path.is_dir():
            record_exception(
                logging.getLogger(__name__),
                "system.health_library_unavailable",
                HealthCheckFailure(
                    "Enabled library root does not exist or is not a directory"
                ),
                context={"stage": "library_root_probe", "library_id": library_id},
            )
            return health_check_item(
                "libraryRootsReadable", "warning", f"书库不存在：{path}"
            )
        try:
            next(path.iterdir(), None)
        except OSError as exc:
            record_exception(
                logging.getLogger(__name__),
                "modules.system.infrastructure.health._check_libraries.failed",
                exc,
                context={"stage": "_check_libraries", "library_id": library_id},
            )
            return health_check_item(
                "libraryRootsReadable", "warning", f"书库不可读：{exc}"
            )
    return health_check_item("libraryRootsReadable", "ok", f"{len(paths)} 个书库可读")


def _check_storage_root(path: Path) -> dict[str, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(prefix=".health-", dir=path, delete=True) as probe:
            probe.write(b"ok")
            probe.flush()
        return health_check_item("storageWritable", "ok", "书库文件夹可写")
    except OSError as exc:
        record_exception(
            logging.getLogger(__name__),
            "modules.system.infrastructure.health._check_storage_root.failed",
            exc,
            context={"stage": "_check_storage_root"},
        )
        return health_check_item("storageWritable", "error", f"书库文件夹不可写：{exc}")


def probe_database(db: Session) -> None:
    db.execute(select(1)).scalar_one()


def run_system_health_checks(db: Session, settings: Settings) -> dict[str, object]:
    checks: list[dict[str, Any]] = [
        _env_check("SESSION_SECRET", settings.session_secret, required=False),
    ]

    try:
        probe_database(db)
        checks.append(health_check_item("database", "ok", "数据库可连接"))
    except Exception as exc:  # noqa: BLE001 - health checks report failures.
        record_exception(
            logging.getLogger(__name__),
            "modules.system.infrastructure.health.run_system_health_checks.failed",
            exc,
            context={"stage": "run_system_health_checks"},
        )
        checks.append(health_check_item("database", "error", f"数据库不可用：{exc}"))

    library_root_paths = [
        (str(library_id), Path(path))
        for library_id, path in db.execute(
            select(Library.id, Library.root_path).where(Library.enabled.is_(True))
        ).all()
        if path
    ]
    checks.append(_check_libraries(library_root_paths))
    checks.append(_check_storage_root(settings.resolved_storage_root))
    return {"status": overall_health_status(checks), "checks": checks}
