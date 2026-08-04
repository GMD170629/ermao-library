"""Reader capability composition root."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.reader.application.volume_reader import VolumeReaderService
from app.modules.reader.infrastructure.epub_navigation_recovery import (
    FileReaderEpubNavigationParser,
)
from app.modules.reader.infrastructure.volume_repository import (
    SqlAlchemyReaderVolumeRepository,
)


def reader_volume_service(session: Session, settings: Settings) -> VolumeReaderService:
    return VolumeReaderService(
        SqlAlchemyReaderVolumeRepository(session),
        session,
        FileReaderEpubNavigationParser(settings.resolved_storage_root),
    )


__all__ = ["reader_volume_service"]
