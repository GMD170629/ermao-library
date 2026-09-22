"""Bounded owned job references from the two existing durable operation stores."""

from sqlalchemy import case, literal, select, union_all
from sqlalchemy.orm import Session

from app.models import (
    FileDeletePlanRow,
    LibraryFileMoveOperation,
    LibraryFileMoveTarget,
    MetadataStandardWriteOperation,
    MetadataStandardWriteTarget,
)
from app.modules.automation.application.operation_management import OperationReference
from app.modules.automation.infrastructure.upload_schema import AutomationUploadRow


class SqlAlchemyOperationHistory:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _query(self, user_id: str):
        return union_all(
            select(
                FileDeletePlanRow.id.label("id"),
                FileDeletePlanRow.grant_id.label("grant_id"),
                FileDeletePlanRow.payload["created_at_ms"]
                .as_integer()
                .label("created_at_ms"),
                literal("file_delete").label("kind"),
            ).where(
                FileDeletePlanRow.user_id == user_id,
                FileDeletePlanRow.payload["executing"].as_boolean().is_(True),
            ),
            select(
                AutomationUploadRow.id.label("id"),
                AutomationUploadRow.grant_id.label("grant_id"),
                AutomationUploadRow.created_at_ms.label("created_at_ms"),
                case(
                    (
                        AutomationUploadRow.payload["spec"]["purpose"].as_string()
                        == "book",
                        "book_upload",
                    ),
                    (
                        AutomationUploadRow.payload["spec"]["purpose"].as_string()
                        == "replace",
                        "file_replace",
                    ),
                    else_="cover_upload",
                ).label("kind"),
            ).where(AutomationUploadRow.user_id == user_id),
            select(
                LibraryFileMoveOperation.id.label("id"),
                LibraryFileMoveOperation.grant_id.label("grant_id"),
                LibraryFileMoveOperation.created_at_ms.label("created_at_ms"),
                literal("file_move").label("kind"),
            ).where(LibraryFileMoveOperation.user_id == user_id),
            select(
                MetadataStandardWriteOperation.id.label("id"),
                MetadataStandardWriteOperation.grant_id.label("grant_id"),
                MetadataStandardWriteOperation.created_at_ms.label("created_at_ms"),
                literal("metadata_writeback").label("kind"),
            ).where(MetadataStandardWriteOperation.user_id == user_id),
        ).subquery()

    def recent(
        self, user_id: str, library_ids: frozenset[str]
    ) -> tuple[OperationReference, ...]:
        rows = self._query(user_id)
        visible = (
            select(rows)
            .where(
                ~select(AutomationUploadRow.id)
                .where(
                    AutomationUploadRow.id == rows.c.id,
                    AutomationUploadRow.library_id.not_in(library_ids),
                )
                .exists(),
                ~select(LibraryFileMoveTarget.operation_id)
                .where(
                    LibraryFileMoveTarget.operation_id == rows.c.id,
                    (LibraryFileMoveTarget.source_library_id.not_in(library_ids))
                    | (
                        LibraryFileMoveTarget.destination_library_id.not_in(library_ids)
                    ),
                )
                .exists(),
                ~select(MetadataStandardWriteTarget.operation_id)
                .where(
                    MetadataStandardWriteTarget.operation_id == rows.c.id,
                    MetadataStandardWriteTarget.library_id.not_in(library_ids),
                )
                .exists(),
            )
            .order_by(rows.c.created_at_ms.desc(), rows.c.id)
            .limit(50)
        )
        return tuple(
            OperationReference(row.id, row.grant_id, row.kind, row.created_at_ms)
            for row in self._db.execute(visible)
        )

    def get(self, operation_id: str, user_id: str) -> OperationReference | None:
        rows = self._query(user_id)
        row = self._db.execute(
            select(rows).where(rows.c.id == operation_id)
        ).one_or_none()
        return (
            OperationReference(row.id, row.grant_id, row.kind, row.created_at_ms)
            if row
            else None
        )
