"""Composition root for media application commands."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.media.application.resource_query import MediaResourceQuery
from app.modules.media.infrastructure import http_streaming as media_streaming
from app.modules.media.infrastructure.page_index import (
    get_library_file,
    get_page_unit,
    list_page_units_for_volume,
    load_read_only_page_index_projection,
)
from app.modules.media.infrastructure.resource_repository import (
    SqlAlchemyMediaResourceRepository,
)
from app.modules.media.infrastructure.volume_archive import ZipVolumeArchiveWriter
from app.modules.media.public import (
    ReadOnlyVolumePageIndex,
    ResolvedVolumePageIndex,
    VolumePageIndexProjection,
)


def load_read_only_volume_page_index(
    db: Session,
    volume_id: str,
) -> VolumePageIndexProjection:
    return load_read_only_page_index_projection(db, volume_id)


def resolve_read_only_volume_page_index(
    projection: VolumePageIndexProjection,
) -> ResolvedVolumePageIndex:
    return ReadOnlyVolumePageIndex().execute(projection)


class MediaPageIndex:
    get_library_file = staticmethod(get_library_file)
    get_page_unit = staticmethod(get_page_unit)
    list_page_units_for_volume = staticmethod(list_page_units_for_volume)
    load_read_only = staticmethod(load_read_only_volume_page_index)
    resolve_read_only = staticmethod(resolve_read_only_volume_page_index)


media_page_index = MediaPageIndex()


def media_resource_query(db: Session) -> MediaResourceQuery:
    return MediaResourceQuery(SqlAlchemyMediaResourceRepository(db))


def volume_archive_dependencies(
    db: Session, settings: Settings
) -> tuple[SqlAlchemyMediaResourceRepository, ZipVolumeArchiveWriter]:
    return SqlAlchemyMediaResourceRepository(db), ZipVolumeArchiveWriter(settings)


__all__ = [
    "load_read_only_volume_page_index",
    "media_page_index",
    "media_resource_query",
    "media_streaming",
    "resolve_read_only_volume_page_index",
    "volume_archive_dependencies",
]
