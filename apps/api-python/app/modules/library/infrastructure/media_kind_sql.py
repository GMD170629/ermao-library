"""SQL expression for a volume's effective media kind."""

from __future__ import annotations

from sqlalchemy import and_, case, func
from sqlalchemy.sql.elements import ColumnElement

from app.models.library import LibraryVolume

_AUDIO_FORMATS = ("AUDIO", "AUDIOBOOK", "MP3", "M4A", "M4B")
_COMIC_FORMATS = ("COMIC", "CBR", "CBZ", "RAR", "ZIP")
_ASSIGNED_KINDS = ("EBOOK", "COMIC", "AUDIOBOOK")


def volume_effective_media_kind(
    volume: type[LibraryVolume] = LibraryVolume,
) -> ColumnElement[str]:
    assigned = func.upper(func.coalesce(volume.suggested_media_kind, ""))
    fmt = func.upper(volume.format)
    return case(
        (
            and_(
                volume.classification_source == "USER",
                assigned.in_(_ASSIGNED_KINDS),
            ),
            assigned,
        ),
        (fmt.in_(_AUDIO_FORMATS), "AUDIOBOOK"),
        (fmt.in_(_COMIC_FORMATS), "COMIC"),
        else_="EBOOK",
    )
