"""Atomic, versioned database metadata patches for Books, Resources and Nodes."""

from dataclasses import asdict, dataclass, replace
from typing import Protocol

from app.contracts.mutation_receipt import MutationReceipt
from app.modules.library.domain.metadata_patch import (
    METADATA_FIELDS,
    MetadataChange,
    MetadataPatchError,
    MetadataTarget,
    MetadataValue,
    prepare_metadata_patch,
)


@dataclass(frozen=True)
class MetadataPatchActor:
    user_id: str | None
    grant_id: str | None
    library_ids: frozenset[str]
    can_write: bool
    can_tags: bool
    can_override: bool
    system_task_id: str | None = None


@dataclass(frozen=True)
class MetadataSnapshot:
    target_type: MetadataTarget
    target_id: str
    library_id: str
    book_id: str
    revision: str
    values: dict[str, MetadataValue]
    protected: frozenset[str]
    linked_book_id: str | None = None
    linked_values: dict[str, MetadataValue] | None = None
    source_node_id: str | None = None
    cover_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedMetadataPatch:
    before: MetadataSnapshot
    values: dict[str, MetadataValue]
    provenance: dict[str, str] | None = None
    resolved_cover_path: str | None = None
    automatic: bool = False


class MetadataPatchPort(Protocol):
    def snapshot(
        self, target_type: MetadataTarget, target_id: str, library_ids: frozenset[str]
    ) -> MetadataSnapshot | None: ...
    def resolve_cover(self, before: MetadataSnapshot, reference: str) -> str: ...
    def apply(self, patch: PreparedMetadataPatch) -> None: ...
    def record(
        self, actor: MetadataPatchActor, patches: tuple[PreparedMetadataPatch, ...]
    ) -> str: ...


class MetadataPatchUnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class GetMetadataSchema:
    port: MetadataPatchPort

    def execute(
        self, target_type: MetadataTarget, target_id: str, library_ids: frozenset[str]
    ) -> dict[str, object]:
        snapshot = self.port.snapshot(target_type, target_id, library_ids)
        if snapshot is None:
            raise MetadataPatchError("RESOURCE_NOT_FOUND")
        return {
            "target_type": target_type,
            "target_id": target_id,
            "expected_revision": snapshot.revision,
            "values": snapshot.values,
            "protected_fields": sorted(
                snapshot.protected & METADATA_FIELDS[target_type].keys()
            ),
            "fields": {
                name: asdict(field)
                for name, field in METADATA_FIELDS[target_type].items()
            },
            "cover_references": list(snapshot.cover_references),
            "linked_book_id": snapshot.linked_book_id,
            "linked_values": snapshot.linked_values,
        }


@dataclass(frozen=True)
class ApplyMetadataPatches:
    port: MetadataPatchPort
    uow: MetadataPatchUnitOfWork

    def stage(
        self,
        actor: MetadataPatchActor,
        changes: tuple[MetadataChange, ...],
        *,
        receipt: MutationReceipt[dict[str, object]] | None = None,
        skip_unchanged: bool = False,
    ) -> dict[str, object]:
        """Stage within the calling application transaction; never commit here."""
        if actor.user_id is None and not actor.system_task_id:
            raise MetadataPatchError("ACTOR_REQUIRED")
        if actor.system_task_id and (actor.can_override or actor.grant_id):
            raise MetadataPatchError("INVALID_SYSTEM_ACTOR")
        if not actor.can_write:
            raise MetadataPatchError("SCOPE_REQUIRED")
        if not 1 <= len(changes) <= 20 or len(
            {(item.target_type, item.target_id) for item in changes}
        ) != len(changes):
            raise MetadataPatchError("INVALID_TARGETS")
        prepared: list[PreparedMetadataPatch] = []
        for change in changes:
            before = self.port.snapshot(
                change.target_type, change.target_id, actor.library_ids
            )
            if before is None:
                raise MetadataPatchError("RESOURCE_NOT_FOUND")
            if before.revision != change.expected_revision:
                raise MetadataPatchError("CONFLICT")
            if (
                "tags" in (set(change.fields) | change.clear_fields)
                and not actor.can_tags
            ):
                raise MetadataPatchError("TAGS_SCOPE_REQUIRED")
            effective = change
            if skip_unchanged:
                unchanged = frozenset(key for key, value in change.fields.items() if before.values.get(key) == value)
                # Validate the original input even when it is a no-op. Existing
                # protection must not turn identical values into a new write.
                prepare_metadata_patch(change, before.values, before.protected - unchanged,
                                       allow_override=actor.can_override)
                fields = {key: value for key, value in change.fields.items() if before.values.get(key) != value}
                cleared = frozenset(key for key in change.clear_fields if before.values.get(key) not in (None, ()))
                effective = replace(change, fields=fields, clear_fields=cleared,
                                    override_fields=change.override_fields & (fields.keys() | cleared))
            values = (prepare_metadata_patch(effective, before.values, before.protected,
                                             allow_override=actor.can_override)
                      if effective.fields or effective.clear_fields else {})
            if change.mode == "fill_missing" and before.linked_values:
                values = {
                    key: value
                    for key, value in values.items()
                    if before.linked_values.get(key) in (None, "", ())
                }
            if skip_unchanged:
                values = {key: value for key, value in values.items() if before.values.get(key) != value}
            cover_path = None
            reference = values.get("cover_ref")
            if reference is not None:
                if not isinstance(reference, str):
                    raise MetadataPatchError("INVALID_COVER_REFERENCE")
                cover_path = self.port.resolve_cover(before, reference)
            prepared.append(
                PreparedMetadataPatch(before, values, change.provenance, cover_path, bool(actor.system_task_id))
            )
        # A root Node patch also changes its Book. Overlapping explicit
        # targets in one batch would otherwise evaluate against stale state.
        books = {
            item.before.target_id
            for item in prepared
            if item.before.target_type == "book"
        }
        if any(
            item.before.linked_book_id in books
            for item in prepared
            if item.before.linked_book_id
        ):
            raise MetadataPatchError("OVERLAPPING_TARGETS")
        # Resource revisions include their parent. Apply children before a
        # jointly selected parent patch so the batch cannot invalidate itself.
        for patch in sorted(prepared, key=lambda item: item.before.target_type == "book"):
            if patch.values:
                self.port.apply(patch)
        operation_id = self.port.record(actor, tuple(prepared)) if any(item.values for item in prepared) else None
        result: dict[str, object] = {
            "operation_id": operation_id,
            "updated": sum(bool(item.values) for item in prepared),
            "targets": [
                {
                    "target_type": item.before.target_type,
                    "target_id": item.before.target_id,
                    "fields": sorted(item.values),
                }
                for item in prepared
            ],
        }
        if receipt is not None:
            receipt.complete(result)
        return result

    def execute(
        self, actor: MetadataPatchActor, changes: tuple[MetadataChange, ...], *,
        receipt: MutationReceipt[dict[str, object]] | None = None,
        skip_unchanged: bool = False,
    ) -> dict[str, object]:
        try:
            result = self.stage(actor, changes, receipt=receipt, skip_unchanged=skip_unchanged)
            self.uow.commit()
            return result
        except Exception:
            self.uow.rollback()
            raise
