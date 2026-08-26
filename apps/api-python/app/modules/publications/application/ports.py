"""Ports owned by the publication application layer."""

from __future__ import annotations

from typing import Protocol

from app.contracts.publication_sources import (
    PublicationAccessScope,
    PublicationSource,
    PublicationSourceRepository,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationResource,
)


class PublicationAdapter(Protocol):
    def open(self, source: PublicationSource) -> NormalizedPublication: ...

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource: ...


__all__ = [
    "PublicationAccessScope",
    "PublicationAdapter",
    "PublicationSource",
    "PublicationSourceRepository",
]
