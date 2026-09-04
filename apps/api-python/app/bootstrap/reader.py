"""Reader capability composition root."""

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.reader.application.resource_reader_v5 import ResourceReaderV5Service
from app.modules.reader.application.v5_library_queries import (
    ReaderV5LibraryPresentationQueryPort,
)
from app.modules.reader.infrastructure.clock import SystemReaderClock
from app.modules.reader.infrastructure.v5_library_queries import (
    SqlAlchemyReaderV5LibraryPresentationQueries,
    reader_v5_latest_read_at_expression,
    reader_v5_progress_expression,
    reader_v5_reading_status_expression,
)
from app.modules.reader.infrastructure.v5_repository import (
    SqlAlchemyReaderV5Repository,
)

if TYPE_CHECKING:
    from app.modules.reader.application.resource_reader import ResourceReaderService


def reader_resource_service(
    session: Session, settings: Settings
) -> "ResourceReaderService":
    # Keep the retired v4 implementation out of the v5 import graph.  OPDS and
    # other legacy adapters still opt into this composition function explicitly.
    from app.bootstrap.media import load_read_only_resource_page_index
    from app.modules.reader.application.resource_reader import ResourceReaderService
    from app.modules.reader.infrastructure.comic_page_index import MediaComicPageIndex
    from app.modules.reader.infrastructure.resource_locator_index import (
        ResourceLocatorIndex,
    )
    from app.modules.reader.infrastructure.resource_repository import (
        SqlAlchemyReaderResourceRepository,
    )

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


def reader_v5_service(session: Session, settings: Settings) -> ResourceReaderV5Service:
    """Compose the v5 application service with isolated ORM persistence."""

    del settings
    return ResourceReaderV5Service(
        SqlAlchemyReaderV5Repository(session),
        session,
        SystemReaderClock(),
    )


def reader_v5_library_queries(
    session: Session,
) -> ReaderV5LibraryPresentationQueryPort:
    """Compose Reader's public Library presentation query port."""

    return SqlAlchemyReaderV5LibraryPresentationQueries(session)


__all__ = [
    "reader_resource_service",
    "reader_v5_latest_read_at_expression",
    "reader_v5_library_queries",
    "reader_v5_progress_expression",
    "reader_v5_reading_status_expression",
    "reader_v5_service",
]
