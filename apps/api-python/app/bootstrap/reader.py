"""Reader capability composition root."""

from sqlalchemy.orm import Session

from app.bootstrap.media import load_read_only_resource_page_index
from app.core.config import Settings
from app.modules.reader.application.resource_reader import ResourceReaderService
from app.modules.reader.infrastructure.clock import SystemReaderClock
from app.modules.reader.infrastructure.comic_page_index import MediaComicPageIndex
from app.modules.reader.infrastructure.resource_locator_index import (
    ResourceLocatorIndex,
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
        ResourceLocatorIndex(
            repository,
            MediaComicPageIndex(
                lambda resource_id: load_read_only_resource_page_index(
                    session, resource_id
                )
            ),
        ),
    )


__all__ = ["reader_resource_service"]
