"""Record a published file's observation and audit in the caller's transaction."""

from datetime import UTC, datetime

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.library.infrastructure.operations import (
    prepare_operation_write,
    write_prepared_operation,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.metadata.public import (
    PlannedStandardWrite,
    PreparedStandardFile,
    PublicationMetadata,
    StandardWritePlan,
)

_METADATA = TypeAdapter(PublicationMetadata)


class SqlAlchemyStandardWriteIndex:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        operation_id: str,
        plan: StandardWritePlan,
        target: PlannedStandardWrite,
        proof: PreparedStandardFile,
    ) -> None:
        now = datetime.now(UTC)
        node = self._db.scalar(
            select(LibrarySourceNode)
            .where(
                LibrarySourceNode.library_id == target.file.library_id,
                LibrarySourceNode.relative_path == target.file.relative_path,
            )
            .execution_options(populate_existing=True)
        )
        if node is not None:
            node.observed_size_bytes = proof.identity.size
            node.observed_mtime_ns = proof.identity.mtime_ns
            node.observed_at = now
            node.updated_at = now
            for asset in self._db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.source_node_id == node.id
                )
            ):
                asset.updated_at = now
        before = _METADATA.dump_python(target.before, mode="json")
        after = _METADATA.dump_python(target.file.values, mode="json")
        prepared = prepare_operation_write(
            user_id=plan.user_id,
            action="WRITE_STANDARD_METADATA",
            target_type="sourceNode",
            target_id=target.source_node_id,
            summary="已写入文件元数据 / File metadata written",
            payload={
                "grantId": plan.grant_id,
                "operationId": operation_id,
                "libraryId": target.file.library_id,
                "relativePath": target.file.relative_path,
                "format": target.file.format,
                "fields": sorted(target.file.fields),
                "before": {key: before[key] for key in target.file.fields},
                "after": {key: after[key] for key in target.file.fields},
            },
            inverse={},
            now=now,
            undoable=False,
        )
        write_prepared_operation(self._db, prepared)
