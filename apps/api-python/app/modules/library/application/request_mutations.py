"""Named transaction boundaries for prepared Library HTTP mutations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.authorization import AuthorizationContext


class LibraryRequestUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DetailPreferenceMutation:
    user_id: str
    work_id: str
    selected_tab: str
    now: datetime


@dataclass(frozen=True, slots=True)
class WorkRecordMutation:
    work_id: str
    values: Mapping[str, object]
    facet_write: object
    writeback_intents: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class BulkWorkMutation:
    updates: tuple[tuple[str, Mapping[str, object]], ...]
    facet_write: object | None = None
    writeback_intents: tuple[object, ...] = ()
    events: tuple[object, ...] = ()
    reported_count: int | None = None


@dataclass(frozen=True, slots=True)
class BulkReadingStatusMutation:
    context: AuthorizationContext
    work_ids: tuple[str, ...]
    status: str
    now: datetime
    events: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class BulkShelfMembershipMutation:
    shelf_id: str
    work_ids: tuple[str, ...]
    membership: str
    now: datetime
    events: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverRecordMutation:
    work_id: str
    cover_path: str
    cover_status: str


@dataclass(frozen=True, slots=True)
class CoverMutation:
    records: tuple[CoverRecordMutation, ...]
    now: datetime
    writeback_intents: tuple[object, ...] = ()
    events: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class MetadataApplyMutation:
    work_id: str
    work_values: Mapping[str, object]
    volume_rows: tuple[Mapping[str, object], ...]
    facet_write: object
    writeback_intents: tuple[object, ...]
    finished_job_ids: tuple[str, ...]
    now: datetime


@dataclass(frozen=True, slots=True)
class MetadataApplyResult:
    work: Mapping[str, object] | None
    finished_job_ids: tuple[str, ...]
    writeback_operation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverPublicationFailure:
    work_id: str
    expected_cover_path: str
    expected_updated_at: datetime
    fallback_cover_path: str | None
    now: datetime


class LibraryRequestMutationGateway(Protocol):
    def save_detail_preference(self, command: DetailPreferenceMutation) -> None: ...

    def update_work(
        self, command: WorkRecordMutation
    ) -> Mapping[str, object] | None: ...

    def update_works(self, command: BulkWorkMutation) -> int: ...

    def update_reading_status(self, command: BulkReadingStatusMutation) -> int: ...

    def update_shelf_membership(self, command: BulkShelfMembershipMutation) -> int: ...

    def update_covers(self, command: CoverMutation) -> int: ...

    def apply_metadata(self, command: MetadataApplyMutation) -> MetadataApplyResult: ...

    def compensate_cover_publication(
        self, command: CoverPublicationFailure
    ) -> bool: ...


class SaveDetailPreference:
    def __init__(
        self,
        gateway: LibraryRequestMutationGateway,
        unit_of_work: LibraryRequestUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: DetailPreferenceMutation) -> None:
        try:
            self._gateway.save_detail_preference(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise


class UpdateWorkRecord:
    def __init__(
        self,
        gateway: LibraryRequestMutationGateway,
        unit_of_work: LibraryRequestUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: WorkRecordMutation) -> Mapping[str, object] | None:
        try:
            result = self._gateway.update_work(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return result


class UpdateBulkWorks:
    def __init__(
        self,
        gateway: LibraryRequestMutationGateway,
        unit_of_work: LibraryRequestUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: BulkWorkMutation) -> int:
        try:
            updated = self._gateway.update_works(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return updated


class UpdateBulkReadingStatus:
    def __init__(
        self,
        gateway: LibraryRequestMutationGateway,
        unit_of_work: LibraryRequestUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: BulkReadingStatusMutation) -> int:
        try:
            updated = self._gateway.update_reading_status(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return updated


class UpdateBulkShelfMembership:
    def __init__(
        self,
        gateway: LibraryRequestMutationGateway,
        unit_of_work: LibraryRequestUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: BulkShelfMembershipMutation) -> int:
        try:
            updated = self._gateway.update_shelf_membership(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return updated


class UpdateCoverRecords:
    def __init__(
        self,
        gateway: LibraryRequestMutationGateway,
        unit_of_work: LibraryRequestUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: CoverMutation) -> int:
        try:
            updated = self._gateway.update_covers(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return updated


class ApplyWorkMetadata:
    def __init__(
        self,
        gateway: LibraryRequestMutationGateway,
        unit_of_work: LibraryRequestUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: MetadataApplyMutation) -> MetadataApplyResult:
        try:
            result = self._gateway.apply_metadata(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return result


class CompensateCoverPublication:
    def __init__(
        self,
        gateway: LibraryRequestMutationGateway,
        unit_of_work: LibraryRequestUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: CoverPublicationFailure) -> bool:
        try:
            compensated = self._gateway.compensate_cover_publication(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return compensated


__all__ = [
    "ApplyWorkMetadata",
    "BulkReadingStatusMutation",
    "BulkShelfMembershipMutation",
    "BulkWorkMutation",
    "CompensateCoverPublication",
    "CoverMutation",
    "CoverPublicationFailure",
    "CoverRecordMutation",
    "DetailPreferenceMutation",
    "LibraryRequestMutationGateway",
    "LibraryRequestUnitOfWork",
    "MetadataApplyMutation",
    "MetadataApplyResult",
    "SaveDetailPreference",
    "UpdateBulkReadingStatus",
    "UpdateBulkShelfMembership",
    "UpdateBulkWorks",
    "UpdateCoverRecords",
    "UpdateWorkRecord",
    "WorkRecordMutation",
]
