"""Named library-management commands and their transaction boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class LibraryManagementUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class LibraryManagementGateway(Protocol):
    def merge_works(
        self, target_work_id: str, source_work_ids: list[str], user_id: str | None
    ) -> dict[str, object]: ...

    def merge_categories(
        self,
        kind: str,
        source_ids: list[str],
        target_id: str,
        user_id: str | None,
    ) -> dict[str, object]: ...

    def rename_category(
        self, facet_id: str, name: str, user_id: str | None
    ) -> dict[str, object]: ...

    def delete_category(
        self, facet_id: str, user_id: str | None
    ) -> dict[str, object]: ...

    def undo_operation(
        self, operation_id: str, user_id: str | None
    ) -> dict[str, object]: ...


class FacetSyncGateway(Protocol):
    def sync_work(self, work_id: str) -> None: ...

    def sync_works(self, work_ids: Iterable[str]) -> None: ...


class MergeLibraryWorks:
    def __init__(self, gateway: LibraryManagementGateway, uow: LibraryManagementUnitOfWork) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(
        self,
        target_work_id: str,
        source_work_ids: list[str],
        user_id: str | None,
    ) -> dict[str, object]:
        try:
            result = self._gateway.merge_works(target_work_id, source_work_ids, user_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class MergeLibraryCategories:
    def __init__(self, gateway: LibraryManagementGateway, uow: LibraryManagementUnitOfWork) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(
        self,
        kind: str,
        source_ids: list[str],
        target_id: str,
        user_id: str | None,
    ) -> dict[str, object]:
        try:
            result = self._gateway.merge_categories(kind, source_ids, target_id, user_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class RenameLibraryCategory:
    def __init__(self, gateway: LibraryManagementGateway, uow: LibraryManagementUnitOfWork) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(self, facet_id: str, name: str, user_id: str | None) -> dict[str, object]:
        try:
            result = self._gateway.rename_category(facet_id, name, user_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class DeleteLibraryCategory:
    def __init__(self, gateway: LibraryManagementGateway, uow: LibraryManagementUnitOfWork) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(self, facet_id: str, user_id: str | None) -> dict[str, object]:
        try:
            result = self._gateway.delete_category(facet_id, user_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class UndoLibraryOperation:
    def __init__(self, gateway: LibraryManagementGateway, uow: LibraryManagementUnitOfWork) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(self, operation_id: str, user_id: str | None) -> dict[str, object]:
        try:
            result = self._gateway.undo_operation(operation_id, user_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class SyncWorkFacets:
    def __init__(self, gateway: FacetSyncGateway, uow: LibraryManagementUnitOfWork) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(self, work_id: str) -> None:
        try:
            self._gateway.sync_work(work_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise


class SyncWorksFacets:
    def __init__(self, gateway: FacetSyncGateway, uow: LibraryManagementUnitOfWork) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(self, work_ids: Iterable[str]) -> None:
        prepared_ids = tuple(work_ids)
        try:
            self._gateway.sync_works(prepared_ids)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
