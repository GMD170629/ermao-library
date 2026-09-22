"""Bounded, redacted system projections for the automation application port."""

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exception_diagnostics import sanitize_diagnostic_text
from app.core.time import to_timestamp_ms
from app.models import LibraryImportTask, QueueRuntimeState
from app.models.settings import SystemEvent
from app.modules.automation.public import AutomationAccessError, ConfigurationGroup
from app.modules.opds.public import (
    normalize_opds_public_base_url,
    validate_opds_activation,
)
from app.modules.system.application.commands import SystemWriteTransaction
from app.modules.system.infrastructure.events import (
    normalize_stored_event_metadata,
    prepare_system_event,
    system_event_search_filter,
    write_prepared_system_events,
)
from app.modules.system.infrastructure.settings import (
    get_setting,
    prepare_settings_write,
    write_prepared_settings,
)
from app.services.email_settings import (
    prepare_email_settings_update,
    public_email_settings,
    write_prepared_email_settings,
)

_CORRELATION_KEYS = (
    "requestId",
    "taskId",
    "operationId",
    "planId",
    "uploadId",
    "nodeId",
    "parentDiagnosticId",
    "targetIndex",
    "targetOrdinal",
    "libraryId",
    "resourceId",
    "sourceNodeId",
    "taskKind",
    "stage",
    "step",
    "attempt",
)
_CAUSE_KEYS = (
    "type",
    "message",
    "errno",
    "errorName",
    "databaseCode",
    "databaseErrorName",
    "protocolStatus",
    "exitCode",
    "relationship",
    "chainIndex",
    "parentIndex",
)


def _diagnostic_summary(metadata: object) -> dict[str, object]:
    """Only current diagnostics can expose an explicitly allowlisted summary."""
    if not isinstance(metadata, dict) or not isinstance(
        metadata.get("diagnostics"), dict
    ):
        return {"diagnostic_status": "HISTORICAL_INFORMATION_UNAVAILABLE"}
    diagnostics = metadata["diagnostics"]

    def safe(value: object) -> str | int | bool | None:
        if isinstance(value, str):
            return sanitize_diagnostic_text(value)[:1000]
        return value if isinstance(value, (int, bool)) or value is None else None

    summary: dict[str, object] = {
        key: safe(diagnostics[key])
        for key in (
            "id", "exceptionType", "message", "causeStatus", "causeProvided",
            "chainTruncated", "contextProvided", "contextsTruncated",
        )
        if key in diagnostics
    }
    for name in ("directException", "directCause", "rootCause"):
        cause = diagnostics.get(name)
        if isinstance(cause, dict):
            summary[name] = {
                key: safe(cause[key]) for key in _CAUSE_KEYS if key in cause
            }
    contexts = diagnostics.get("contexts")
    if isinstance(contexts, list):
        summary["contexts"] = [
            {key: safe(context[key]) for key in _CAUSE_KEYS if key in context}
            for context in contexts[:8]
            if isinstance(context, dict)
        ]
        summary["contextsTruncated"] = (
            diagnostics.get("contextsTruncated") is True or len(contexts) > 8
        )
    return {
        "diagnostic_status": "RECORDED"
        if "rootCause" in diagnostics
        else "HISTORICAL_INFORMATION_UNAVAILABLE",
        "diagnostics": summary,
        "correlation": {
            key: safe(metadata[key]) for key in _CORRELATION_KEYS if key in metadata
        },
    }


