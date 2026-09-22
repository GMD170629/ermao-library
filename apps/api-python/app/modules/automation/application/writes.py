"""Grant-bound shelf and tag commands with transactionally durable receipts."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from app.modules.automation.application.catalog import AutomationCatalog, scoped_context
from app.modules.automation.application.execution import RecheckMutationAccess
from app.modules.automation.application.grants import GrantUnitOfWork
from app.modules.automation.application.receipts import (
    CompleteReceipt,
    ReceiptStore,
    request_fingerprint,
)
from app.modules.automation.application.refresh import (
    RefreshMetadataChange,
    project_file_metadata,
)
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)
from app.modules.automation.domain.tools import METADATA_BATCH_LIMIT
from app.modules.library.public import (
    ApplyMetadataPatches,
    BulkBookAccessError,
    BulkBookAuthorizationError,
    BulkBookOperationResult,
    BulkMetadataCommand,
    BulkShelfMembershipCommand,
    ExecuteBulkMetadata,
    ExecuteBulkShelfMembership,
    InvalidBulkBookOperationError,
    MetadataChange,
    MetadataPatchActor,
)
from app.modules.shelf.public import (
    CreateShelf,
    CreateShelfCommand,
    DeleteShelf,
    DeleteShelfCommand,
    ShelfKind,
    UpdateShelf,
    UpdateShelfCommand,
)


def shelf_result(value: dict[str, object]) -> dict[str, object]:
    return {
        "shelf_id": value["id"],
        "name": value["name"],
        "description": value.get("description"),
        "kind": value.get("kind", "STATIC"),
        "rules": json.loads(str(value.get("rulesJson") or "{}")),
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
        metadata: ApplyMetadataPatches,
        authorization: RecheckMutationAccess,
        update: UpdateShelf,
        delete: DeleteShelf,
        read_shelf: Callable[[str, str], dict[str, object] | None],
        normalize_rules: Callable[[object], tuple[dict[str, object], str | None]],
    ) -> None:
        self._catalog = catalog
        self._create = create
        self._membership = membership
        self._tags = tags
        self._receipts = receipts
        self._uow = uow
        self._clock = clock_ms
        self._new_id = new_id
        self._metadata = metadata
        self._authorization = authorization
        self._update = update
        self._delete = delete
        self._read_shelf = read_shelf
        self._normalize_rules = normalize_rules

    def create_shelf(
        self,
        access: EffectiveAccess,
        request_id: str,
        name: str,
        description: str | None,
        kind: str = "STATIC",
        rules: dict[str, object] | None = None,
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
        if kind not in {"STATIC", "SMART"}:
            raise AutomationAccessError("INVALID_SHELF_KIND")
        normalized, error = self._normalize_rules(rules)
        if error or (kind == "STATIC" and normalized):
            raise AutomationAccessError("INVALID_SHELF_RULES")
        self._validate_rule_books(access, normalized)
        args: dict[str, object] = {
            "name": name,
            "description": description,
            "kind": kind,
            "rules": normalized,
        }
        fingerprint = request_fingerprint("create_shelf", args, request_id)
        now_ms = self._clock()
        now = datetime.fromtimestamp(now_ms / 1000, UTC)
        values = {
            "id": self._new_id(),
            "name": name,
            "description": description,
            "ownerUserId": access.user_id,
            "kind": kind,
            "rulesJson": json.dumps(normalized),
            "pinned": False,
            "createdAt": now,
            "updatedAt": now,
        }
        command = CreateShelfCommand(values, ShelfKind(kind), (), (), (), now)
        receipt = CompleteReceipt(
            self._receipts, access.grant_id, request_id, shelf_result
        )
        try:
            previous = self._receipts.claim(
                access.grant_id, request_id, "create_shelf", fingerprint, now_ms
            )
            access = self._authorization.require(access, Scope.SHELVES_WRITE)
            if previous is not None:
                self._catalog.get_shelf(access, str(previous["shelf_id"]), 1, 1)
                self._uow.rollback()
                return previous
            return shelf_result(self._create.execute(command, receipt=receipt))
        except Exception:
            self._uow.rollback()
            raise

    def _validate_rule_books(
        self, access: EffectiveAccess, rules: dict[str, object]
    ) -> None:
        ids = rules.get("includedBookIds")
        if isinstance(ids, list):
            for offset in range(0, len(ids), 50):
                self._catalog.get_books(
                    access, [str(value) for value in ids[offset : offset + 50]]
                )

    def update_shelf(
        self,
        access: EffectiveAccess,
        request_id: str,
        shelf_id: str,
        name: str,
        description: str | None,
        kind: str,
        rules: dict[str, object] | None,
    ) -> dict[str, object]:
        access = self._authorization.require(access, Scope.SHELVES_WRITE)
        normalized, error = self._normalize_rules(rules)
        if (
            error
            or kind not in {"STATIC", "SMART"}
            or (kind == "STATIC" and normalized)
            or not name.strip()
            or len(name) > 191
            or any(ord(c) < 32 for c in name)
            or (description is not None and len(description) > 2000)
        ):
            raise AutomationAccessError("INVALID_SHELF")
        self._validate_rule_books(access, normalized)
        fingerprint = request_fingerprint(
            "update_shelf",
            {
                "id": shelf_id,
                "name": name,
                "description": description,
                "kind": kind,
                "rules": normalized,
            },
            request_id,
        )
        now_ms = self._clock()
        try:
            previous = self._receipts.claim(
                access.grant_id, request_id, "update_shelf", fingerprint, now_ms
            )
            existing = self._read_shelf(shelf_id, access.user_id)
            if existing is None or existing.get("kind") == "COLLECTION":
                raise AutomationAccessError("RESOURCE_NOT_FOUND")
            if previous is not None:
                self._uow.rollback()
                return previous
            now = datetime.fromtimestamp(now_ms / 1000, UTC)
            command = UpdateShelfCommand(
                shelf_id,
                {
                    "name": name.strip(),
                    "description": description,
                    "kind": kind,
                    "rulesJson": json.dumps(normalized),
                    "updatedAt": now,
                },
                ShelfKind(str(existing.get("kind") or "STATIC")),
                ShelfKind(kind),
                None,
                None,
                None,
                (),
                (),
                now,
            )
            result = self._update.execute(
                command,
                receipt=CompleteReceipt(
                    self._receipts, access.grant_id, request_id, shelf_result
                ),
            )
            if result is None:
                raise AutomationAccessError("RESOURCE_NOT_FOUND")
            return shelf_result(result)
        except Exception:
            self._uow.rollback()
            raise

    def delete_shelf(
        self, access: EffectiveAccess, request_id: str, shelf_id: str
    ) -> dict[str, object]:
        access = self._authorization.require(access, Scope.SHELVES_WRITE)
        fingerprint = request_fingerprint("delete_shelf", {"id": shelf_id}, request_id)
        now_ms = self._clock()
        try:
            previous = self._receipts.claim(
                access.grant_id, request_id, "delete_shelf", fingerprint, now_ms
            )
            if previous is not None:
                self._uow.rollback()
                return previous
            existing = self._read_shelf(shelf_id, access.user_id)
            if existing is None or existing.get("kind") == "COLLECTION":
                raise AutomationAccessError("RESOURCE_NOT_FOUND")
            result = self._delete.execute(
                DeleteShelfCommand(
                    shelf_id, False, datetime.fromtimestamp(now_ms / 1000, UTC)
                ),
                receipt=CompleteReceipt(
                    self._receipts,
                    access.grant_id,
                    request_id,
                    lambda deleted: {"deleted": deleted, "shelf_id": shelf_id},
                ),
            )
            return {"deleted": result, "shelf_id": shelf_id}
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
            access = self._authorization.require(access, Scope.SHELVES_WRITE)
            self._catalog.get_books(access, book_ids)
            self._catalog.get_shelf(access, shelf_id, 1, 1)
            command = replace(command, context=scoped_context(access))
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
        expected_revisions: dict[str, str] | None = None,
        override_fields: frozenset[str] = frozenset(),
    ) -> dict[str, object]:
        access.require(Scope.BOOKS_WRITE)
        if not 1 <= len(book_ids) <= METADATA_BATCH_LIMIT:
            raise AutomationAccessError("INVALID_BOOK_SELECTION")
        if not 1 <= len(tags) <= 50 or any(
            not value.strip() or len(value) > 191 or any(ord(c) < 32 for c in value)
            for value in tags
        ):
            raise AutomationAccessError("INVALID_TAGS")
        if override_fields:
            access.require(Scope.BOOKS_WRITE)
            if override_fields != {"tags"}:
                raise AutomationAccessError("INVALID_OVERRIDE_FIELDS")
            if expected_revisions is None:
                raise AutomationAccessError("EXPECTED_REVISION_REQUIRED")
        if expected_revisions is not None and set(expected_revisions) != set(book_ids):
            raise AutomationAccessError("EXPECTED_REVISION_REQUIRED")
        self._catalog.get_books(access, book_ids)
        tool = "add_book_tags" if add else "remove_book_tags"
        fingerprint = request_fingerprint(
            tool,
            {
                "book_ids": book_ids,
                "tags": tags,
                "expected_revisions": expected_revisions,
                "override_fields": sorted(override_fields),
            },
            request_id,
        )
        now = self._clock()
        normalized = tuple(dict.fromkeys(value.strip() for value in tags))
        command = BulkMetadataCommand(
            replace(scoped_context(access), can_manage_system=True),
            tuple(book_ids),
            {},
            normalized if add else (),
            () if add else normalized,
            protected_overrides=override_fields,
        )
        receipt = CompleteReceipt(
            self._receipts, access.grant_id, request_id, bulk_result
        )
        try:
            previous = self._receipts.claim(
                access.grant_id, request_id, tool, fingerprint, now
            )
            access = self._authorization.require(access, Scope.BOOKS_WRITE)
            if override_fields:
                access.require(Scope.BOOKS_WRITE)
            self._catalog.get_books(access, book_ids)
            command = replace(
                command, context=replace(scoped_context(access), can_manage_system=True)
            )
            if previous is not None:
                self._uow.rollback()
                return previous
            if expected_revisions is not None:
                for book_id in book_ids:
                    current = self._catalog.get_metadata_schema(access, "book", book_id)
                    if current["expected_revision"] != expected_revisions[book_id]:
                        raise AutomationAccessError("CONFLICT")
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

    def update_metadata(
        self,
        access: EffectiveAccess,
        request_id: str,
        changes: tuple[MetadataChange, ...],
    ) -> dict[str, object]:
        access.require(Scope.BOOKS_WRITE)
        if not changes or len(changes) > METADATA_BATCH_LIMIT:
            raise AutomationAccessError("INVALID_TARGETS")
        arguments: dict[str, object] = {
            "changes": [
                {
                    "target_type": item.target_type,
                    "target_id": item.target_id,
                    "expected_revision": item.expected_revision,
                    "mode": item.mode,
                    "fields": item.fields,
                    "clear_fields": sorted(item.clear_fields),
                    "override_fields": sorted(item.override_fields),
                }
                for item in changes
            ]
        }
        fingerprint = request_fingerprint("update_metadata", arguments, request_id)
        actor = MetadataPatchActor(
            access.user_id,
            access.grant_id,
            access.permissions.library_ids,
            True,
            Scope.BOOKS_WRITE in access.permissions.scopes,
            Scope.BOOKS_WRITE in access.permissions.scopes,
        )
        now = self._clock()
        receipt = CompleteReceipt(
            self._receipts, access.grant_id, request_id, lambda result: result
        )
        try:
            # Scope checks also apply to a replay after grant permissions shrink.
            for item in changes:
                access.require_metadata(
                    changes_tags="tags" in (set(item.fields) | item.clear_fields),
                    overrides_protection=bool(item.override_fields),
                )
                self._catalog.get_metadata_schema(
                    access, item.target_type, item.target_id
                )
            previous = self._receipts.claim(
                access.grant_id, request_id, "update_metadata", fingerprint, now
            )
            access = self._authorization.require(access, Scope.BOOKS_WRITE)
            for item in changes:
                access.require_metadata(
                    changes_tags="tags" in (set(item.fields) | item.clear_fields),
                    overrides_protection=bool(item.override_fields),
                )
                self._catalog.get_metadata_schema(
                    access, item.target_type, item.target_id
                )
            actor = replace(
                actor,
                library_ids=access.permissions.library_ids,
                can_tags=Scope.BOOKS_WRITE in access.permissions.scopes,
                can_override=Scope.BOOKS_WRITE in access.permissions.scopes,
            )
            if previous is not None:
                self._uow.rollback()
                return previous
            return self._metadata.execute(actor, changes, receipt=receipt)
        except Exception:
            self._uow.rollback()
            raise

    def refresh_metadata(
        self,
        access: EffectiveAccess,
        request_id: str,
        requests: tuple[RefreshMetadataChange, ...],
    ) -> dict[str, object]:
        access.require(Scope.SYSTEM_READ, Scope.BOOKS_WRITE)
        if not 1 <= len(requests) <= METADATA_BATCH_LIMIT:
            raise AutomationAccessError("INVALID_TARGETS")
        arguments: dict[str, object] = {
            "changes": [
                {
                    "target_type": item.target_type,
                    "target_id": item.target_id,
                    "expected_revision": item.expected_revision,
                    "node_id": item.node_id,
                    "source": item.source,
                    "fields": item.fields,
                    "expected_file_revision": item.expected_file_revision,
                    "mode": item.mode,
                    "override_fields": sorted(item.override_fields),
                    "sidecar_relative_path": item.sidecar_relative_path,
                }
                for item in requests
            ]
        }
        fingerprint = request_fingerprint("refresh_metadata", arguments, request_id)
        access = self._authorization.require(
            access, Scope.SYSTEM_READ, Scope.BOOKS_WRITE
        )
        for item in requests:
            access.require_metadata(
                changes_tags="tags" in item.fields,
                overrides_protection=bool(item.override_fields),
            )
            self._catalog.require_metadata_source(
                access, item.target_type, item.target_id, item.node_id
            )
        # A successful replay must not parse a newer file or recreate a prior
        # action. Only the original persisted result is returned after access checks.
        previous = self._receipts.lookup(
            access.grant_id, request_id, "refresh_metadata", fingerprint
        )
        if previous is not None:
            return previous
        changes = tuple(
            project_file_metadata(
                item,
                self._catalog.observe_file_metadata(
                    access, item.node_id, item.source, item.sidecar_relative_path
                ),
            )
            for item in requests
        )
        now = self._clock()
        receipt = CompleteReceipt(
            self._receipts, access.grant_id, request_id, lambda result: result
        )
        try:
            previous = self._receipts.claim(
                access.grant_id, request_id, "refresh_metadata", fingerprint, now
            )
            access = self._authorization.require(
                access, Scope.SYSTEM_READ, Scope.BOOKS_WRITE
            )
            for item in requests:
                access.require_metadata(
                    changes_tags="tags" in item.fields,
                    overrides_protection=bool(item.override_fields),
                )
                self._catalog.require_metadata_source(
                    access, item.target_type, item.target_id, item.node_id
                )
            if previous is not None:
                self._uow.rollback()
                return previous
            actor = MetadataPatchActor(
                access.user_id,
                access.grant_id,
                access.permissions.library_ids,
                True,
                Scope.BOOKS_WRITE in access.permissions.scopes,
                Scope.BOOKS_WRITE in access.permissions.scopes,
            )
            return self._metadata.execute(actor, changes, receipt=receipt)
        except Exception:
            self._uow.rollback()
            raise
