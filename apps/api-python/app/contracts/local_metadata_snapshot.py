"""Bounded, typed observations retained independently of source priority."""

from dataclasses import dataclass, fields, replace

from pydantic import TypeAdapter

from app.contracts.local_metadata import LocalMetadataSource
from app.contracts.publication_metadata import PublicationMetadata


@dataclass(frozen=True, slots=True)
class LocalMetadataObservation:
    source: LocalMetadataSource
    metadata: PublicationMetadata
    cover_path: str | None = None


_OBSERVATIONS = TypeAdapter(tuple[LocalMetadataObservation, ...])


def encode_observations(values: tuple[LocalMetadataObservation, ...]) -> str:
    return _OBSERVATIONS.dump_json(values).decode()


def decode_observations(value: str) -> tuple[LocalMetadataObservation, ...]:
    return _OBSERVATIONS.validate_json(value)


def merge_observations(
    values: tuple[LocalMetadataObservation, ...],
) -> dict[LocalMetadataSource, PublicationMetadata]:
    """Keep the first nonempty field within each source, in caller-owned order."""
    grouped: dict[LocalMetadataSource, PublicationMetadata] = {}
    for candidate in values:
        previous = grouped.get(candidate.source, PublicationMetadata())
        grouped[candidate.source] = replace(
            previous,
            **{
                field.name: getattr(candidate.metadata, field.name)
                for field in fields(PublicationMetadata)
                if getattr(previous, field.name) in (None, "", ())
            },
        )
    return grouped
