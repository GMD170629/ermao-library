"""Provider field names shared by recognition proposals and manual selection."""

from types import MappingProxyType

PROVIDER_METADATA_FIELDS = MappingProxyType({
    "title": "title", "author": "author", "description": "description",
    "tags": "tags", "seriesName": "series_name", "seriesIndex": "series_index",
    "publisher": "publisher", "publishedAt": "published_at", "language": "language",
    "isbn": "isbn", "identifier": "identifier", "narrator": "narrator",
    "abridged": "abridged", "resourceIndex": "resource_index", "coverUrl": "cover_ref",
})


def recognized_field_name(field: str) -> str:
    return PROVIDER_METADATA_FIELDS.get(field, "cover_ref" if field == "cover" else field)
