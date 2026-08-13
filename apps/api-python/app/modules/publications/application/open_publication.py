"""Open and resolve resources from an authorized normalized publication."""

from __future__ import annotations

from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationAdapter,
    PublicationSource,
    PublicationSourceRepository,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationNotFoundError,
    PublicationResource,
)


class OpenPublication:
    def __init__(
        self,
        repository: PublicationSourceRepository,
        adapter: PublicationAdapter,
    ) -> None:
        self._repository = repository
        self._adapter = adapter

    def manifest(
        self,
        *,
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> NormalizedPublication:
        return self._adapter.open(
            self._require_source(volume_id=volume_id, access_scope=access_scope)
        )

    def resource(
        self,
        *,
        volume_id: str,
        href: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationResource:
        source = self._require_source(
            volume_id=volume_id,
            access_scope=access_scope,
        )
        return self._adapter.read_resource(source, href)

    def _require_source(
        self,
        *,
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationSource:
        source = self._repository.find_source(
            volume_id=volume_id,
            access_scope=access_scope,
        )
        if source is None:
            raise PublicationNotFoundError
        return source
