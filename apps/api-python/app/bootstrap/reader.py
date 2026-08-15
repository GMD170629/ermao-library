"""Reader capability composition root."""

from sqlalchemy.orm import Session

from app.bootstrap.publications import (
    open_publication,
)
from app.core.config import Settings
from app.modules.reader.application.volume_reader import VolumeReaderService
from app.modules.reader.infrastructure.clock import SystemReaderClock
from app.modules.reader.infrastructure.publication_locator_index import (
    NormalizedPublicationLocatorIndex,
)
from app.modules.reader.infrastructure.volume_repository import (
    SqlAlchemyReaderVolumeRepository,
)


def reader_volume_service(session: Session, settings: Settings) -> VolumeReaderService:
    repository = SqlAlchemyReaderVolumeRepository(session)
    return VolumeReaderService(
        repository,
        session,
        SystemReaderClock(),
        NormalizedPublicationLocatorIndex(
            open_publication(session, settings),
            repository,
        ),
    )


__all__ = ["reader_volume_service"]
