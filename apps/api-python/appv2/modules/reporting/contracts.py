from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DashboardProjection:
    work_count: int
    edition_count: int
    active_readers: int
    queued_jobs: int
    recent_items: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ManagementProjection:
    users: int
    works: int
    files: int
    queued_imports: int
    queued_downloads: int
    queued_deliveries: int
    failed_jobs: int


class ReportingReadPort(Protocol):
    def dashboard(self) -> DashboardProjection: ...

    def management(self) -> ManagementProjection: ...
