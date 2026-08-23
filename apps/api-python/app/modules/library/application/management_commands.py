"""Named library-management commands and their transaction boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class LibraryManagementUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class LibraryFacetManagementGateway(Protocol):
    def merge_facets(
        self,
        kind: str,
        source_ids: list[str],
        target_id: str,
        user_id: str | None,
    ) -> dict[str, object]: ...

    def rename_facet(
        self, facet_id: str, name: str, user_id: str | None
    ) -> dict[str, object]: ...

    def delete_facet(self, facet_id: str, user_id: str | None) -> dict[str, object]: ...


class LibraryOperationManagementGateway(Protocol):
    def undo_operation(
        self,
        operation_id: str,
        user_id: str,
        *,
        can_manage_system: bool,
    ) -> dict[str, object]: ...


class FacetSyncGateway(Protocol):
    def sync_book(self, book_id: str) -> None: ...

    def sync_books(self, book_ids: Iterable[str]) -> None: ...


class MergeLibraryFacets:
    def __init__(
        self, gateway: LibraryFacetManagementGateway, uow: LibraryManagementUnitOfWork
    ) -> None:
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
            result = self._gateway.merge_facets(kind, source_ids, target_id, user_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class RenameLibraryFacet:
    def __init__(
        self, gateway: LibraryFacetManagementGateway, uow: LibraryManagementUnitOfWork
    ) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(
        self, facet_id: str, name: str, user_id: str | None
    ) -> dict[str, object]:
        try:
            result = self._gateway.rename_facet(facet_id, name, user_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class DeleteLibraryFacet:
    def __init__(
        self, gateway: LibraryFacetManagementGateway, uow: LibraryManagementUnitOfWork
    ) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(self, facet_id: str, user_id: str | None) -> dict[str, object]:
        try:
            result = self._gateway.delete_facet(facet_id, user_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class UndoLibraryOperation:
    def __init__(
        self,
        gateway: LibraryOperationManagementGateway,
        uow: LibraryManagementUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(
        self,
        operation_id: str,
        user_id: str,
        *,
        can_manage_system: bool,
    ) -> dict[str, object]:
        try:
            result = self._gateway.undo_operation(
                operation_id,
                user_id,
                can_manage_system=can_manage_system,
            )
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return result


class LibraryOperationNotFoundError(Exception):
    """The operation does not exist or is intentionally hidden from the actor."""


class LibraryOperationAuthorizationError(Exception):
    """The actor cannot undo this operation."""


class InvalidLibraryOperationError(Exception):
    """The operation is finalized, expired, already undone, or malformed."""


class SyncBookFacets:
    def __init__(
        self, gateway: FacetSyncGateway, uow: LibraryManagementUnitOfWork
    ) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(self, book_id: str) -> None:
        try:
            self._gateway.sync_book(book_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise


class SyncBooksFacets:
    def __init__(
        self, gateway: FacetSyncGateway, uow: LibraryManagementUnitOfWork
    ) -> None:
        self._gateway = gateway
        self._uow = uow

    def execute(self, book_ids: Iterable[str]) -> None:
        prepared_ids = tuple(book_ids)
        try:
            self._gateway.sync_books(prepared_ids)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
