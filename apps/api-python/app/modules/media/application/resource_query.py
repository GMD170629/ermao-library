"""Read-only media resource application contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MediaFileResource:
    id: str
    path: str
    mime_type: str


class MediaResourceRepository(Protocol):
    def get_file(self, file_id: str) -> MediaFileResource | None: ...

    def first_volume_file(self, volume_id: str) -> MediaFileResource | None: ...

    def work_cover_path(self, work_id: str) -> str | None: ...

    def volume_cover_path(self, volume_id: str) -> str | None: ...


class MediaResourceQuery:
    def __init__(self, repository: MediaResourceRepository) -> None:
        self._repository = repository

    def get_file(self, file_id: str) -> MediaFileResource | None:
        return self._repository.get_file(file_id)

    def first_volume_file(self, volume_id: str) -> MediaFileResource | None:
        return self._repository.first_volume_file(volume_id)

    def cover_path(
        self, *, work_id: str | None = None, volume_id: str | None = None
    ) -> str | None:
        if work_id is not None:
            return self._repository.work_cover_path(work_id)
        if volume_id is not None:
            return self._repository.volume_cover_path(volume_id)
        return None
