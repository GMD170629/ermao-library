"""SQL expression for a readable resource's declared media kind."""

from __future__ import annotations

from typing import cast

from sqlalchemy.sql.elements import ColumnElement

from app.models import LibraryReadableResource


def resource_media_kind(
    resource: type[LibraryReadableResource] = LibraryReadableResource,
) -> ColumnElement[str]:
    """Return the normalized media-kind column owned by the resource."""

    return cast(ColumnElement[str], resource.media_kind)
