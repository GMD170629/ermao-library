"""Wire recognition to the existing library metadata patch application."""

from sqlalchemy.orm import Session

from app.modules.library.application.metadata_patches import ApplyMetadataPatches
from app.modules.library.application.recognized_metadata import RemoteCoverDownloadPort
from app.modules.library.infrastructure.metadata_patches import (
    SqlAlchemyMetadataPatches,
)
from app.modules.library.infrastructure.recognized_metadata import (
    SafeRemoteCoverDownloader,
)
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.public import (
    load_metadata_writeback_projection,
    metadata_writeback_enabled,
    persist_metadata_writeback_intents,
    prepare_metadata_writeback_intents,
)


def recognition_patches(db: Session, *, prepared_covers: dict[tuple[str, str], tuple[str, str]] | None = None) -> ApplyMetadataPatches:
    return ApplyMetadataPatches(SqlAlchemyMetadataPatches(db, prepared_covers=prepared_covers), db)


def recognition_cover_downloader() -> RemoteCoverDownloadPort:
    return SafeRemoteCoverDownloader()


def recognition_writeback(db: Session, book_id: str, resource_id: str | None, *, source: str = "MANUAL", task_id: str | None = None) -> bool:
    if not metadata_writeback_enabled(db):
        db.close()
        return False
    projection = load_metadata_writeback_projection(db, book_id=book_id, resource_id=resource_id)
    db.close()
    intents = prepare_metadata_writeback_intents(projection, source=source, lookup_task_id=task_id, resource_id=resource_id)
    with MetadataWriteTransaction(db):
        persist_metadata_writeback_intents(db, intents)
    return bool(intents)
