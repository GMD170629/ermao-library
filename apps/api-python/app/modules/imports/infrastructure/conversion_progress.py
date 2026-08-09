"""Independent short-session adapter for text-conversion checkpoints."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from sqlalchemy.orm import Session

from app.modules.imports.application.conversion_identity import (
    conversion_idempotency_key,
)
from app.modules.imports.application.dto import ConversionProgressTaskDTO
from app.modules.imports.application.errors import ConversionProgressConflict
from app.modules.imports.infrastructure.conversion import (
    ConversionTaskConflict,
    ensure_conversion_task,
    record_conversion_failure,
    resolve_source_volume_id,
    update_conversion_stage,
)


class SqlAlchemyTextConversionProgress:
    """Persist each conversion checkpoint in its own explicit transaction."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def ensure_task(
        self,
        import_task_id: str,
        *,
        task_id: str,
        source_path: Path,
        source_format: str,
        converter: str,
        source_hash: str,
        options_json: str,
        now: int,
    ) -> ConversionProgressTaskDTO:
        try:
            with self._session_factory() as session, session.begin():
                source_volume_id = resolve_source_volume_id(
                    session,
                    import_task_id,
                    str(source_path.resolve()),
                )
                if not source_volume_id:
                    raise ValueError("转换任务缺少源卷册")
                return ensure_conversion_task(
                    session,
                    import_task_id,
                    task_id=task_id,
                    source_volume_id=source_volume_id,
                    source_hash=source_hash,
                    idempotency_key=conversion_idempotency_key(
                        source_volume_id,
                        source_hash,
                    ),
                    source_path=str(source_path),
                    fmt=source_format,
                    target_format="EPUB",
                    converter=converter,
                    options_json=options_json,
                    now=now,
                )
        except ConversionTaskConflict as exc:
            raise ConversionProgressConflict(str(exc)) from exc

    def update_stage(
        self,
        import_task_id: str,
        conversion_task_id: str,
        *,
        status: str,
        progress: int,
        message: str,
        conversion_values: Mapping[str, object] | None,
        now: int,
    ) -> None:
        try:
            with self._session_factory() as session, session.begin():
                update_conversion_stage(
                    session,
                    import_task_id,
                    conversion_task_id,
                    status=status,
                    progress=progress,
                    message=message,
                    conversion_values=(
                        dict(conversion_values)
                        if conversion_values is not None
                        else None
                    ),
                    now=now,
                )
        except ConversionTaskConflict as exc:
            raise ConversionProgressConflict(str(exc)) from exc

    def record_failure(
        self,
        import_task_id: str,
        conversion_task_id: str,
        *,
        retryable: bool,
        error_code: str,
        summary: str,
        now: int,
    ) -> None:
        with self._session_factory() as session, session.begin():
            record_conversion_failure(
                session,
                import_task_id,
                conversion_task_id,
                retryable=retryable,
                error_code=error_code,
                summary=summary,
                now=now,
            )