class SqlAlchemyAutomationSystem:
    def __init__(
        self,
        db: Session,
        read_library: Callable[[str], dict[str, object]],
        write_library: Callable[[str, dict[str, object], str], dict[str, object]],
        read_organize: Callable[[], dict[str, object]],
        write_organize: Callable[[dict[str, object]], dict[str, object]],
    ) -> None:
        self.db = db
        self._read_library = read_library
        self._write_library = write_library
        self._read_organize = read_organize
        self._write_organize = write_organize

    def import_queue(
        self, library_ids: frozenset[str], page: int, limit: int
    ) -> dict[str, object]:
        query = select(LibraryImportTask).where(
            LibraryImportTask.library_id.in_(library_ids)
        )
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(
            query.order_by(LibraryImportTask.created_at.desc(), LibraryImportTask.id)
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return {
            "tasks": [
                {
                    "id": r.id,
                    "library_id": r.library_id,
                    "kind": r.kind,
                    "state": r.state,
                    "created_at_ms": to_timestamp_ms(r.created_at),
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": limit,
        }

    def queue_status(self) -> dict[str, object]:
        rows = self.db.scalars(
            select(QueueRuntimeState).order_by(QueueRuntimeState.queue_name).limit(50)
        )
        return {
            "queues": [
                {
                    "name": r.queue_name,
                    "status": r.status,
                    "heartbeat_at_ms": to_timestamp_ms(r.heartbeat_at),
                }
                for r in rows
            ]
        }

    def logs(
        self, page: int, limit: int, search: str | None = None
    ) -> dict[str, object]:
        statement = select(SystemEvent)
        if search:
            statement = statement.where(system_event_search_filter(search))
        rows = self.db.scalars(
            statement.order_by(SystemEvent.created_at.desc(), SystemEvent.id)
            .offset((page - 1) * limit)
            .limit(limit)
        )
        # Free-form messages and diagnostic metadata can contain legacy paths or secrets.
        return {
            "events": [
                {
                    "id": r.id,
                    "level": r.level,
                    "source": r.source,
                    "action": r.action,
                    "target_type": r.target_type,
                    "created_at_ms": to_timestamp_ms(r.created_at),
                    **_diagnostic_summary(
                        normalize_stored_event_metadata(r.metadata_json, event_id=r.id)
                    ),
                }
                for r in rows
            ],
            "page": page,
            "page_size": limit,
        }

    def configuration(
        self, group: ConfigurationGroup, library_id: str | None
    ) -> dict[str, object]:
        if group == "email":
            return public_email_settings(self.db)
        if group == "site":
            return {"language": get_setting(self.db, "language", "zh-CN")}
        if group == "opds":
            return {
                "enabled": get_setting(self.db, "opds.enabled", False),
                "publicBaseUrl": get_setting(self.db, "opds.publicBaseUrl", ""),
            }
        return (
            self._read_library(library_id or "")
            if group == "library"
            else self._read_organize()
        )

    def configure(
        self,
        group: ConfigurationGroup,
        library_id: str | None,
        values: dict[str, object],
        user_id: str,
    ) -> dict[str, object]:
        if group not in {"site", "email", "opds"}:
            return (
                self._write_library(library_id or "", values, user_id)
                if group == "library"
                else self._write_organize(values)
            )
        event = prepare_system_event(
            source="automation",
            action="automation.system.updated",
            actor_type="user",
            actor_id=user_id,
            target_type="settings",
            target_id=group,
            message="系统配置已更新 / System configuration updated",
        )
        if group == "email":
            prepared_email = prepare_email_settings_update(self.db, values)
            with SystemWriteTransaction(self.db):
                write_prepared_email_settings(self.db, prepared_email)
                write_prepared_system_events(self.db, (event,))
        else:
            allowed = {"language"} if group == "site" else {"enabled", "publicBaseUrl"}
            if not values.keys() <= allowed:
                raise AutomationAccessError("INVALID_CONFIGURATION_FIELD")
            if group == "opds":
                normalized_url = normalize_opds_public_base_url(
                    str(values.get("publicBaseUrl") or "")
                )
                validate_opds_activation(values.get("enabled") is True, normalized_url)
                values = {**values, "publicBaseUrl": normalized_url}
            normalized = (
                values
                if group == "site"
                else {f"opds.{key}": value for key, value in values.items()}
            )
            prepared = prepare_settings_write(normalized)
            with SystemWriteTransaction(self.db):
                write_prepared_settings(self.db, prepared)
                write_prepared_system_events(self.db, (event,))
        return self.configuration(group, library_id)
