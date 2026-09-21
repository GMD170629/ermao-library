"""One standard audio-tag projection shared by reads and write verification."""

from collections.abc import Mapping
from typing import Literal

from app.contracts.publication_metadata import PublicationMetadata

AudioFormat = Literal["MP3", "M4A", "M4B", "FLAC"]
ID3_FIELDS = {
    "title": "TIT2",
    "authors": "TPE1",
    "description": "COMM::eng",
    "subjects": "TCON",
    "publisher": "TPUB",
    "language": "TLAN",
    "published_at": "TDRC",
}
FLAC_FIELDS = {
    "title": "title",
    "authors": "artist",
    "description": "description",
    "subjects": "genre",
    "publisher": "publisher",
    "language": "language",
    "published_at": "date",
}
MP4_FIELDS = {
    "title": "©nam",
    "authors": "©ART",
    "description": "desc",
    "subjects": "©gen",
    "published_at": "©day",
}


def audio_tag_metadata(
    tags: Mapping[str, object], format: AudioFormat, *, id3_version: int = 4
) -> PublicationMetadata:
    mapping = (
        ID3_FIELDS
        if format == "MP3"
        else FLAC_FIELDS
        if format == "FLAC"
        else MP4_FIELDS
    )

    def values(name: str) -> tuple[str, ...]:
        key = mapping.get(name)
        value = tags.get(key) if key else None
        value = getattr(value, "text", value)
        if value is None:
            return ()
        result = (
            tuple(str(item) for item in value)
            if isinstance(value, (list, tuple))
            else (str(value),)
        )
        # ID3v2.3 TPE1 uses slash-separated people, unlike v2.4 text lists.
        if format == "MP3" and id3_version == 3 and name == "authors":
            return tuple(part for item in result for part in item.split("/") if part)
        return result

    def text(name: str) -> str | None:
        return " / ".join(values(name)) or None

    return PublicationMetadata(
        title=text("title"),
        authors=values("authors"),
        description=text("description"),
        subjects=values("subjects"),
        publisher=text("publisher"),
        language=text("language"),
        published_at=text("published_at"),
    )
