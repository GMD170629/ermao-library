"""Grant-bound shelf and tag commands with transactionally durable receipts."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from app.modules.automation.application.catalog import AutomationCatalog, scoped_context
from app.modules.automation.application.grants import GrantUnitOfWork
from app.modules.automation.application.receipts import (
    CompleteReceipt,
    ReceiptStore,
    request_fingerprint,
)
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)
from app.modules.automation.domain.tools import METADATA_BATCH_LIMIT
from app.modules.library.public import (
    BulkBookAccessError,
    BulkBookAuthorizationError,
    BulkBookOperationResult,
    BulkMetadataCommand,
    BulkShelfMembershipCommand,
    ExecuteBulkMetadata,
    ExecuteBulkShelfMembership,
    InvalidBulkBookOperationError,
)
from app.modules.shelf.public import CreateShelf, CreateShelfCommand, ShelfKind


def shelf_result(value: dict[str, object]) -> dict[str, object]:
    return {
        "shelf_id": value["id"],
        "name": value["name"],
        "description": value.get("description"),
        "kind": "STATIC",
    }


def bulk_result(value: BulkBookOperationResult) -> dict[str, object]:
    return {
        "updated": value.updated,
        "changed_values": value.changed_values,
        "operation_id": value.operation.id,
    }


class AutomationWrites:
    def __init__(
        self,
        catalog: AutomationCatalog,
        create: CreateShelf,
        membership: ExecuteBulkShelfMembership,
        tags: ExecuteBulkMetadata,
        receipts: ReceiptStore,
        uow: GrantUnitOfWork,
        clock_ms: Callable[[], int],
        new_id: Callable[[], str],
    ) -> None:
        self._catalog = catalog
        self._create = create
        self._membership = membership
        self._tags = tags
        self._receipts = receipts
        self._uow = uow
        self._clock = clock_ms
        self._new_id = new_id

    def create_shelf(
        self,
        access: EffectiveAccess,
        request_id: str,
        name: str,
        description: str | None,
    ) -> dict[str, object]:
        access.require(Scope.SHELVES_WRITE)
        name = name.strip()
        if (
            not name
            or len(name) > 191
            or any(ord(c) < 32 for c in name)
            or (description is not None and len(description) > 2000)
        ):
            raise AutomationAccessError("INVALID_SHELF")
        args: dict[str, object] = {"name": name, "description": description}
        fingerprint = request_fingerprint("create_shelf", args, request_id)
        now_ms = self._clock()
        now = datetime.fromtimestamp(now_ms / 1000, UTC)
        values = {
            "id": self._new_id(),
            "name": name,
            "description": description,
            "ownerUserId": access.user_id,
            "kind": "STATIC",
            "rulesJson": "{}",
            "pinned": False,
            "createdAt": now,
            "updatedAt": now,
        }
        command = CreateShelfCommand(values, ShelfKind.STATIC, (), (), (), now)
        receipt = CompleteReceipt(
            self._receipts, access.grant_id, request_id, shelf_result
        )
        try:
            previous = self._receipts.claim(
                access.grant_id, request_id, "create_shelf", fingerprint, now_ms
            )
            if previous is not None:
                self._catalog.get_shelf(access, str(previous["shelf_id"]), 1, 1)
                self._uow.rollback()
                return previous
            return shelf_result(self._create.execute(command, receipt=receipt))
        except Exception:
            self._uow.rollback()
            raise

    def shelf_membership(
        self,
        access: EffectiveAccess,
        request_id: str,
        shelf_id: str,
        book_ids: list[str],
        *,
        add: bool,
    ) -> dict[str, object]:
        access.require(Scope.SHELVES_WRITE)
        self._catalog.get_books(access, book_ids)
        self._catalog.get_shelf(access, shelf_id, 1, 1)
        tool = "add_shelf_books" if add else "remove_shelf_books"
        fingerprint = request_fingerprint(
            tool, {"shelf_id": shelf_id, "book_ids": book_ids}, request_id
        )
        now = self._clock()
        command = BulkShelfMembershipCommand(
            scoped_context(access),
            tuple(book_ids),
            shelf_id,
            "ADD" if add else "REMOVE",
        )
        receipt = CompleteReceipt(
            self._receipts, access.grant_id, request_id, bulk_result
        )
        try:
            previous = self._receipts.claim(
                access.grant_id, request_id, tool, fingerprint, now
            )
            if previous is not None:
                self._uow.rollback()
                return previous
            return bulk_result(self._membership.execute(command, receipt=receipt))
        except (
            BulkBookAccessError,
            BulkBookAuthorizationError,
            InvalidBulkBookOperationError,
        ) as error:
            self._uow.rollback()
            raise AutomationAccessError("RESOURCE_NOT_FOUND") from error
        except Exception:
            self._uow.rollback()
            raise

    def book_tags(
        self,
        access: EffectiveAccess,
        request_id: str,
        book_ids: list[str],
        tags: list[str],
        *,
        add: bool,
    ) -> dict[str, object]:
        access.require(Scope.TAGS_WRITE)
        if not 1 <= len(book_ids) <= METADATA_BATCH_LIMIT:
            raise AutomationAccessError("INVALID_BOOK_SELECTION")
        if not 1 <= len(tags) <= 50 or any(
            not value.strip() or len(value) > 191 or any(ord(c) < 32 for c in value)
            for value in tags
        ):
            raise AutomationAccessError("INVALID_TAGS")
        self._catalog.get_books(access, book_ids)
        tool = "add_book_tags" if add else "remove_book_tags"
        fingerprint = request_fingerprint(
            tool, {"book_ids": book_ids, "tags": tags}, request_id
        )
        now = self._clock()
        normalized = tuple(dict.fromkeys(value.strip() for value in tags))
        command = BulkMetadataCommand(
            replace(scoped_context(access), can_manage_system=True),
            tuple(book_ids),
            {},
            normalized if add else (),
            () if add else normalized,
            protected_overrides=frozenset(),
        )
        receipt = CompleteReceipt(
            self._receipts, access.grant_id, request_id, bulk_result
        )
        try:
            previous = self._receipts.claim(
                access.grant_id, request_id, tool, fingerprint, now
            )
            if previous is not None:
                self._uow.rollback()
                return previous
            return bulk_result(self._tags.execute(command, receipt=receipt))
        except InvalidBulkBookOperationError as error:
            self._uow.rollback()
            code = (
                "PROTECTED_FIELD"
                if str(error) == "PROTECTED_FIELD"
                else "INVALID_TAG_CHANGE"
            )
            raise AutomationAccessError(code) from error
        except (BulkBookAccessError, BulkBookAuthorizationError) as error:
            self._uow.rollback()
            raise AutomationAccessError("RESOURCE_NOT_FOUND") from error
        except Exception:
            self._uow.rollback()
            raise
