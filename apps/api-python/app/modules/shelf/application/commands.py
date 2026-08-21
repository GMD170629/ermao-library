"""Named shelf write commands with explicit transaction ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.modules.shelf.domain.policies import ShelfKind


class ShelfUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ShelfWriteStore(Protocol):
    def create_shelf(self, db: object, values: dict[str, Any]) -> dict[str, Any]: ...

    def update_shelf(
        self, db: object, shelf_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def replace_shelf_books(
        self,
        db: object,
        shelf_id: str,
        book_ids: list[str],
        *,
        now: datetime,
    ) -> None: ...

    def replace_collection_members(
        self,
        db: object,
        *,
        collection_id: str,
        shelf_ids: list[str],
        now: datetime,
    ) -> None: ...

    def replace_shelf_collections(
        self,
        db: object,
        *,
        shelf_id: str,
        collection_ids: list[str],
        now: datetime,
    ) -> None: ...

    def touch_shelves_updated_at(
        self, db: object, shelf_ids: list[str], *, now: datetime
    ) -> None: ...

    def collection_has_members(self, db: object, collection_id: str) -> bool: ...

    def clear_library_shelf_links(
        self, db: object, shelf_id: str, *, now: datetime
    ) -> None: ...

    def delete_shelf(self, db: object, shelf_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class CreateShelfCommand:
    values: dict[str, Any]
    kind: ShelfKind
    book_ids: tuple[str, ...]
    member_shelf_ids: tuple[str, ...]
    collection_ids: tuple[str, ...]
    now: datetime


@dataclass(frozen=True, slots=True)
class UpdateShelfCommand:
    shelf_id: str
    values: dict[str, Any]
    existing_kind: ShelfKind
    kind: ShelfKind
    book_ids: tuple[str, ...] | None
    member_shelf_ids: tuple[str, ...] | None
    collection_ids: tuple[str, ...] | None
    previous_member_shelf_ids: tuple[str, ...]
    previous_collection_ids: tuple[str, ...]
    now: datetime


@dataclass(frozen=True, slots=True)
class DeleteShelfCommand:
    shelf_id: str
    is_collection: bool
    now: datetime


class CreateShelf:
    def __init__(
        self,
        store: ShelfWriteStore,
        unit_of_work: ShelfUnitOfWork,
    ) -> None:
        self._store = store
        self._unit_of_work = unit_of_work

    def execute(self, command: CreateShelfCommand) -> dict[str, Any]:
        static_book_ids = (
            list(command.book_ids) if command.kind is ShelfKind.STATIC else None
        )
        collection_member_ids = (
            list(command.member_shelf_ids)
            if command.kind is ShelfKind.COLLECTION
            else None
        )
        collection_ids = (
            list(command.collection_ids)
            if command.kind is not ShelfKind.COLLECTION and command.collection_ids
            else None
        )
        try:
            shelf = self._store.create_shelf(self._unit_of_work, command.values)
            shelf_id = str(shelf["id"])
            if static_book_ids is not None:
                self._store.replace_shelf_books(
                    self._unit_of_work,
                    shelf_id,
                    static_book_ids,
                    now=command.now,
                )
            if collection_member_ids is not None:
                self._store.replace_collection_members(
                    self._unit_of_work,
                    collection_id=shelf_id,
                    shelf_ids=collection_member_ids,
                    now=command.now,
                )
                self._store.touch_shelves_updated_at(
                    self._unit_of_work,
                    collection_member_ids,
                    now=command.now,
                )
            if collection_ids is not None:
                self._store.replace_shelf_collections(
                    self._unit_of_work,
                    shelf_id=shelf_id,
                    collection_ids=collection_ids,
                    now=command.now,
                )
                self._store.touch_shelves_updated_at(
                    self._unit_of_work,
                    collection_ids,
                    now=command.now,
                )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return shelf


class UpdateShelf:
    def __init__(
        self,
        store: ShelfWriteStore,
        unit_of_work: ShelfUnitOfWork,
    ) -> None:
        self._store = store
        self._unit_of_work = unit_of_work

    def execute(self, command: UpdateShelfCommand) -> dict[str, Any] | None:
        replacement_book_ids = (
            list(command.book_ids)
            if command.book_ids is not None and command.kind is ShelfKind.STATIC
            else []
            if command.kind is ShelfKind.SMART
            and command.existing_kind is not ShelfKind.SMART
            else None
        )
        replacement_member_ids = (
            list(command.member_shelf_ids)
            if command.kind is ShelfKind.COLLECTION
            and command.member_shelf_ids is not None
            else None
        )
        replacement_collection_ids = (
            list(command.collection_ids)
            if command.kind is not ShelfKind.COLLECTION
            and command.collection_ids is not None
            else None
        )
        touched_member_ids = list(
            dict.fromkeys(
                (*command.previous_member_shelf_ids, *(replacement_member_ids or ()))
            )
        )
        touched_collection_ids = list(
            dict.fromkeys(
                (
                    *command.previous_collection_ids,
                    *(replacement_collection_ids or ()),
                )
            )
        )
        try:
            shelf = self._store.update_shelf(
                self._unit_of_work,
                command.shelf_id,
                command.values,
            )
            if shelf is None:
                self._unit_of_work.rollback()
                return None
            if replacement_book_ids is not None:
                self._store.replace_shelf_books(
                    self._unit_of_work,
                    command.shelf_id,
                    replacement_book_ids,
                    now=command.now,
                )
            if replacement_member_ids is not None:
                self._store.replace_collection_members(
                    self._unit_of_work,
                    collection_id=command.shelf_id,
                    shelf_ids=replacement_member_ids,
                    now=command.now,
                )
                self._store.touch_shelves_updated_at(
                    self._unit_of_work,
                    touched_member_ids,
                    now=command.now,
                )
            if replacement_collection_ids is not None:
                self._store.replace_shelf_collections(
                    self._unit_of_work,
                    shelf_id=command.shelf_id,
                    collection_ids=replacement_collection_ids,
                    now=command.now,
                )
                self._store.touch_shelves_updated_at(
                    self._unit_of_work,
                    touched_collection_ids,
                    now=command.now,
                )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return shelf


class DeleteShelf:
    def __init__(
        self,
        store: ShelfWriteStore,
        unit_of_work: ShelfUnitOfWork,
    ) -> None:
        self._store = store
        self._unit_of_work = unit_of_work

    def execute(self, command: DeleteShelfCommand) -> bool:
        try:
            if command.is_collection and self._store.collection_has_members(
                self._unit_of_work,
                command.shelf_id,
            ):
                raise ValueError("SHELF_COLLECTION_NOT_EMPTY")
            self._store.clear_library_shelf_links(
                self._unit_of_work,
                command.shelf_id,
                now=command.now,
            )
            deleted = self._store.delete_shelf(
                self._unit_of_work,
                command.shelf_id,
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return deleted
