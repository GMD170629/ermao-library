"""Composition root for local cover actions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.bootstrap.reader import reader_v5_library_queries
from app.core.config import Settings
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
)
from app.modules.library.application.bulk_operations import ExecuteBulkCovers
from app.modules.library.application.local_cover_regeneration import (
    RegenerateBulkBookCovers,
    RegenerateLocalMetadataCovers,
)
from app.modules.library.application.resource_cover import (
    UploadResourceCover,
)
from app.modules.library.infrastructure.bulk_operations import (
    SqlAlchemyBulkBookOperations,
)
from app.modules.library.infrastructure.local_cover_regeneration import (
    FilesystemLocalMetadataCoverParser,
    SqlAlchemyBulkCoverRegenerationOperations,
    SqlAlchemyLocalCoverSources,
)
from app.modules.library.infrastructure.resource_commands import (
    SqlAlchemyResourceMetadata,
)
from app.modules.library.infrastructure.resource_cover import (
    FilesystemResourceCoverPublication,
    SqlAlchemyResourceCover,
)
from app.modules.library.infrastructure.source_node_cover import (
    FilesystemSourceNodeCoverPublication,
)


def regenerate_local_metadata_covers(
    db: Session,
    settings: Settings,
) -> RegenerateLocalMetadataCovers:
    metadata_adapter = RegistryResourceAdapterExecutor()
    return RegenerateLocalMetadataCovers(
        access=SqlAlchemyResourceMetadata(db),
        sources=SqlAlchemyLocalCoverSources(db),
        parser=FilesystemLocalMetadataCoverParser(
            metadata_adapter.local_metadata_inspector
        ),
        resource_covers=FilesystemResourceCoverPublication(
            settings.resolved_storage_root
        ),
        source_covers=FilesystemSourceNodeCoverPublication(
            settings.resolved_storage_root
        ),
        unit_of_work=db,
    )


def upload_resource_cover(db: Session, settings: Settings) -> UploadResourceCover:
    return UploadResourceCover(
        SqlAlchemyResourceMetadata(db),
        SqlAlchemyResourceCover(db),
        FilesystemResourceCoverPublication(settings.resolved_storage_root),
        db,
    )


def bulk_covers(db: Session, settings: Settings) -> ExecuteBulkCovers:
    local_covers = regenerate_local_metadata_covers(db, settings)
    return ExecuteBulkCovers(
        SqlAlchemyBulkBookOperations(
            db,
            storage_root=settings.resolved_storage_root,
            reader_queries=reader_v5_library_queries(db),
        ),
        db,
        RegenerateBulkBookCovers(
            covers=local_covers,
            operations=SqlAlchemyBulkCoverRegenerationOperations(db),
            unit_of_work=db,
        ),
    )


__all__ = [
    "bulk_covers",
    "regenerate_local_metadata_covers",
    "upload_resource_cover",
]
