from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import BinaryIO

from appv2.modules.catalog.contracts import CatalogReadPort
from appv2.modules.ingestion.contracts import (
    SUPPORTED_IMPORT_EXTENSIONS,
    DirectoryNode,
    FileDiscoveryPort,
    ImportRequest,
    ImportResult,
    IngestionJob,
    IngestionPolicy,
    IngestionUnitOfWork,
    JobLog,
    MonitorFolder,
    ScanRun,
    UploadStoragePort,
)


class IngestionNotFound(Exception):
    pass


class IngestionSourceMissing(IngestionNotFound):
    pass


class IngestionService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], IngestionUnitOfWork],
        discovery: FileDiscoveryPort,
        uploads: UploadStoragePort,
        catalog: CatalogReadPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._discovery = discovery
        self._uploads = uploads
        self._catalog = catalog

    def list_jobs(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        kind: str | None = None,
        origin: str | None = None,
        keyword: str | None = None,
        monitor_folder_ids: tuple[uuid.UUID, ...] | None = None,
        requested_by: uuid.UUID | None = None,
    ) -> tuple[list[IngestionJob], int]:
        with self._uow_factory() as uow:
            return uow.ingestion.list_jobs(
                offset=(page - 1) * page_size,
                limit=page_size,
                status=status,
                kind=kind,
                origin=origin,
                keyword=keyword,
                monitor_folder_ids=monitor_folder_ids,
                requested_by=requested_by,
            )

    def get_job(self, job_id: uuid.UUID) -> tuple[IngestionJob, list[JobLog]]:
        with self._uow_factory() as uow:
            job = uow.ingestion.get_job(job_id)
            if job is None:
                raise IngestionNotFound
            return job, uow.ingestion.list_logs(job_id)

    def enqueue(
        self,
        *,
        source_path: str,
        requested_by: uuid.UUID | None,
        idempotency_key: str | None,
        origin: str = "manual",
        monitor_folder_id: uuid.UUID | None = None,
        triggered_by: str = "user",
        kind: str = "import",
        options: dict[str, object] | None = None,
    ) -> ImportResult:
        key = idempotency_key or hashlib.sha256(f"{kind}\0{source_path}".encode()).hexdigest()
        request = ImportRequest(
            source_path=source_path,
            requested_by=requested_by,
            idempotency_key=key,
            origin=origin,
            monitor_folder_id=monitor_folder_id,
            triggered_by=triggered_by,
            options=options or {},
        )
        with self._uow_factory() as uow:
            if kind == "import" and "autoConvertToEpub" not in request.options:
                policy = uow.ingestion.get_policy()
                request = ImportRequest(
                    source_path=request.source_path,
                    requested_by=request.requested_by,
                    idempotency_key=request.idempotency_key,
                    origin=request.origin,
                    monitor_folder_id=request.monitor_folder_id,
                    triggered_by=request.triggered_by,
                    options={
                        **request.options,
                        "autoConvertToEpub": policy.auto_convert_to_epub,
                    },
                )
            result = uow.ingestion.enqueue(request, kind=kind)
            uow.commit()
            return result

    def policy(self) -> IngestionPolicy:
        with self._uow_factory() as uow:
            return uow.ingestion.get_policy()

    def update_policy(
        self,
        *,
        allowed_extensions: tuple[str, ...],
        ignore_patterns: tuple[str, ...],
        stability_check_enabled: bool,
        stability_check_seconds: int,
        auto_convert_to_epub: bool,
    ) -> IngestionPolicy:
        normalized_extensions = tuple(
            sorted({value.strip().casefold() for value in allowed_extensions})
        )
        if (
            not normalized_extensions
            or any(value not in SUPPORTED_IMPORT_EXTENSIONS for value in normalized_extensions)
            or stability_check_seconds < 0
            or stability_check_seconds > 300
        ):
            raise ValueError("invalid ingestion policy")
        normalized_patterns = tuple(value.strip() for value in ignore_patterns if value.strip())
        with self._uow_factory() as uow:
            policy = uow.ingestion.update_policy(
                allowed_extensions=normalized_extensions,
                ignore_patterns=normalized_patterns,
                stability_check_enabled=stability_check_enabled,
                stability_check_seconds=stability_check_seconds,
                auto_convert_to_epub=auto_convert_to_epub,
            )
            uow.commit()
            return policy

    def enqueue_monitored(
        self,
        *,
        source_path: str,
        requested_by: uuid.UUID,
        idempotency_key: str | None,
        monitor_folder_ids: tuple[uuid.UUID, ...] | None,
    ) -> ImportResult:
        folders = [
            folder
            for folder in self.list_folders()
            if folder.enabled and (monitor_folder_ids is None or folder.id in monitor_folder_ids)
        ]
        validated = self._discovery.validate_source(
            source_path,
            allowed_roots=tuple(folder.path for folder in folders),
        )
        matching_folder = max(
            (
                folder
                for folder in folders
                if validated == folder.path or validated.startswith(f"{folder.path.rstrip('/')}/")
            ),
            key=lambda folder: len(folder.path),
        )
        return self.enqueue(
            source_path=validated,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            origin="manual",
            monitor_folder_id=matching_folder.id,
            triggered_by="user",
        )

    def enqueue_conversion(
        self,
        *,
        edition_id: uuid.UUID,
        requested_by: uuid.UUID,
    ) -> ImportResult:
        edition = self._catalog.get_edition(edition_id)
        if edition is None:
            raise IngestionNotFound
        if edition.format != "txt":
            raise ValueError("only text editions can be converted to EPUB")
        files = self._catalog.files_for_edition(edition_id)
        if not files:
            raise IngestionNotFound
        source = files[0]
        return self.enqueue(
            source_path=source.storage_path,
            requested_by=requested_by,
            idempotency_key=hashlib.sha256(
                f"conversion\0{edition_id}\0{source.checksum}\0epub".encode()
            ).hexdigest(),
            kind="conversion",
            options={
                "sourceEditionId": str(edition_id),
                "sourceLanguage": edition.language,
                "targetFormat": "epub",
            },
        )

    def upload(
        self,
        *,
        name: str,
        stream: BinaryIO,
        requested_by: uuid.UUID,
        idempotency_key: str | None,
    ) -> ImportResult:
        stored_path = self._uploads.store(name, stream)
        return self.enqueue(
            source_path=stored_path,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            origin="upload",
        )

    def retry(self, job_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            job = uow.ingestion.get_job(job_id)
            if job is None:
                raise IngestionNotFound
            if not self._discovery.source_exists(job.source_path):
                raise IngestionSourceMissing
            if not uow.ingestion.retry(job_id, datetime.now(UTC)):
                raise IngestionNotFound
            uow.commit()

    def cancel(self, job_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.ingestion.cancel(job_id):
                raise IngestionNotFound
            uow.commit()

    def request_scan(
        self,
        *,
        trigger: str,
        monitor_folder_id: uuid.UUID | None,
        requested_by: uuid.UUID | None,
    ) -> ScanRun:
        with self._uow_factory() as uow:
            if (
                monitor_folder_id is not None
                and uow.ingestion.get_folder(monitor_folder_id) is None
            ):
                raise IngestionNotFound
            scan = uow.ingestion.create_scan_run(
                trigger=trigger,
                monitor_folder_id=monitor_folder_id,
                requested_by=requested_by,
            )
            uow.commit()
            return scan

    def get_scan(self, scan_run_id: uuid.UUID) -> ScanRun:
        with self._uow_factory() as uow:
            scan = uow.ingestion.get_scan_run(scan_run_id)
            if scan is None:
                raise IngestionNotFound
            return scan

    def delete_job(self, job_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.ingestion.delete_job(job_id):
                raise IngestionNotFound
            uow.commit()

    def clear_finished(self) -> int:
        with self._uow_factory() as uow:
            count = uow.ingestion.clear_finished()
            uow.commit()
            return count

    def list_folders(self) -> list[MonitorFolder]:
        with self._uow_factory() as uow:
            return uow.ingestion.list_folders()

    def directory_tree(self, path: str | None = None) -> tuple[DirectoryNode, str]:
        return self._discovery.tree(path)

    def add_folder(
        self,
        *,
        path: str,
        recursive: bool,
        options: dict[str, object],
        requested_by: uuid.UUID,
    ) -> tuple[MonitorFolder, ScanRun]:
        validated = self._discovery.validate_folder(path)
        with self._uow_factory() as uow:
            folder = uow.ingestion.add_folder(
                path=validated,
                recursive=recursive,
                options=options,
            )
            scan = uow.ingestion.create_scan_run(
                trigger="initial",
                monitor_folder_id=folder.id,
                requested_by=requested_by,
            )
            uow.commit()
            return folder, scan

    def update_folder(
        self,
        folder_id: uuid.UUID,
        *,
        enabled: bool | None,
        recursive: bool | None,
        options: dict[str, object] | None,
    ) -> MonitorFolder:
        with self._uow_factory() as uow:
            folder = uow.ingestion.update_folder(
                folder_id,
                enabled=enabled,
                recursive=recursive,
                options=options,
                scanned_at=None,
            )
            if folder is None:
                raise IngestionNotFound
            uow.commit()
            return folder

    def delete_folder(self, folder_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.ingestion.delete_folder(folder_id):
                raise IngestionNotFound
            uow.commit()

    def scan_folder(self, folder_id: uuid.UUID, requested_by: uuid.UUID) -> list[ImportResult]:
        with self._uow_factory() as uow:
            folder = uow.ingestion.get_folder(folder_id)
        if folder is None:
            raise IngestionNotFound
        paths = self._discovery.discover(folder.path, recursive=folder.recursive)
        results = [
            self.enqueue(
                source_path=path,
                requested_by=requested_by,
                idempotency_key=hashlib.sha256(f"scan\0{path}".encode()).hexdigest(),
                origin="watch",
                monitor_folder_id=folder.id,
            )
            for path in paths
        ]
        with self._uow_factory() as uow:
            uow.ingestion.update_folder(
                folder_id,
                enabled=None,
                recursive=None,
                options=None,
                scanned_at=datetime.now(UTC),
            )
            uow.commit()
        return results

    def scan_all_folders(self, requested_by: uuid.UUID) -> list[ImportResult]:
        results: list[ImportResult] = []
        for folder in self.list_folders():
            if folder.enabled:
                results.extend(self.scan_folder(folder.id, requested_by))
        return results

    def scan_directory(self, path: str, requested_by: uuid.UUID) -> list[ImportResult]:
        discovered = self._discovery.discover(path, recursive=True)
        return [
            self.enqueue(
                source_path=source_path,
                requested_by=requested_by,
                idempotency_key=hashlib.sha256(f"scan\0{source_path}".encode()).hexdigest(),
                origin="manual",
            )
            for source_path in discovered
        ]
