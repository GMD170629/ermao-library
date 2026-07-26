from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from appv2.modules.catalog.contracts import (
    CatalogMetadataPort,
    CatalogOrganizationReadPort,
)
from appv2.modules.metadata.contracts import (
    MetadataCandidate,
    MetadataJob,
    MetadataPatch,
    MetadataUnitOfWork,
    OrganizePolicy,
    ProviderView,
)


class MetadataNotFound(Exception):
    pass


class MetadataConflict(Exception):
    pass


class MetadataService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], MetadataUnitOfWork],
        catalog: CatalogMetadataPort,
        catalog_read: CatalogOrganizationReadPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog
        self._catalog_read = catalog_read

    def list_providers(self) -> list[ProviderView]:
        with self._uow_factory() as uow:
            return uow.metadata.list_providers()

    def organize_policy(self) -> OrganizePolicy:
        with self._uow_factory() as uow:
            return uow.metadata.get_organize_policy()

    def update_organize_policy(
        self,
        *,
        schedule_mode: str,
        interval_minutes: int | None,
        auto_run_on_new: bool,
        provider_scope: tuple[str, ...],
        overwrite_fields: tuple[str, ...],
        rules: dict[str, object],
    ) -> OrganizePolicy:
        if schedule_mode not in {"MANUAL", "INTERVAL"}:
            raise ValueError("invalid organize schedule mode")
        if schedule_mode == "INTERVAL" and (interval_minutes is None or interval_minutes < 5):
            raise ValueError("interval schedule requires at least five minutes")
        with self._uow_factory() as uow:
            policy = uow.metadata.update_organize_policy(
                schedule_mode=schedule_mode,
                interval_minutes=(interval_minutes if schedule_mode == "INTERVAL" else None),
                auto_run_on_new=auto_run_on_new,
                provider_scope=provider_scope,
                overwrite_fields=overwrite_fields,
                rules=rules,
            )
            uow.commit()
            return policy

    def handle_import_completed(
        self,
        *,
        work_id: uuid.UUID,
        import_job_id: uuid.UUID,
    ) -> bool:
        work = self._catalog_read.get_work(work_id)
        if work is None:
            raise MetadataNotFound
        with self._uow_factory() as uow:
            policy = uow.metadata.get_organize_policy()
            if not policy.auto_run_on_new:
                return False
            created = uow.metadata.enqueue_organize_job(
                work_id=work_id,
                proposal={
                    "trigger": "import.completed",
                    "importJobId": str(import_job_id),
                    "providerScope": list(policy.provider_scope),
                    "overwriteFields": list(policy.overwrite_fields),
                    "rules": policy.rules,
                    "title": work.title,
                    "author": work.author,
                },
            )
            uow.commit()
            return created

    def schedule_interval(self) -> tuple[int, int | None]:
        with self._uow_factory() as uow:
            policy = uow.metadata.get_organize_policy()
        if policy.schedule_mode != "INTERVAL" or policy.interval_minutes is None:
            return 0, None
        offset = 0
        batch_size = 200
        created = 0
        while works := self._catalog_read.list_active_works(
            offset=offset,
            limit=batch_size,
        ):
            with self._uow_factory() as uow:
                for work in works:
                    created += int(
                        uow.metadata.enqueue_organize_job(
                            work_id=work.id,
                            proposal={
                                "trigger": "interval",
                                "providerScope": list(policy.provider_scope),
                                "overwriteFields": list(policy.overwrite_fields),
                                "rules": policy.rules,
                                "title": work.title,
                                "author": work.author,
                            },
                        )
                    )
                uow.commit()
            offset += len(works)
            if len(works) < batch_size:
                break
        return created, policy.interval_minutes

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
        provider_id: uuid.UUID | None,
        requested_by: uuid.UUID,
        query: str,
        idempotency_key: str | None,
    ) -> MetadataJob:
        if self._catalog_read.get_work(work_id) is None:
            raise MetadataNotFound
        if provider_id is not None:
            with self._uow_factory() as uow:
                provider = uow.metadata.get_provider(provider_id)
                if provider is None or not provider.enabled:
                    raise MetadataNotFound
        key = (
            idempotency_key
            or hashlib.sha256(f"{work_id}\0{provider_id}\0{query}".encode()).hexdigest()
        )
        with self._uow_factory() as uow:
            job = uow.metadata.enqueue_job(
                work_id=work_id,
                provider_id=provider_id,
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

    def get_job(self, job_id: uuid.UUID) -> MetadataJob:
        with self._uow_factory() as uow:
            job = uow.metadata.get_job(job_id)
            if job is None:
                raise MetadataNotFound
            return job

    def retry_job(self, job_id: uuid.UUID) -> MetadataJob:
        with self._uow_factory() as uow:
            job = uow.metadata.retry_job(job_id, now=datetime.now(UTC))
            if job is None:
                raise MetadataNotFound
            if job.status == "running":
                raise MetadataConflict
            uow.commit()
            return job

    def delete_job(self, job_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            result = uow.metadata.delete_job(job_id)
            if result == "missing":
                raise MetadataNotFound
            if result == "running":
                raise MetadataConflict
            uow.commit()

    def list_candidates(self, job_id: uuid.UUID) -> list[MetadataCandidate]:
        with self._uow_factory() as uow:
            if uow.metadata.get_job(job_id) is None:
                raise MetadataNotFound
            return uow.metadata.list_candidates(job_id)

    def apply_candidate(
        self,
        *,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        patch: MetadataPatch,
    ) -> None:
        with self._uow_factory() as uow:
            job = uow.metadata.get_job(job_id)
            candidate = uow.metadata.get_candidate(job_id, candidate_id)
            if job is None or candidate is None:
                raise MetadataNotFound
        values: dict[str, object] = {
            "metadataProviderId": str(candidate.provider_id),
            "metadataExternalId": candidate.external_id,
            "metadataRaw": candidate.raw_payload,
        }
        if patch.title is not None:
            values["title"] = patch.title
        if patch.author is not None:
            values["author"] = patch.author
        if patch.series is not None:
            values["series"] = patch.series
        if patch.summary is not None:
            values["summary"] = patch.summary
        if patch.cover_url is not None:
            values["coverUrl"] = patch.cover_url
        if patch.extra:
            values.update(patch.extra)
        if self._catalog.apply_metadata(job.work_id, values) is None:
            raise MetadataNotFound
