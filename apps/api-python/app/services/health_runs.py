from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.services.email_settings import EmailSettingsError, get_email_settings, test_smtp_connection
from app.services.kindle_queue import safe_error_message
from app.services.metadata_provider_registry import enabled_metadata_provider_ids, test_metadata_provider
from app.services.queue_runtime import queue_runtime_view
from app.services.system_events import record_system_event
from app.services.text_conversion import converter_capability


SessionFactory = Callable[[], Session]
TERMINAL_CHECK_STATUSES = {"ok", "warning", "error", "skipped"}
QUEUE_TABLES = {
    "import": ("ImportTask", ("PENDING",), ("PARSING",), ("FAILED",)),
    "download": ("DownloadTask", ("queued",), ("downloading", "downloaded", "importing"), ("failed",)),
    "kindle": ("KindleSendTask", ("queued",), ("sending",), ("failed", "unknown")),
    "metadata": ("MetadataLookupTask", ("PENDING", "RETRY_WAIT"), ("RUNNING",), ("FAILED",)),
}
_threads: dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.get_bind()).get_table_names()
    except Exception:
        return False


def _session(factory: SessionFactory) -> Session:
    return factory()


def _close(db: Session, close_sessions: bool) -> None:
    if close_sessions:
        db.close()


def _run_row(db: Session, run_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "SystemHealthRun"):
        return None
    row = db.execute(
        text("SELECT * FROM `SystemHealthRun` WHERE `id` = :id"),
        {"id": run_id},
    ).mappings().first()
    return dict(row) if row else None


def health_run_snapshot(db: Session, run_id: str) -> dict[str, Any] | None:
    row = _run_row(db, run_id)
    if not row:
        return None
    snapshot = json.loads(str(row["snapshot"]))
    snapshot["version"] = int(row.get("version") or snapshot.get("version") or 1)
    snapshot["status"] = str(row.get("status") or snapshot.get("status") or "running")
    snapshot["finishedAt"] = row.get("finishedAt") or snapshot.get("finishedAt")
    return snapshot


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
        _item("monitor-root", "storage", "health.item.monitorRoot", "directory", options={"path": str(settings.resolved_monitor_root or ""), "writable": False}),
    ]
    if _has_table(db, "MonitorFolder"):
        folders = db.execute(
            text("SELECT `id`, `name`, `rootPath` FROM `MonitorFolder` WHERE `enabled` = 1 ORDER BY `createdAt`, `id`")
        ).mappings()
        for folder in folders:
            items.append(
                _item(
                    f"monitor-folder:{folder['id']}",
                    "storage",
                    "health.item.importFolder",
                    "directory",
                    options={"path": str(folder.get("rootPath") or ""), "writable": False, "name": str(folder.get("name") or "")},
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
            _item("queue:download", "queues", "health.item.downloadQueue", "queue", options={"queue": "download", "enabled": settings.download_queue_enabled}),
            _item("queue:kindle", "queues", "health.item.kindleQueue", "queue", options={"queue": "kindle", "enabled": settings.kindle_send_queue_enabled}),
            _item("queue:metadata", "queues", "health.item.metadataQueue", "queue", options={"queue": "metadata", "enabled": True}),
            _item("config:smtp", "configuration", "health.item.smtp", "smtp"),
            _item("config:conversion", "configuration", "health.item.epubConversion", "conversion"),
            _item("config:providers:ebook", "configuration", "health.item.ebookProviders", "providers", options={"workType": "ebook"}),
            _item("config:providers:comic", "configuration", "health.item.comicProviders", "providers", options={"workType": "comic"}),
            _item("config:providers:audiobook", "configuration", "health.item.audiobookProviders", "providers", options={"workType": "audiobook"}),
        ]
    )
    return items


