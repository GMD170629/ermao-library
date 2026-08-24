"""Application operations for persisted library scan settings."""

from __future__ import annotations

from typing import Protocol

from app.modules.imports.application.readable_resource.ports import UnitOfWorkPort
from app.modules.imports.domain.library_scan_schedule import LibraryScanSettings


class LibraryScanSettingsRepositoryPort(Protocol):
    def load(self) -> LibraryScanSettings: ...

    def save(self, settings: LibraryScanSettings) -> None: ...


class GetLibraryScanSettings:
    def __init__(self, repository: LibraryScanSettingsRepositoryPort) -> None:
        self._repository = repository

    def execute(self) -> LibraryScanSettings:
        return self._repository.load()


class UpdateLibraryScanSettings:
    def __init__(
        self,
        repository: LibraryScanSettingsRepositoryPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._repository = repository
        self._uow = uow

    def execute(self, settings: LibraryScanSettings) -> LibraryScanSettings:
        with self._uow.transaction():
            self._repository.save(settings)
        return settings


__all__ = [
    "GetLibraryScanSettings",
    "LibraryScanSettingsRepositoryPort",
    "UpdateLibraryScanSettings",
]
