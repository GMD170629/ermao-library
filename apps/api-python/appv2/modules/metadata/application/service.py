from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from appv2.modules.catalog.contracts import CatalogMetadataPort
from appv2.modules.metadata.contracts import (
    MetadataCandidate,
    MetadataJob,
    MetadataPatch,
    MetadataUnitOfWork,
    ProviderView,
)


class MetadataNotFound(Exception):
    pass


class MetadataService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], MetadataUnitOfWork],
        catalog: CatalogMetadataPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog

    def list_providers(self) -> list[ProviderView]:
        with self._uow_factory() as uow:
            return uow.metadata.list_providers()

    def add_provider(
        self,
        *,
        slug: str,
        name: str,
        enabled: bool,
        priority: int,
        config: dict[str, object],
    ) -> ProviderView:
        with self._uow_factory() as uow:
            provider = uow.metadata.add_provider(
                slug=slug,
                name=name,
                enabled=enabled,
                priority=priority,
                config=config,
            )
            uow.commit()
            return provider

    def update_provider(
        self,
        provider_id: uuid.UUID,
        *,
        name: str | None,
        enabled: bool | None,
        priority: int | None,
        config: dict[str, object] | None,
    ) -> ProviderView:
        with self._uow_factory() as uow:
            provider = uow.metadata.update_provider(
                provider_id,
                name=name,
                enabled=enabled,
                priority=priority,
                config=config,
            )
            if provider is None:
                raise MetadataNotFound
            uow.commit()
            return provider

    def enqueue(
        self,
        *,
        work_id: uuid.UUID,
        requested_by: uuid.UUID,
        query: str,
        idempotency_key: str | None,
    ) -> MetadataJob:
        key = idempotency_key or hashlib.sha256(f"{work_id}\0{query}".encode()).hexdigest()
        with self._uow_factory() as uow:
            job = uow.metadata.enqueue_job(
                work_id=work_id,
                requested_by=requested_by,
                query=query,
                idempotency_key=key,
                now=datetime.now(UTC),
            )
            uow.commit()
            return job

    def list_jobs(
        self, *, page: int, page_size: int, status: str | None
    ) -> tuple[list[MetadataJob], int]:
        with self._uow_factory() as uow:
            return uow.metadata.list_jobs(
                offset=(page - 1) * page_size, limit=page_size, status=status
            )

    def list_candidates(self, job_id: uuid.UUID) -> list[MetadataCandidate]:
        with self._uow_factory() as uow:
            if uow.metadata.get_job(job_id) is None:
                raise MetadataNotFound
            return uow.metadata.list_candidates(job_id)

    def apply_candidate(
        self,
        *,
        work_id: uuid.UUID,
        candidate: MetadataCandidate,
        patch: MetadataPatch,
    ) -> None:
        values: dict[str, object] = {
            "title": patch.title or candidate.title,
            "author": patch.author or candidate.author or "",
            "metadataProviderId": str(candidate.provider_id),
            "metadataExternalId": candidate.external_id,
            "metadataRaw": candidate.raw_payload,
        }
        if patch.series is not None:
            values["series"] = patch.series
        if patch.summary is not None:
            values["summary"] = patch.summary
        if patch.cover_url or candidate.cover_url:
            values["coverUrl"] = patch.cover_url or candidate.cover_url or ""
        if patch.extra:
            values.update(patch.extra)
        if self._catalog.apply_metadata(work_id, values) is None:
            raise MetadataNotFound
