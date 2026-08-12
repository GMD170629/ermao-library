"""Lightweight system health probe checks."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.settings import MonitorFolder
from app.modules.system.domain.health import health_check_item, overall_health_status


def _env_check(name: str, value: str | None, required: bool = True) -> dict[str, str]:
    if required and not value:
        return health_check_item(name, "error", f"{name} 未配置")
    return health_check_item(
        name, "ok" if value else "unknown", "已配置" if value else "未配置"
    )


def _check_monitor_folders(paths: list[Path]) -> dict[str, str]:
    if not paths:
        return health_check_item("monitorRootReadable", "unknown", "未启用监控文件夹")
    for path in paths:
        if not path.exists() or not path.is_dir():
            return health_check_item(
                "monitorRootReadable", "warning", f"监控文件夹不存在：{path}"
            )
        try:
            next(path.iterdir(), None)
        except OSError as exc:
            return health_check_item(
                "monitorRootReadable", "warning", f"监控文件夹不可读：{exc}"
            )
    return health_check_item(
        "monitorRootReadable", "ok", f"{len(paths)} 个监控文件夹可读"
    )


def _check_storage_root(path: Path) -> dict[str, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(prefix=".health-", dir=path, delete=True) as probe:
            probe.write(b"ok")
            probe.flush()
        return health_check_item("storageWritable", "ok", "书库文件夹可写")
    except OSError as exc:
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
        checks.append(health_check_item("database", "error", f"数据库不可用：{exc}"))

    monitor_paths = [
        Path(path)
        for path in db.scalars(
            select(MonitorFolder.root_path).where(MonitorFolder.enabled.is_(True))
        ).all()
        if path
    ]
    checks.append(_check_monitor_folders(monitor_paths))
    checks.append(_check_storage_root(settings.resolved_storage_root))
    return {"status": overall_health_status(checks), "checks": checks}
