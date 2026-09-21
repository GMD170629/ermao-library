"""Project one explicit file observation into selected system metadata fields."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.modules.automation.domain.access import AutomationAccessError
from app.modules.library.public import MetadataChange, MetadataTarget, MetadataValue
from app.modules.metadata.public import MetadataFileSource, StandardMetadataObservation


@dataclass(frozen=True)
class RefreshMetadataChange:
    target_type: MetadataTarget
    target_id: str
    expected_revision: str
    node_id: str
    source: MetadataFileSource
    fields: tuple[str, ...]
    expected_file_revision: str
    mode: Literal["patch", "fill_missing"] = "fill_missing"
    override_fields: frozenset[str] = frozenset()
    sidecar_relative_path: str | None = None


def project_file_metadata(
    request: RefreshMetadataChange, observation: StandardMetadataObservation
) -> MetadataChange:
    if observation.file_revision != request.expected_file_revision:
        raise AutomationAccessError("SOURCE_CHANGED")
    if not request.fields or len(set(request.fields)) != len(request.fields):
        raise AutomationAccessError("INVALID_FIELDS")
    metadata = observation.metadata
    values: dict[str, MetadataValue] = {
        "title": metadata.volume_title or metadata.title
        if request.target_type == "resource"
        else metadata.title,
        "author": metadata.author,
        "description": metadata.description,
        "tags": metadata.subjects,
        "series_name": metadata.series_name,
        "series_index": metadata.series_index,
        "resource_index": metadata.volume_index,
        "publisher": metadata.publisher,
        "language": metadata.language,
        "identifier": metadata.identifier,
        "isbn": metadata.isbn,
        "narrator": " / ".join(metadata.narrators) if metadata.narrators else None,
        "abridged": metadata.abridged,
        "published_at": metadata.published_at,
    }
    selected: dict[str, MetadataValue] = {}
    for name in request.fields:
        if name not in values:
            raise AutomationAccessError("INVALID_FIELDS")
        value = values[name]
        if value in (None, "", ()):
            raise AutomationAccessError("SOURCE_FIELD_UNAVAILABLE")
        if name == "published_at":
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError as error:
                raise AutomationAccessError(
                    "SOURCE_DATE_PRECISION_UNSUPPORTED"
                ) from error
            value = (
                parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            ).isoformat()
        selected[name] = value
    return MetadataChange(
        request.target_type,
        request.target_id,
        request.expected_revision,
        request.mode,
        selected,
        override_fields=request.override_fields,
        provenance={
            "node_id": request.node_id,
            "source": observation.source,
            "relative_path": observation.relative_path,
            "file_revision": observation.file_revision,
            "format": observation.format,
        },
    )
