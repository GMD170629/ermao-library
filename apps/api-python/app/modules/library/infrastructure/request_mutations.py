"""SQL-only persistence for prepared Library request mutations."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.authorization import resource_visibility_predicate
from app.core.sql_batches import sqlite_parameter_chunks
from app.models import (
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    ReaderResourceProgress,
)
from app.models.common import cuid
from app.models.organize import OrganizeJob
from app.modules.library.application.request_mutations import (
    BookRecordMutation,
    BulkBookMutation,
    BulkReadingStatusMutation,
    BulkShelfMembershipMutation,
    CoverMutation,
    CoverPublicationFailure,
    DetailPreferenceMutation,
    MetadataApplyMutation,
    MetadataApplyResult,
)
from app.modules.library.infrastructure import books, projections, storage
from app.modules.library.infrastructure.facet_sync import (
    PreparedBookFacetWrite,
    execute_book_facet_write,
)
from app.modules.shelf.public import ShelfBookMembershipPort

EventWriter = Callable[[Session, list[object]], None]
MetadataWriter = Callable[[Session, tuple[object, ...]], tuple[str, ...]]


def load_metadata_apply_job_ids(db: Session, book_id: str) -> tuple[str, ...]:
    return tuple(
        str(job_id)
        for job_id in db.scalars(
            select(OrganizeJob.id).where(
                OrganizeJob.book_id == book_id,
                OrganizeJob.status.in_(("PENDING", "REVIEWING", "FAILED")),
            )
        ).all()
    )


def _prepared_facets(value: object | None) -> PreparedBookFacetWrite | None:
    if value is None:
        return None
    if not isinstance(value, PreparedBookFacetWrite):
        raise TypeError("facet write must be prepared before the mutation")
    return value


class SqlAlchemyLibraryRequestMutations:
    def __init__(
        self,
        db: Session,
        *,
        shelf_memberships: ShelfBookMembershipPort,
        write_events: EventWriter,
        write_metadata: MetadataWriter,
    ) -> None:
        self._db = db
        self._shelf_memberships = shelf_memberships
        self._write_events = write_events
        self._write_metadata = write_metadata

    def save_detail_preference(self, command: DetailPreferenceMutation) -> None:
        projections.save_detail_preference(
            self._db,
            user_id=command.user_id,
            book_id=command.book_id,
            selected_tab=command.selected_tab,
            now=command.now,
        )

    def update_book(self, command: BookRecordMutation) -> dict[str, object] | None:
        facet_write = _prepared_facets(command.facet_write)
        updated = books.update_book_fields(
            self._db, command.book_id, dict(command.values)
        )
        if facet_write is not None:
            execute_book_facet_write(self._db, facet_write)
        self._write_metadata(self._db, command.writeback_intents)
        return updated

    def update_books(self, command: BulkBookMutation) -> int:
        facet_write = _prepared_facets(command.facet_write)
        updates = tuple((book_id, dict(values)) for book_id, values in command.updates)
        updated = books.update_book_fields_bulk(self._db, updates)
        if facet_write is not None:
            execute_book_facet_write(self._db, facet_write)
        self._write_metadata(self._db, command.writeback_intents)
        result_count = (
            command.reported_count if command.reported_count is not None else updated
        )
        if result_count and command.events:
            self._write_events(self._db, list(command.events))
        return result_count

    def update_reading_status(self, command: BulkReadingStatusMutation) -> int:
        rows = self._db.execute(
            select(
                LibraryReadableResource.id,
                LibraryReadableResource.format,
                LibraryReadableResource.book_id,
            )
            .join(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .where(
                LibraryReadableResource.book_id.in_(command.book_ids),
                LibraryReadableResource.enablement_state == "ENABLED",
                resource_visibility_predicate(command.context),
            )
            .order_by(
                LibraryReadableResource.book_id.asc(),
                LibraryReadableResourceMetadata.resource_index.asc().nulls_last(),
                LibraryReadableResource.id.asc(),
            )
        ).all()
        resource_ids = tuple(str(row.id) for row in rows)
        updated = len({str(row.book_id) for row in rows})
        statements: list[Executable] = []
        if command.status == "UNREAD":
            statements.extend(
                delete(ReaderResourceProgress).where(
                    ReaderResourceProgress.user_id == command.context.user_id,
                    ReaderResourceProgress.resource_id.in_(chunk),
                )
                for chunk in sqlite_parameter_chunks(resource_ids, parameters_per_row=1)
            )
        else:
            target_percent = 100.0 if command.status == "FINISHED" else 0.01
            progress_rows = tuple(
                {
                    "id": cuid(),
                    "user_id": command.context.user_id,
                    "resource_id": str(row.id),
                    "reader_type": (
                        "audio"
                        if str(row.format).upper() in {"M4B", "M4A", "MP3"}
                        else "comic"
                        if str(row.format).upper() in {"CBR", "CBZ", "RAR", "ZIP"}
                        else "pdf"
                        if str(row.format).upper() == "PDF"
                        else "epub"
                    ),
                    "position": "0",
                    "percent": target_percent,
                    "extra": "{}",
                    "schema_version": 3,
                    "progressed_at": command.now,
                    "source_protocol": "SHUKU_WEB",
                    "created_at": command.now,
                    "updated_at": command.now,
                }
                for row in rows
            )
            statements.extend(
                sqlite_insert(ReaderResourceProgress)
                .values(list(chunk))
                .on_conflict_do_update(
                    index_elements=[
                        ReaderResourceProgress.user_id,
                        ReaderResourceProgress.resource_id,
                    ],
                    set_={
                        ReaderResourceProgress.percent: target_percent,
                        ReaderResourceProgress.updated_at: command.now,
                    },
                )
                for chunk in sqlite_parameter_chunks(
                    progress_rows, parameters_per_row=12
                )
            )
        for statement in statements:
            self._db.execute(statement)
        if updated and command.events:
            self._write_events(self._db, list(command.events))
        return updated

    def update_shelf_membership(self, command: BulkShelfMembershipMutation) -> int:
        if command.membership == "ADD":
            self._shelf_memberships.add_books(
                shelf_id=command.shelf_id,
                book_ids=command.book_ids,
                now=command.now,
            )
        else:
            self._shelf_memberships.remove_books(
                shelf_id=command.shelf_id,
                book_ids=command.book_ids,
            )
        if command.book_ids and command.events:
            self._write_events(self._db, list(command.events))
        return len(command.book_ids)

    def update_covers(self, command: CoverMutation) -> int:
        cover_rows = tuple(
            {
                "id": record.book_id,
                "cover_path": record.cover_path,
                "cover_status": record.cover_status,
                "updated_at": command.now,
            }
            for record in command.records
        )
        updated = storage.update_book_covers(self._db, cover_rows)
        self._write_metadata(self._db, command.writeback_intents)
        if updated and command.events:
            self._write_events(self._db, list(command.events))
        return updated

    def apply_metadata(self, command: MetadataApplyMutation) -> MetadataApplyResult:
        facet_write = _prepared_facets(command.facet_write)
        finish_jobs_statement = (
            update(OrganizeJob)
            .where(OrganizeJob.id.in_(command.finished_job_ids))
            .values(
                status="APPLIED",
                summary="元数据已应用，整理完成",
                error_summary=None,
                updated_at=command.now,
            )
            if command.finished_job_ids
            else None
        )
        resource_rows = tuple(dict(row) for row in command.resource_rows)
        book = books.update_book_fields(
            self._db, command.book_id, dict(command.book_values)
        )
        if resource_rows:
            self._db.execute(update(LibraryReadableResource), list(resource_rows))
        if facet_write is not None:
            execute_book_facet_write(self._db, facet_write)
        if finish_jobs_statement is not None:
            self._db.execute(finish_jobs_statement)
        operation_ids = self._write_metadata(self._db, command.writeback_intents)
        return MetadataApplyResult(
            book=book,
            finished_job_ids=command.finished_job_ids,
            writeback_operation_ids=tuple(str(value) for value in operation_ids),
        )

    def compensate_cover_publication(
        self,
        command: CoverPublicationFailure,
    ) -> bool:
        result = self._db.execute(
            update(LibraryBookMetadata)
            .where(
                LibraryBookMetadata.book_id == command.book_id,
                LibraryBookMetadata.cover_path == command.expected_cover_path,
                LibraryBookMetadata.updated_at == command.expected_updated_at,
            )
            .values(
                cover_path=command.fallback_cover_path,
                cover_status="FAILED",
                updated_at=command.now,
            )
        )
        return bool(getattr(result, "rowcount", 0))


__all__ = ["SqlAlchemyLibraryRequestMutations", "load_metadata_apply_job_ids"]
