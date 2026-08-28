"""Open and resolve resources from an authorized normalized publication."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationAdapter,
    PublicationSource,
    PublicationSourceRepository,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationChangedError,
    PublicationLink,
    PublicationNotFoundError,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationResourceTooLargeError,
)


@dataclass(frozen=True, slots=True)
class PublicationResourceDelivery:
    resource: PublicationResource
    revision_token: str


@dataclass(frozen=True, slots=True)
class PublicationResourceDescription:
    link: PublicationLink
    revision_token: str


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
        resource_id: str,
        access_scope: PublicationAccessScope,
        expected_revision: str | None = None,
    ) -> NormalizedPublication:
        publication = self._adapter.open(
            self._require_source(resource_id=resource_id, access_scope=access_scope)
        )
        self._check_revision(publication, expected_revision)
        return publication

    def resource(
        self,
        *,
        resource_id: str,
        href: str,
        access_scope: PublicationAccessScope,
        expected_revision: str | None = None,
    ) -> PublicationResourceDelivery:
        source = self._require_source(
            resource_id=resource_id,
            access_scope=access_scope,
        )
        publication = self._adapter.open(source)
        self._check_revision(publication, expected_revision)
        resource = self._adapter.read_resource(source, href)
        limit = (
            8 * 1024 * 1024
            if resource.media_type in {"text/html", "application/xhtml+xml"}
            else 32 * 1024 * 1024
        )
        if len(resource.content) > limit:
            raise PublicationResourceTooLargeError
        self._check_revision(self._adapter.open(source), publication.revision.token)
        return PublicationResourceDelivery(resource, publication.revision.token)

    def describe_resource(
        self,
        *,
        resource_id: str,
        href: str,
        access_scope: PublicationAccessScope,
        expected_revision: str | None = None,
    ) -> PublicationResourceDescription:
        publication = self.manifest(
            resource_id=resource_id,
            access_scope=access_scope,
            expected_revision=expected_revision,
        )
        for link in (*publication.reading_order, *publication.resources):
            if link.href == href:
                return PublicationResourceDescription(link, publication.revision.token)
        raise PublicationResourceNotFoundError

    @staticmethod
    def _check_revision(
        publication: NormalizedPublication, expected: str | None
    ) -> None:
        if expected is not None and publication.revision.token != expected:
            raise PublicationChangedError

    def _require_source(
        self,
        *,
        resource_id: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationSource:
        source = self._repository.find_source(
            resource_id=resource_id,
            access_scope=access_scope,
        )
        if source is None:
            raise PublicationNotFoundError
        return source
