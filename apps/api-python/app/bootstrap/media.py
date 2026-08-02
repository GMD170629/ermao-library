"""Composition root for media application commands."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.media.application.resource_query import MediaResourceQuery
from app.modules.media.infrastructure import http_streaming as media_streaming
from app.modules.media.infrastructure.page_index import (
    ensure_volume_page_index as build_volume_page_index,
)
from app.modules.media.infrastructure.page_index import (
    get_library_file,
    get_page_unit,
    list_page_units_for_volume,
)
from app.modules.media.infrastructure.resource_repository import (
    SqlAlchemyMediaResourceRepository,
)
from app.modules.media.public import execute_media_write


def ensure_volume_page_index(
    db: Session,
    settings: Settings,
    volume_id: str,
) -> int:
    return execute_media_write(
        db,
        lambda: build_volume_page_index(db, settings, volume_id),
    )


class MediaPageIndex:
    ensure_volume_page_index = staticmethod(ensure_volume_page_index)
    get_library_file = staticmethod(get_library_file)
    get_page_unit = staticmethod(get_page_unit)
    list_page_units_for_volume = staticmethod(list_page_units_for_volume)


media_page_index = MediaPageIndex()


def media_resource_query(db: Session) -> MediaResourceQuery:
    return MediaResourceQuery(SqlAlchemyMediaResourceRepository(db))


__all__ = [
    "ensure_volume_page_index",
    "media_page_index",
    "media_resource_query",
    "media_streaming",
]