def create_or_reuse_health_run(db: Session, settings: Settings, actor_user_id: str) -> tuple[dict[str, Any], bool]:
    if not _has_table(db, "SystemHealthRun"):
        raise RuntimeError("health-run-storage-unavailable")
    active = db.execute(
        text(
            "SELECT * FROM `SystemHealthRun` WHERE `status` = 'running' "
            "ORDER BY CAST(`startedAt` AS INTEGER) DESC LIMIT 1"
        )
    ).mappings().first()
    if active:
        return health_run_snapshot(db, str(active["id"])) or {}, False
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
    db.execute(
        text(
            "INSERT INTO `SystemHealthRun` "
            "(`id`, `actorUserId`, `status`, `version`, `snapshot`, `startedAt`, `createdAt`, `updatedAt`) "
            "VALUES (:id, :actor, 'running', 1, :snapshot, :now, :now, :now)"
        ),
        {"id": run_id, "actor": actor_user_id, "snapshot": json.dumps(snapshot, ensure_ascii=False), "now": now},
    )
    db.commit()
    return snapshot, True


def _summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(items), "completed": 0, "ok": 0, "warning": 0, "error": 0, "skipped": 0}
    for item in items:
        status = str(item.get("status"))
        if status in TERMINAL_CHECK_STATUSES:
            summary["completed"] += 1
            summary[status] += 1
    return summary


def _update_snapshot(
    db: Session,
    run_id: str,
    item_id: str | None,
    *,
    item_values: dict[str, Any] | None = None,
    run_status: str | None = None,
) -> dict[str, Any]:
    row = _run_row(db, run_id)
    if not row:
        raise RuntimeError("health-run-not-found")
    snapshot = json.loads(str(row["snapshot"]))
    if item_id is not None:
        target = next(item for item in snapshot["items"] if item["id"] == item_id)
        target.update(item_values or {})
    snapshot["summary"] = _summary(snapshot["items"])
    now = now_timestamp_ms()
    if run_status:
        snapshot["status"] = run_status
        if run_status != "running":
            snapshot["finishedAt"] = now
    version = int(row.get("version") or 1) + 1
    snapshot["version"] = version
    db.execute(
        text(
            "UPDATE `SystemHealthRun` SET `status` = :status, `version` = :version, "
            "`snapshot` = :snapshot, `finishedAt` = :finished, `updatedAt` = :now WHERE `id` = :id"
        ),
        {
            "id": run_id,
            "status": snapshot["status"],
            "version": version,
            "snapshot": json.dumps(snapshot, ensure_ascii=False),
            "finished": snapshot.get("finishedAt"),
            "now": now,
        },
    )
    db.commit()
    return snapshot


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
        db.execute(text("SELECT 1"))
        return "ok", "health.database.ok", {}
    except Exception as exc:
        db.rollback()
        return "error", "health.database.error", {"error": safe_error_message(exc)}


def _status_clause(values: tuple[str, ...], prefix: str) -> tuple[str, dict[str, str]]:
    params = {f"{prefix}_{index}": value for index, value in enumerate(values)}
    return ", ".join(f":{key}" for key in params), params


