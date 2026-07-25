from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import BinaryIO

from appv2.modules.catalog.contracts import CatalogReadPort
from appv2.modules.ingestion.contracts import (
    DirectoryNode,
    FileDiscoveryPort,
    ImportRequest,
    ImportResult,
    IngestionJob,
    IngestionUnitOfWork,
    MonitorFolder,
    UploadStoragePort,
)


class IngestionNotFound(Exception):
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
    ) -> tuple[list[IngestionJob], int]:
        with self._uow_factory() as uow:
            return uow.ingestion.list_jobs(
                offset=(page - 1) * page_size,
                limit=page_size,
                status=status,
                kind=kind,
            )

    def enqueue(
        self,
        *,
        source_path: str,
        requested_by: uuid.UUID,
        idempotency_key: str | None,
        move_source: bool = False,
        kind: str = "import",
        options: dict[str, object] | None = None,
    ) -> ImportResult:
        key = idempotency_key or hashlib.sha256(f"{kind}\0{source_path}".encode()).hexdigest()
        request = ImportRequest(
            source_path=source_path,
            requested_by=requested_by,
            idempotency_key=key,
            move_source=move_source,
            options=options or {},
        )
        with self._uow_factory() as uow:
            result = uow.ingestion.enqueue(request, kind=kind)
            uow.commit()
            return result

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
        )

    def retry(self, job_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.ingestion.retry(job_id, datetime.now(UTC)):
                raise IngestionNotFound
            uow.commit()

    def cancel(self, job_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.ingestion.cancel(job_id):
                raise IngestionNotFound
            uow.commit()

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
        move_source: bool,
        options: dict[str, object],
    ) -> MonitorFolder:
        validated = self._discovery.validate_folder(path)
        with self._uow_factory() as uow:
            folder = uow.ingestion.add_folder(
                path=validated,
                recursive=recursive,
                move_source=move_source,
                options=options,
            )
            uow.commit()
            return folder

    def update_folder(
        self,
        folder_id: uuid.UUID,
        *,
        enabled: bool | None,
        recursive: bool | None,
        move_source: bool | None,
        options: dict[str, object] | None,
    ) -> MonitorFolder:
        with self._uow_factory() as uow:
            folder = uow.ingestion.update_folder(
                folder_id,
                enabled=enabled,
                recursive=recursive,
                move_source=move_source,
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
                move_source=folder.move_source,
            )
            for path in paths
        ]
        with self._uow_factory() as uow:
            uow.ingestion.update_folder(
                folder_id,
                enabled=None,
                recursive=None,
                move_source=None,
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
            )
            for source_path in discovered
        ]
