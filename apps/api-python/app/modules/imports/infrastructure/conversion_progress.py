"""Independent short-session adapter for text-conversion checkpoints."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from sqlalchemy.orm import Session

from app.modules.imports.application.commands import ImportWriteTransaction
from app.modules.imports.application.conversion_identity import (
    conversion_idempotency_key,
)
from app.modules.imports.application.dto import ConversionProgressTaskDTO
from app.modules.imports.application.errors import ConversionProgressConflict
from app.modules.imports.infrastructure.conversion import (
    ConversionTaskConflict,
    load_conversion_task_projection,
    load_source_volume_id,
    prepare_conversion_failure_write,
    prepare_conversion_stage_write,
    prepare_conversion_task_write,
    write_conversion_failure,
    write_conversion_stage,
    write_inserted_conversion_task,
    write_reused_conversion_task,
    write_updated_conversion_task,
)
from app.modules.imports.infrastructure.uow import SqlAlchemyImportUnitOfWork


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
        source_path_value = str(source_path)
        resolved_source_path = str(source_path.resolve())
        with self._session_factory() as session:
            source_volume_id = load_source_volume_id(
                session,
                import_task_id,
                resolved_source_path,
            )
        if not source_volume_id:
            raise ValueError("遗留文件处理记录缺少源卷册")
        idempotency_key = conversion_idempotency_key(
            source_volume_id,
            source_hash,
        )
        for attempt in range(2):
            with self._session_factory() as session:
                projection = load_conversion_task_projection(
                    session,
                    import_task_id=import_task_id,
                    idempotency_key=idempotency_key,
                )
            prepared = prepare_conversion_task_write(
                projection,
                import_task_id=import_task_id,
                task_id=task_id,
                source_volume_id=source_volume_id,
                source_hash=source_hash,
                idempotency_key=idempotency_key,
                source_path=source_path_value,
                source_format=source_format,
                converter=converter,
                options_json=options_json,
                now=now,
            )
            try:
                if prepared.mode == "reuse":
                    with self._session_factory() as session:
                        with ImportWriteTransaction(
                            SqlAlchemyImportUnitOfWork(session)
                        ):
                            write_reused_conversion_task(session, prepared)
                elif prepared.mode == "update":
                    with self._session_factory() as session:
                        with ImportWriteTransaction(
                            SqlAlchemyImportUnitOfWork(session)
                        ):
                            write_updated_conversion_task(session, prepared)
                else:
                    with self._session_factory() as session:
                        with ImportWriteTransaction(
                            SqlAlchemyImportUnitOfWork(session)
                        ):
                            write_inserted_conversion_task(session, prepared)
                return prepared.result
            except ConversionTaskConflict as exc:
                if attempt == 1:
                    raise ConversionProgressConflict(str(exc)) from exc
        raise AssertionError("unreachable conversion checkpoint retry")

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
        prepared_conversion_values = (
            dict(conversion_values) if conversion_values is not None else None
        )
        prepared = prepare_conversion_stage_write(
            import_task_id,
            conversion_task_id,
            status=status,
            progress=progress,
            message=message,
            conversion_values=prepared_conversion_values,
            now=now,
        )
        try:
            with self._session_factory() as session:
                with ImportWriteTransaction(SqlAlchemyImportUnitOfWork(session)):
                    write_conversion_stage(session, prepared)
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
        prepared = prepare_conversion_failure_write(
            import_task_id,
            conversion_task_id,
            retryable=retryable,
            error_code=error_code,
            summary=summary,
            now=now,
        )
        with self._session_factory() as session:
            with ImportWriteTransaction(SqlAlchemyImportUnitOfWork(session)):
                write_conversion_failure(session, prepared)
