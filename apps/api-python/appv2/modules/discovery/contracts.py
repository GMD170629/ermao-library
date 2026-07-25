from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from appv2.modules.ingestion.contracts import ImportResult
from appv2.platform.database.contracts import UnitOfWork


@dataclass(frozen=True, slots=True)
class SourceResult:
    source_id: uuid.UUID
    external_id: str
    title: str
    author: str | None
    download_url: str | None
    info_url: str | None
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    source_id: uuid.UUID
    result_id: uuid.UUID
    requested_by: uuid.UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SourceView:
    id: uuid.UUID
    name: str
    kind: str
    base_url: str
    enabled: bool
    config: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SearchResultView:
    id: uuid.UUID
    source_id: uuid.UUID
    external_id: str
    title: str
    author: str | None
    download_url: str | None
    info_url: str | None
    payload: dict[str, object]
    state: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DownloadJob:
    id: uuid.UUID
    result_id: uuid.UUID
    requested_by: uuid.UUID
    status: str
    attempt: int
    next_attempt_at: datetime
    destination_path: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class DiscoveryRepository(Protocol):
    def list_sources(self) -> list[SourceView]: ...

    def get_source(self, source_id: uuid.UUID) -> SourceView | None: ...

    def add_source(
        self,
        *,
        name: str,
        kind: str,
        base_url: str,
        enabled: bool,
        config: dict[str, object],
    ) -> SourceView: ...

    def update_source(
        self,
        source_id: uuid.UUID,
        *,
        name: str | None,
        base_url: str | None,
        enabled: bool | None,
        config: dict[str, object] | None,
    ) -> SourceView | None: ...

    def delete_source(self, source_id: uuid.UUID) -> bool: ...

    def save_results(
        self, source_id: uuid.UUID, results: list[SourceResult]
    ) -> list[SearchResultView]: ...

    def list_results(
        self, *, offset: int, limit: int, state: str | None
    ) -> tuple[list[SearchResultView], int]: ...

    def get_result(self, result_id: uuid.UUID) -> SearchResultView | None: ...

    def enqueue_download(self, request: DownloadRequest, *, now: datetime) -> DownloadJob: ...

    def list_downloads(
        self, *, offset: int, limit: int, status: str | None
    ) -> tuple[list[DownloadJob], int]: ...

    def claim_download(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> tuple[DownloadJob, SearchResultView] | None: ...

    def complete_download(self, job_id: uuid.UUID, destination_path: str) -> None: ...

    def fail_download(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> None: ...


class DiscoveryUnitOfWork(UnitOfWork, Protocol):
    discovery: DiscoveryRepository


class SourceSearchPort(Protocol):
    def search(self, source: SourceView, query: str) -> list[SourceResult]: ...


class DownloadPort(Protocol):
    def download(self, result: SearchResultView) -> str: ...


class ImportEnqueuePort(Protocol):
    def enqueue_downloaded(
        self, *, path: str, requested_by: uuid.UUID, idempotency_key: str
    ) -> ImportResult: ...