def _queue_result(db: Session, options: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    queue = str(options["queue"])
    if not bool(options.get("enabled")):
        return "skipped", "health.queue.disabled", {"queue": queue}
    runtime = queue_runtime_view(db, queue)
    details: dict[str, Any] = {"queue": queue, "runtime": runtime}
    table, pending_values, running_values, failed_values = QUEUE_TABLES[queue]
    if _has_table(db, table):
        for key, statuses in (("pending", pending_values), ("running", running_values), ("failed", failed_values)):
            placeholders, params = _status_clause(statuses, key)
            details[key] = int(
                db.execute(text(f"SELECT COUNT(*) FROM `{table}` WHERE `status` IN ({placeholders})"), params).scalar() or 0
            )
        pending_placeholders, pending_params = _status_clause(pending_values, "oldest")
        details["oldestPendingAt"] = db.execute(
            text(f"SELECT MIN(`createdAt`) FROM `{table}` WHERE `status` IN ({pending_placeholders})"),
            pending_params,
        ).scalar()
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
    recipient_count = 0
    if _has_table(db, "UserPreference"):
        recipient_count = int(
            db.execute(
                text("SELECT COUNT(*) FROM `UserPreference` WHERE `key` = 'kindle.email' AND LENGTH(TRIM(`value`)) > 2")
            ).scalar()
            or 0
        )
    details = {"recipientCount": recipient_count, "configured": bool(values.get("host") and values.get("fromEmail"))}
    if not values.get("host"):
        return "warning", "health.smtp.notConfigured", details
    try:
        test_smtp_connection(values, timeout=10)
    except Exception as exc:
        return "error", "health.smtp.connectionFailed", {**details, "error": safe_error_message(exc, [str(values.get("password") or "")])}
    return ("ok", "health.smtp.ok", details) if recipient_count else ("warning", "health.smtp.noRecipients", details)


def _conversion_result(settings: Settings) -> tuple[str, str, dict[str, Any]]:
    capability = converter_capability(settings)
    if not settings.ebook_conversion_enabled:
        return "skipped", "health.conversion.disabled", capability
    if capability.get("available"):
        return "ok", "health.conversion.ok", capability
    return "error", "health.conversion.unavailable", capability


def _providers_result(db: Session, options: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
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
            details["providers"].append({"id": provider_id, "ok": ok, "message": safe_error_message(str(result.get("message") or ""))[:300]})
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
            actor_user_id = str(row.get("actorUserId") or "")
            snapshot = json.loads(str(row["snapshot"]))
        finally:
            _close(db, close_sessions)

        for item in snapshot["items"]:
            started = now_timestamp_ms()
            db = _session(factory)
            try:
                _update_snapshot(
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
                current = next(candidate for candidate in health_run_snapshot(db, run_id)["items"] if candidate["id"] == item["id"])
                status, message_code, details = _execute_item(db, current, settings)
                finished = now_timestamp_ms()
                _update_snapshot(
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
                db.rollback()
                finished = now_timestamp_ms()
                _update_snapshot(
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
                    _update_snapshot(
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
            final_status = "error" if snapshot.get("summary", {}).get("error") else "warning" if snapshot.get("summary", {}).get("warning") else "completed"
            final = _update_snapshot(db, run_id, None, run_status=final_status)
            record_system_event(
                db,
                source="system",
                action="health.completed",
                message="系统健康检查已完成",
                level="warning" if final_status in {"warning", "error"} else "info",
                actor_type="admin",
                actor_id=actor_user_id,
                target_type="healthRun",
                target_id=run_id,
                metadata={"durationMs": max(0, int(final.get("finishedAt") or 0) - int(final.get("startedAt") or 0)), "summary": final.get("summary")},
                commit=True,
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
                        _update_snapshot(
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
                _update_snapshot(db, run_id, None, run_status="failed")
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
    if not _has_table(db, "SystemHealthRun"):
        return 0
    rows = db.execute(text("SELECT `id`, `snapshot` FROM `SystemHealthRun` WHERE `status` = 'running'")).mappings().all()
    changed = 0
    for row in rows:
        snapshot = json.loads(str(row["snapshot"]))
        now = now_timestamp_ms()
        for item in snapshot.get("items", []):
            if item.get("status") in {"pending", "running"}:
                item.update({"status": "error", "messageCode": "health.run.interrupted", "finishedAt": now})
        snapshot["status"] = "failed"
        snapshot["finishedAt"] = now
        snapshot["summary"] = _summary(snapshot.get("items", []))
        snapshot["version"] = int(snapshot.get("version") or 1) + 1
        db.execute(
            text(
                "UPDATE `SystemHealthRun` SET `status` = 'failed', `version` = :version, "
                "`snapshot` = :snapshot, `finishedAt` = :now, `updatedAt` = :now WHERE `id` = :id"
            ),
            {"id": row["id"], "version": snapshot["version"], "snapshot": json.dumps(snapshot, ensure_ascii=False), "now": now},
        )
        changed += 1
    if changed:
        db.commit()
    return changed


def prune_old_health_runs(db: Session, max_age_hours: int = 24) -> int:
    if not _has_table(db, "SystemHealthRun"):
        return 0
    cutoff = now_timestamp_ms() - max(1, max_age_hours) * 60 * 60 * 1000
    result = db.execute(
        text(
            "DELETE FROM `SystemHealthRun` WHERE `status` != 'running' "
            "AND CAST(`finishedAt` AS INTEGER) < :cutoff"
        ),
        {"cutoff": cutoff},
    )
    if result.rowcount:
        db.commit()
    return int(result.rowcount or 0)
