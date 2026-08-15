"""Stable media application contracts."""

from pathlib import Path

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.media.application.page_index import (
    ReadOnlyVolumePageIndex,
    ResolvedVolumePageIndex,
    VolumePageIndexProjection,
    VolumePageSource,
    VolumePageUnit,
)
from app.modules.media.infrastructure import http_streaming
from app.modules.media.infrastructure.page_index import (
    load_read_only_page_index_projection,
)


def load_persisted_volume_page_index(
    db: Session,
    volume_id: str,
) -> ResolvedVolumePageIndex:
    """Load the authoritative persisted comic page order without archive scanning."""

    return ReadOnlyVolumePageIndex().execute(
        load_read_only_page_index_projection(db, volume_id)
    )


def stored_media_path(path: str | None, settings: Settings) -> Path | None:
    return http_streaming.stored_path(path, settings, database_backed=True)


def send_comic_page(
    *,
    archive_path: Path | None,
    entry_name: str | None,
    request: Request,
    actor_id: str,
    settings: Settings,
    media_type: str | None,
    resource_id: str,
) -> Response:
    return http_streaming.send_comic_page_zip_entry(
        archive_path,
        entry_name,
        request,
        actor_id,
        settings,
        media_type,
        route="reader-v4-comic-page",
        file_id=resource_id,
    )


def send_comic_archive(
    *,
    archive_path: Path | None,
    request: Request,
    actor_id: str,
    media_type: str,
    resource_id: str,
) -> Response:
    return http_streaming.send_file(
        archive_path,
        request,
        actor_id,
        media_type=media_type,
        route="reader-v4-comic-archive",
        file_id=resource_id,
        as_attachment=True,
    )

__all__ = [
    "ReadOnlyVolumePageIndex",
    "ResolvedVolumePageIndex",
    "VolumePageIndexProjection",
    "VolumePageSource",
    "VolumePageUnit",
    "load_persisted_volume_page_index",
    "send_comic_archive",
    "send_comic_page",
    "stored_media_path",
]
