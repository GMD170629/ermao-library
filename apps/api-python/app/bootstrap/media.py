"""Composition root for media queries and original-asset delivery."""

from sqlalchemy.orm import Session

from app.modules.media.application.page_index import (
    ReadOnlyResourcePageIndex,
    ResolvedResourcePageIndex,
    ResourcePageIndexProjection,
)
from app.modules.media.application.resource_query import MediaResourceQuery
from app.modules.media.infrastructure import http_streaming as media_streaming
from app.modules.media.infrastructure.page_index import (
    get_page_unit,
    get_resource_asset,
    list_page_units_for_resource,
    load_read_only_page_index_projection,
)
from app.modules.media.infrastructure.resource_repository import (
    SqlAlchemyMediaResourceRepository,
)


def load_read_only_resource_page_index(
    db: Session,
    resource_id: str,
) -> ResourcePageIndexProjection:
    return load_read_only_page_index_projection(db, resource_id)


def resolve_read_only_resource_page_index(
    projection: ResourcePageIndexProjection,
) -> ResolvedResourcePageIndex:
    return ReadOnlyResourcePageIndex().execute(projection)


class MediaPageIndex:
    get_resource_asset = staticmethod(get_resource_asset)
    get_page_unit = staticmethod(get_page_unit)
    list_page_units_for_resource = staticmethod(list_page_units_for_resource)
    load_read_only = staticmethod(load_read_only_resource_page_index)
    resolve_read_only = staticmethod(resolve_read_only_resource_page_index)


media_page_index = MediaPageIndex()


def media_resource_query(db: Session) -> MediaResourceQuery:
    return MediaResourceQuery(SqlAlchemyMediaResourceRepository(db))


__all__ = [
    "load_read_only_resource_page_index",
    "media_page_index",
    "media_resource_query",
    "media_streaming",
    "resolve_read_only_resource_page_index",
]
