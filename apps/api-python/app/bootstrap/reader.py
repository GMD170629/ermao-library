"""Reader capability composition root."""

from sqlalchemy.orm import Session

from app.bootstrap.publications import (
    open_publication,
)
from app.core.config import Settings
from app.modules.reader.application.resource_reader import ResourceReaderService
from app.modules.reader.infrastructure.clock import SystemReaderClock
from app.modules.reader.infrastructure.publication_locator_index import (
    NormalizedPublicationLocatorIndex,
)
from app.modules.reader.infrastructure.resource_repository import (
    SqlAlchemyReaderResourceRepository,
)


def reader_resource_service(
    session: Session, settings: Settings
) -> ResourceReaderService:
    repository = SqlAlchemyReaderResourceRepository(session)
    return ResourceReaderService(
        repository,
        session,
        SystemReaderClock(),
        NormalizedPublicationLocatorIndex(
            open_publication(session, settings),
            repository,
        ),
    )


__all__ = ["reader_resource_service"]
