"""Atomic, versioned database metadata patches for Books, Resources and Nodes."""

from dataclasses import asdict, dataclass
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
    user_id: str
    grant_id: str
    library_ids: frozenset[str]
    can_write: bool
    can_tags: bool
    can_override: bool


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


@dataclass(frozen=True)
class PreparedMetadataPatch:
    before: MetadataSnapshot
    values: dict[str, MetadataValue]
    provenance: dict[str, str] | None = None


class MetadataPatchPort(Protocol):
    def snapshot(
        self, target_type: MetadataTarget, target_id: str, library_ids: frozenset[str]
    ) -> MetadataSnapshot | None: ...
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
            "linked_book_id": snapshot.linked_book_id,
            "linked_values": snapshot.linked_values,
        }


@dataclass(frozen=True)
class ApplyMetadataPatches:
    port: MetadataPatchPort
    uow: MetadataPatchUnitOfWork

    def execute(
        self,
        actor: MetadataPatchActor,
        changes: tuple[MetadataChange, ...],
        *,
        receipt: MutationReceipt[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        if not actor.can_write:
            raise MetadataPatchError("SCOPE_REQUIRED")
        if not 1 <= len(changes) <= 20 or len(
            {(item.target_type, item.target_id) for item in changes}
        ) != len(changes):
            raise MetadataPatchError("INVALID_TARGETS")
        try:
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
                values = prepare_metadata_patch(
                    change,
                    before.values,
                    before.protected,
                    allow_override=actor.can_override,
                )
                if change.mode == "fill_missing" and before.linked_values:
                    values = {
                        key: value
                        for key, value in values.items()
                        if before.linked_values.get(key) in (None, "", ())
                    }
                prepared.append(
                    PreparedMetadataPatch(before, values, change.provenance)
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
            for patch in prepared:
                if patch.values:
                    self.port.apply(patch)
            operation_id = self.port.record(actor, tuple(prepared))
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
            self.uow.commit()
            return result
        except Exception:
            self.uow.rollback()
            raise
