from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from appv2.modules.discovery.contracts import (
    DiscoveryUnitOfWork,
    DownloadJob,
    DownloadRequest,
    SearchResultView,
    SourceSearchPort,
    SourceView,
)
from appv2.modules.discovery.domain import ExternalSource


class DiscoveryNotFound(Exception):
    pass


class DiscoveryService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], DiscoveryUnitOfWork],
        search_port: SourceSearchPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._search = search_port

    def list_sources(self) -> list[SourceView]:
        with self._uow_factory() as uow:
            return uow.discovery.list_sources()

    def add_source(
        self,
        *,
        name: str,
        kind: str,
        base_url: str,
        enabled: bool,
        config: dict[str, object],
    ) -> SourceView:
        ExternalSource(id=uuid.uuid4(), name=name, base_url=base_url, enabled=enabled).validate()
        with self._uow_factory() as uow:
            source = uow.discovery.add_source(
                name=name,
                kind=kind,
                base_url=base_url.rstrip("/"),
                enabled=enabled,
                config=config,
            )
            uow.commit()
            return source

    def update_source(
        self,
        source_id: uuid.UUID,
        *,
        name: str | None,
        base_url: str | None,
        enabled: bool | None,
        config: dict[str, object] | None,
    ) -> SourceView:
        if base_url is not None:
            ExternalSource(
                id=source_id,
                name=name or "source",
                base_url=base_url,
                enabled=enabled if enabled is not None else True,
            ).validate()
        with self._uow_factory() as uow:
            source = uow.discovery.update_source(
                source_id,
                name=name,
                base_url=base_url.rstrip("/") if base_url else None,
                enabled=enabled,
                config=config,
            )
            if source is None:
                raise DiscoveryNotFound
            uow.commit()
            return source

    def delete_source(self, source_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.discovery.delete_source(source_id):
                raise DiscoveryNotFound
            uow.commit()

    def search(self, source_id: uuid.UUID, query: str) -> list[SearchResultView]:
        with self._uow_factory() as uow:
            source = uow.discovery.get_source(source_id)
        if source is None or not source.enabled:
            raise DiscoveryNotFound
        found = self._search.search(source, query)
        with self._uow_factory() as uow:
            results = uow.discovery.save_results(source_id, found)
            uow.commit()
            return results

    def list_results(
        self, *, page: int, page_size: int, state: str | None
    ) -> tuple[list[SearchResultView], int]:
        with self._uow_factory() as uow:
            return uow.discovery.list_results(
                offset=(page - 1) * page_size, limit=page_size, state=state
            )

    def enqueue_download(
        self,
        *,
        result_id: uuid.UUID,
        requested_by: uuid.UUID,
        idempotency_key: str | None,
    ) -> DownloadJob:
        with self._uow_factory() as uow:
            result = uow.discovery.get_result(result_id)
            if result is None:
                raise DiscoveryNotFound
            key = idempotency_key or hashlib.sha256(f"download\0{result_id}".encode()).hexdigest()
            job = uow.discovery.enqueue_download(
                DownloadRequest(
                    source_id=result.source_id,
                    result_id=result.id,
                    requested_by=requested_by,
                    idempotency_key=key,
                ),
                now=datetime.now(UTC),
            )
            uow.commit()
            return job

    def list_downloads(
        self, *, page: int, page_size: int, status: str | None
    ) -> tuple[list[DownloadJob], int]:
        with self._uow_factory() as uow:
            return uow.discovery.list_downloads(
                offset=(page - 1) * page_size, limit=page_size, status=status
            )
