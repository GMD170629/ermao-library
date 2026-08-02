"""Manual system health run orchestration with ORM persistence."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import now_timestamp_ms, timestamp_ms_to_iso
from app.models.auth import UserPreference
from app.models.import_pipeline import DownloadTask, ImportTask, KindleSendTask
from app.models.organize import MetadataLookupTask
from app.models.settings import MonitorFolder, SystemHealthRun
from app.modules.system.domain.health import (
    HealthRunSnapshot,
    TERMINAL_CHECK_STATUSES,
    normalize_health_run_snapshot,
    summarize_health_items,
)
from app.modules.system.application.commands import (
    execute_system_transaction,
    reset_failed_system_transaction,
)
from app.modules.system.infrastructure.events import record_system_event
from app.modules.system.infrastructure.health import probe_database
from app.modules.system.infrastructure.queue_runtime import queue_runtime_view
from app.services.email_settings import EmailSettingsError, get_email_settings, test_smtp_connection
from app.core.safe_errors import safe_error_message
from app.services.text_conversion import converter_capability

SessionFactory = Callable[[], Session]
QUEUE_MODELS = {
    "import": (ImportTask, ("PENDING",), ("PARSING",), ("FAILED",)),
    "download": (DownloadTask, ("queued",), ("downloading", "downloaded", "importing"), ("failed",)),
    "kindle": (KindleSendTask, ("queued",), ("sending",), ("failed", "unknown")),
    "metadata": (MetadataLookupTask, ("PENDING", "RETRY_WAIT"), ("RUNNING",), ("FAILED",)),
}
_threads: dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()


def _session(factory: SessionFactory) -> Session:
    return factory()


def _close(db: Session, close_sessions: bool) -> None:
    if close_sessions:
        db.close()


def _run_row(db: Session, run_id: str) -> SystemHealthRun | None:
    return db.get(SystemHealthRun, run_id)


def _snapshot_from_row(row: SystemHealthRun) -> HealthRunSnapshot:
    snapshot = json.loads(str(row.snapshot))
    snapshot["version"] = int(row.version or snapshot.get("version") or 1)
    snapshot["status"] = str(row.status or snapshot.get("status") or "running")
    snapshot["finishedAt"] = row.finished_at or snapshot.get("finishedAt")
    return normalize_health_run_snapshot(snapshot)


def health_run_snapshot(db: Session, run_id: str) -> HealthRunSnapshot | None:
    row = _run_row(db, run_id)
    if not row:
        return None
    return _snapshot_from_row(row)


def _item(
    item_id: str,
    group: str,
    label_code: str,
    kind: str,
    *,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "group": group,
        "labelCode": label_code,
        "kind": kind,
        "options": options or {},
        "status": "pending",
        "messageCode": "health.pending",
        "messageParams": {},
        "details": {},
        "startedAt": None,
        "finishedAt": None,
        "durationMs": None,
    }


def _initial_items(db: Session, settings: Settings) -> list[dict[str, Any]]:
    items = [
        _item("database", "storage", "health.item.database", "database"),
    ]
    folders = db.scalars(
        select(MonitorFolder)
        .where(MonitorFolder.enabled.is_(True))
        .order_by(MonitorFolder.created_at, MonitorFolder.id)
    ).all()
    for folder in folders:
        items.append(
            _item(
                f"monitor-folder:{folder.id}",
                "storage",
                "health.item.importFolder",
                "directory",
                options={
                    "path": str(folder.root_path or ""),
                    "writable": False,
                    "name": str(folder.name or ""),
                },
            )
        )
    directories = [
        ("storage-root", "health.item.storageRoot", settings.resolved_storage_root),
        ("database-directory", "health.item.databaseDirectory", settings.database_path.parent),
        ("library-directory", "health.item.libraryDirectory", settings.resolved_storage_root / "library"),
        ("covers-directory", "health.item.coversDirectory", settings.resolved_storage_root / "covers"),
        ("indexes-directory", "health.item.indexesDirectory", settings.resolved_storage_root / "indexes"),
        ("backups-directory", "health.item.backupsDirectory", settings.resolved_storage_root / "backups"),
        ("conversion-directory", "health.item.conversionDirectory", settings.conversion_root),
        ("conversion-temp-directory", "health.item.conversionTempDirectory", settings.conversion_temp_root),
        ("logs-directory", "health.item.logsDirectory", settings.resolved_storage_root / "logs"),
        ("secrets-directory", "health.item.secretsDirectory", settings.resolved_storage_root / "secrets"),
    ]
    items.extend(
        _item(item_id, "storage", label, "directory", options={"path": str(path), "writable": True})
        for item_id, label, path in directories
    )
    items.extend(
        [
            _item("queue:import", "queues", "health.item.importQueue", "queue", options={"queue": "import", "enabled": True}),
            _item(
                "queue:download",
                "queues",
                "health.item.downloadQueue",
                "queue",
                options={"queue": "download", "enabled": settings.download_queue_enabled},
            ),
            _item(
                "queue:kindle",
                "queues",
                "health.item.kindleQueue",
                "queue",
                options={"queue": "kindle", "enabled": settings.kindle_send_queue_enabled},
            ),
            _item(
                "queue:metadata",
                "queues",
                "health.item.metadataQueue",
                "queue",
                options={"queue": "metadata", "enabled": True},
            ),
            _item("config:smtp", "configuration", "health.item.smtp", "smtp"),
            _item("config:conversion", "configuration", "health.item.epubConversion", "conversion"),
            _item(
                "config:providers:ebook",
                "configuration",
                "health.item.ebookProviders",
                "providers",
                options={"workType": "ebook"},
            ),
            _item(
                "config:providers:comic",
                "configuration",
                "health.item.comicProviders",
                "providers",
                options={"workType": "comic"},
            ),
            _item(
                "config:providers:audiobook",
                "configuration",
                "health.item.audiobookProviders",
                "providers",
                options={"workType": "audiobook"},
            ),
        ]
    )
    return items


def create_or_reuse_health_run(
    db: Session,
    settings: Settings,
    actor_user_id: str,
) -> tuple[HealthRunSnapshot, bool]:
    active = db.scalars(
        select(SystemHealthRun)
        .where(SystemHealthRun.status == "running")
        .order_by(SystemHealthRun.started_at.desc())
        .limit(1)
    ).first()
    if active:
        return health_run_snapshot(db, str(active.id)) or {}, False
    now = now_timestamp_ms()
    run_id = f"health_{uuid4().hex}"
    snapshot = {
        "runId": run_id,
        "status": "running",
        "version": 1,
        "startedAt": now,
        "finishedAt": None,
        "groups": [
            {"id": "storage", "labelCode": "health.group.storage"},
            {"id": "queues", "labelCode": "health.group.queues"},
            {"id": "configuration", "labelCode": "health.group.configuration"},
        ],
        "items": _initial_items(db, settings),
        "summary": {"total": 0, "completed": 0, "ok": 0, "warning": 0, "error": 0, "skipped": 0},
    }
    snapshot["summary"]["total"] = len(snapshot["items"])
    db.add(
        SystemHealthRun(
            id=run_id,
            actor_user_id=actor_user_id,
            status="running",
            version=1,
            snapshot=json.dumps(snapshot, ensure_ascii=False),
            started_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    return normalize_health_run_snapshot(snapshot), True


def _update_snapshot(
    db: Session,
    run_id: str,
    item_id: str | None,
    *,
    item_values: dict[str, Any] | None = None,
    run_status: str | None = None,
) -> HealthRunSnapshot:
    row = _run_row(db, run_id)
    if not row:
        raise RuntimeError("health-run-not-found")
    snapshot = json.loads(str(row.snapshot))
    if item_id is not None:
        target = next(item for item in snapshot["items"] if item["id"] == item_id)
        target.update(item_values or {})
    snapshot["summary"] = summarize_health_items(snapshot["items"])
    now = now_timestamp_ms()
    if run_status:
        snapshot["status"] = run_status
        if run_status != "running":
            snapshot["finishedAt"] = now
    version = int(row.version or 1) + 1
    snapshot["version"] = version
    db.execute(
        update(SystemHealthRun)
        .where(SystemHealthRun.id == run_id)
        .values(
            status=snapshot["status"],
            version=version,
            snapshot=json.dumps(snapshot, ensure_ascii=False),
            finished_at=snapshot.get("finishedAt"),
            updated_at=now,
        )
    )
    db.flush()
    return normalize_health_run_snapshot(snapshot)


def _commit_snapshot_update(
    db: Session,
    run_id: str,
    item_id: str | None,
    *,
    item_values: dict[str, Any] | None = None,
    run_status: str | None = None,
) -> HealthRunSnapshot:
    return execute_system_transaction(
        db,
        lambda: _update_snapshot(
            db,
            run_id,
            item_id,
            item_values=item_values,
            run_status=run_status,
        ),
    )


def _directory_result(options: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    raw_path = str(options.get("path") or "")
    if not raw_path:
        return "error", "health.directory.notConfigured", {}
    path = Path(raw_path).expanduser()
    details = {"path": str(path), "writableRequired": bool(options.get("writable")), "name": options.get("name")}
    if not path.exists():
        return "error", "health.directory.missing", details
    if not path.is_dir():
        return "error", "health.directory.notDirectory", details
    try:
        next(path.iterdir(), None)
    except OSError as exc:
        details["error"] = safe_error_message(exc)
        return "error", "health.directory.notReadable", details
    if not os.access(path, os.R_OK | os.X_OK):
        return "error", "health.directory.notReadable", details
    if options.get("writable"):
        try:
            with NamedTemporaryFile(prefix=".health-", dir=path, delete=True) as probe:
                probe.write(b"ok")
                probe.flush()
        except OSError as exc:
            details["error"] = safe_error_message(exc)
            return "error", "health.directory.notWritable", details
    return "ok", "health.directory.ok", details


def _database_result(db: Session) -> tuple[str, str, dict[str, Any]]:
    try:
        probe_database(db)
        return "ok", "health.database.ok", {}
    except Exception as exc:
        reset_failed_system_transaction(db)
        return "error", "health.database.error", {"error": safe_error_message(exc)}


def _queue_result(db: Session, options: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    queue = str(options["queue"])
    if not bool(options.get("enabled")):
        return "skipped", "health.queue.disabled", {"queue": queue}
    runtime = queue_runtime_view(db, queue)
    details: dict[str, Any] = {"queue": queue, "runtime": runtime}
    model, pending_values, running_values, failed_values = QUEUE_MODELS[queue]
    for key, statuses in (("pending", pending_values), ("running", running_values), ("failed", failed_values)):
        details[key] = int(
            db.scalar(select(func.count()).select_from(model).where(model.status.in_(statuses))) or 0
        )
    details["oldestPendingAt"] = timestamp_ms_to_iso(
        db.scalar(
            select(func.min(model.created_at)).where(model.status.in_(pending_values))
        )
    )
    if runtime is None:
        return "error", "health.queue.noHeartbeat", details
    if runtime.get("status") != "running" or runtime.get("stale"):
        return "error", "health.queue.stale", details
    if runtime.get("lastError"):
        return "warning", "health.queue.recentError", details
    return "ok", "health.queue.ok", details


def _smtp_result(db: Session) -> tuple[str, str, dict[str, Any]]:
    try:
        values = get_email_settings(db, include_password=True)
    except EmailSettingsError as exc:
        return "error", "health.smtp.invalid", {"error": safe_error_message(exc)}
    recipient_count = int(
        db.scalar(
            select(func.count())
            .select_from(UserPreference)
            .where(
                UserPreference.key == "kindle.email",
                func.length(func.trim(UserPreference.value)) > 2,
            )
        )
        or 0
    )
    details = {"recipientCount": recipient_count, "configured": bool(values.get("host") and values.get("fromEmail"))}
    if not values.get("host"):
        return "warning", "health.smtp.notConfigured", details
    try:
        test_smtp_connection(values, timeout=10)
    except Exception as exc:
        return "error", "health.smtp.connectionFailed", {
            **details,
            "error": safe_error_message(exc, [str(values.get("password") or "")]),
        }
    return ("ok", "health.smtp.ok", details) if recipient_count else ("warning", "health.smtp.noRecipients", details)


def _conversion_result(settings: Settings) -> tuple[str, str, dict[str, Any]]:
    capability = converter_capability(settings)
    if not settings.ebook_conversion_enabled:
        return "skipped", "health.conversion.disabled", capability
    if capability.get("available"):
        return "ok", "health.conversion.ok", capability
    return "error", "health.conversion.unavailable", capability


def _providers_result(db: Session, options: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    from app.services.metadata_provider_registry import (
        enabled_metadata_provider_ids,
        test_metadata_provider,
    )

    work_type = str(options["workType"])
    provider_ids = enabled_metadata_provider_ids(db, work_type)
    details: dict[str, Any] = {"workType": work_type, "providers": []}
    if not provider_ids:
        return "warning", "health.providers.noneEnabled", details
    failed = 0
    for provider_id in provider_ids:
        try:
            result, _provider = test_metadata_provider(db, provider_id)
            ok = bool(result.get("ok"))
            details["providers"].append(
                {
                    "id": provider_id,
                    "ok": ok,
                    "message": safe_error_message(str(result.get("message") or ""))[:300],
                }
            )
            failed += 0 if ok else 1
        except Exception as exc:
            failed += 1
            details["providers"].append({"id": provider_id, "ok": False, "message": safe_error_message(exc)})
    if failed:
        return "error", "health.providers.failed", details
    return "ok", "health.providers.ok", details


def _execute_item(db: Session, item: dict[str, Any], settings: Settings) -> tuple[str, str, dict[str, Any]]:
    kind = str(item["kind"])
    options = dict(item.get("options") or {})
    if kind == "directory":
        return _directory_result(options)
    if kind == "database":
        return _database_result(db)
    if kind == "queue":
        return _queue_result(db, options)
    if kind == "smtp":
        return _smtp_result(db)
    if kind == "conversion":
        return _conversion_result(settings)
    if kind == "providers":
        return _providers_result(db, options)
    return "error", "health.unknownCheck", {}


def run_health_checks(factory: SessionFactory, close_sessions: bool, settings: Settings, run_id: str) -> None:
    actor_user_id = ""
    try:
        db = _session(factory)
        try:
            row = _run_row(db, run_id)
            if not row:
                return
            actor_user_id = str(row.actor_user_id or "")
            snapshot = json.loads(str(row.snapshot))
        finally:
            _close(db, close_sessions)

        for item in snapshot["items"]:
            started = now_timestamp_ms()
            db = _session(factory)
            try:
                _commit_snapshot_update(
                    db,
                    run_id,
                    str(item["id"]),
                    item_values={
                        "status": "running",
                        "messageCode": "health.running",
                        "startedAt": started,
                        "finishedAt": None,
                        "durationMs": None,
                    },
                )
                current = next(
                    candidate for candidate in health_run_snapshot(db, run_id)["items"] if candidate["id"] == item["id"]
                )
                status, message_code, details = _execute_item(db, current, settings)
                finished = now_timestamp_ms()
                _commit_snapshot_update(
                    db,
                    run_id,
                    str(item["id"]),
                    item_values={
                        "status": status,
                        "messageCode": message_code,
                        "details": details,
                        "finishedAt": finished,
                        "durationMs": max(0, finished - started),
                    },
                )
            except Exception as exc:
                reset_failed_system_transaction(db)
                finished = now_timestamp_ms()
                _commit_snapshot_update(
                    db,
                    run_id,
                    str(item["id"]),
                    item_values={
                        "status": "error",
                        "messageCode": "health.check.failed",
                        "details": {"error": safe_error_message(exc)},
                        "finishedAt": finished,
                        "durationMs": max(0, finished - started),
                    },
                )
            finally:
                _close(db, close_sessions)

        db = _session(factory)
        try:
            snapshot = health_run_snapshot(db, run_id) or {}
            for item in snapshot.get("items", []):
                if item.get("status") in {"pending", "running"}:
                    _commit_snapshot_update(
                        db,
                        run_id,
                        str(item["id"]),
                        item_values={
                            "status": "error",
                            "messageCode": "health.check.failed",
                            "details": {"error": "health-check-did-not-reach-terminal-state"},
                            "finishedAt": now_timestamp_ms(),
                        },
                    )
            snapshot = health_run_snapshot(db, run_id) or {}
            final_status = (
                "error"
                if snapshot.get("summary", {}).get("error")
                else "warning"
                if snapshot.get("summary", {}).get("warning")
                else "completed"
            )
            final = _commit_snapshot_update(db, run_id, None, run_status=final_status)
            execute_system_transaction(
                db,
                lambda: record_system_event(
                    db,
                    source="system",
                    action="health.completed",
                    message="系统健康检查已完成",
                    level=(
                        "warning"
                        if final_status in {"warning", "error"}
                        else "info"
                    ),
                    actor_type="admin",
                    actor_id=actor_user_id,
                    target_type="healthRun",
                    target_id=run_id,
                    metadata={
                        "durationMs": max(
                            0,
                            int(final.get("finishedAt") or 0)
                            - int(final.get("startedAt") or 0),
                        ),
                        "summary": final.get("summary"),
                    },
                ),
            )
        finally:
            _close(db, close_sessions)
    except Exception as exc:
        db = _session(factory)
        try:
            snapshot = health_run_snapshot(db, run_id)
            if snapshot:
                for item in snapshot["items"]:
                    if item["status"] in {"pending", "running"}:
                        _commit_snapshot_update(
                            db,
                            run_id,
                            item["id"],
                            item_values={
                                "status": "error",
                                "messageCode": "health.run.interrupted",
                                "details": {"error": safe_error_message(exc)},
                                "finishedAt": now_timestamp_ms(),
                            },
                        )
                _commit_snapshot_update(db, run_id, None, run_status="failed")
        finally:
            _close(db, close_sessions)
    finally:
        with _threads_lock:
            _threads.pop(run_id, None)


def start_health_run(factory: SessionFactory, close_sessions: bool, settings: Settings, run_id: str) -> None:
    with _threads_lock:
        existing = _threads.get(run_id)
        if existing and existing.is_alive():
            return
        thread = threading.Thread(
            target=run_health_checks,
            args=(factory, close_sessions, settings, run_id),
            name=f"health-run-{run_id[-8:]}",
            daemon=True,
        )
        _threads[run_id] = thread
        thread.start()


def fail_abandoned_health_runs(db: Session) -> int:
    rows = db.scalars(select(SystemHealthRun).where(SystemHealthRun.status == "running")).all()
    changed = 0
    for row in rows:
        snapshot = json.loads(str(row.snapshot))
        now = now_timestamp_ms()
        for item in snapshot.get("items", []):
            if item.get("status") in {"pending", "running"}:
                item.update({"status": "error", "messageCode": "health.run.interrupted", "finishedAt": now})
        snapshot["status"] = "failed"
        snapshot["finishedAt"] = now
        snapshot["summary"] = summarize_health_items(snapshot.get("items", []))
        snapshot["version"] = int(snapshot.get("version") or 1) + 1
        db.execute(
            update(SystemHealthRun)
            .where(SystemHealthRun.id == row.id)
            .values(
                status="failed",
                version=snapshot["version"],
                snapshot=json.dumps(snapshot, ensure_ascii=False),
                finished_at=now,
                updated_at=now,
            )
        )
        changed += 1
    if changed:
        db.flush()
    return changed


def prune_old_health_runs(db: Session, max_age_hours: int = 24) -> int:
    from app.core.time import timestamp_ms_to_datetime

    cutoff = timestamp_ms_to_datetime(now_timestamp_ms() - max(1, max_age_hours) * 60 * 60 * 1000)
    result = db.execute(
        delete(SystemHealthRun).where(
            SystemHealthRun.status != "running",
            SystemHealthRun.finished_at.is_not(None),
            SystemHealthRun.finished_at < cutoff,
        )
    )
    if result.rowcount:
        db.flush()
    return int(result.rowcount or 0)


def active_health_run_id(db: Session) -> str | None:
    return db.scalar(select(SystemHealthRun.id).where(SystemHealthRun.status == "running").limit(1))
