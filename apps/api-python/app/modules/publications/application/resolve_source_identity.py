"""Resolve the byte identity of an authorized publication source."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationSourceHasher,
    PublicationSourceRepository,
)
from app.modules.publications.domain.model import PublicationNotFoundError
from app.modules.publications.domain.navigation import canonical_original_file_hash


@dataclass(frozen=True, slots=True)
class PublicationSourceIdentity:
    original_file_hash: str
    source_format: str


class ResolvePublicationSourceIdentity:
    def __init__(
        self,
        *,
        repository: PublicationSourceRepository,
        hasher: PublicationSourceHasher,
    ) -> None:
        self._repository = repository
        self._hasher = hasher

    def execute(
        self,
        *,
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationSourceIdentity:
        source = self._repository.find_source(
            volume_id=volume_id,
            access_scope=access_scope,
        )
        if source is None:
            raise PublicationNotFoundError
        return PublicationSourceIdentity(
            original_file_hash=canonical_original_file_hash(
                self._hasher.sha256(source)
            ),
            source_format=source.source_format,
        )


__all__ = ["PublicationSourceIdentity", "ResolvePublicationSourceIdentity"]
