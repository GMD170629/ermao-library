"""Scoped snapshots and reuse of the existing database-only metadata writers."""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.time import to_timestamp_ms
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.models.common import db_timestamp
from app.modules.library.application.facet_sync import (
    BookFacetProjection,
    prepare_book_facet,
)
from app.modules.library.application.metadata_effects import MetadataSideEffectPolicy
from app.modules.library.application.metadata_ownership import (
    protect_fields,
    protected_fields,
)
from app.modules.library.application.metadata_patches import (
    MetadataPatchActor,
    MetadataSnapshot,
    PreparedMetadataPatch,
)
from app.modules.library.application.resource_commands import ResourceMetadataChanges
from app.modules.library.application.source_node_commands import (
    SourceNodeMetadataChanges,
)
from app.modules.library.domain.metadata_patch import (
    METADATA_FIELDS,
    MetadataPatchError,
    MetadataTarget,
    MetadataValue,
)
from app.modules.library.infrastructure.book_commands import SqlAlchemyBookMutation
from app.modules.library.infrastructure.facet_sync import (
    execute_book_facet_write,
    prepare_book_facet_write,
)
from app.modules.library.infrastructure.operations import (
    prepare_operation_write,
    write_prepared_operation,
)
from app.modules.library.infrastructure.resource_commands import (
    SqlAlchemyResourceMetadata,
)
from app.modules.library.infrastructure.source_node_commands import (
    SqlAlchemySourceNodeMetadata,
)


def _cover_reference(path: str | None) -> str | None:
    return "cover:" + hashlib.sha256(path.encode()).hexdigest() if path else None


class SqlAlchemyMetadataPatches:
    def __init__(self, db: Session, *, prepared_covers: dict[tuple[str, str], tuple[str, str]] | None = None) -> None:
        self._db = db
        self._prepared_covers = prepared_covers or {}

    def _cover_candidates(self, book_id: str, library_id: str) -> dict[str, str]:
        # Only immutable publications from local import are reusable. User-upload
        # slots can be replaced/deleted and must never become shared references.
        rows = self._db.execute(
            select(
                LibraryResourceAsset.local_cover_path, LibraryResourceAsset.resource_id
            )
            .join(
                LibraryReadableResource,
                LibraryReadableResource.id == LibraryResourceAsset.resource_id,
            )
            .where(
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.library_id == library_id,
                LibraryResourceAsset.library_id == library_id,
                LibraryResourceAsset.local_cover_path.is_not(None),
            )
            .order_by(LibraryResourceAsset.id)
            .limit(50)
        )
        candidates: dict[str, str] = {}
        for path, resource_id in rows:
            if (
                not path
                or not re.fullmatch(
                    r"covers/resources/"
                    + re.escape(resource_id)
                    + r"(?:\.[0-9a-f]{32}\.(?:jpg|png|gif|webp)|-candidate-[0-9a-f]{64})",
                    path,
                )
                or "/" in resource_id
                or "\\" in resource_id
            ):
                continue
            reference = _cover_reference(path)
            if reference is not None:
                candidates[reference] = path
        return candidates

    def resolve_cover(self, before: MetadataSnapshot, reference: str) -> str:
        prepared = self._prepared_covers.get((before.target_type, before.target_id))
        if prepared and prepared[0] == reference:
            return prepared[1]
        candidate = self._cover_candidates(before.book_id, before.library_id).get(
            reference
        )
        if candidate is None:
            raise MetadataPatchError("INVALID_COVER_REFERENCE")
        return candidate

    def snapshot(
        self, target_type: MetadataTarget, target_id: str, library_ids: frozenset[str]
    ) -> MetadataSnapshot | None:
        linked = None
        node_name = ""
        metadata: (
            LibraryBookMetadata
            | LibraryReadableResourceMetadata
            | LibrarySourceNodeMetadata
            | None
        )
        owner_metadata = None
        if target_type == "book":
            entity = self._db.scalar(
                select(LibraryBook)
                .execution_options(populate_existing=True)
                .where(
                    LibraryBook.id == target_id, LibraryBook.library_id.in_(library_ids)
                )
            )
            if entity is None:
                return None
            metadata = self._db.get(
                LibraryBookMetadata, target_id, populate_existing=True
            )
            source_node_id = entity.source_node_id
            book_id, library_id = entity.id, entity.library_id
        elif target_type == "resource":
            resource = self._db.scalar(
                select(LibraryReadableResource)
                .execution_options(populate_existing=True)
                .where(
                    LibraryReadableResource.id == target_id,
                    LibraryReadableResource.library_id.in_(library_ids),
                )
            )
            if resource is None:
                return None
            metadata = self._db.get(
                LibraryReadableResourceMetadata, target_id, populate_existing=True
            )
            source_node_id = resource.source_node_id
            book_id, library_id = resource.book_id, resource.library_id
        elif target_type == "source_node":
            node = self._db.scalar(
                select(LibrarySourceNode)
                .execution_options(populate_existing=True)
                .where(
                    LibrarySourceNode.id == target_id,
                    LibrarySourceNode.library_id.in_(library_ids),
                    LibrarySourceNode.physical_kind == "DIRECTORY",
                )
            )
            if node is None:
                return None
            source_node_id = node.id
            node_name = node.name
            root = aliased(LibrarySourceNode)
            root_path = func.rtrim(root.relative_path, "/")
            owners = self._db.scalars(
                select(LibraryBook)
                .join(root, root.id == LibraryBook.source_node_id)
                .where(
                    LibraryBook.library_id == node.library_id,
                    or_(
                        root.id == node.id,
                        func.substr(node.relative_path, 1, func.length(root_path) + 1)
                        == root_path + "/",
                    ),
                )
                .limit(2)
            ).all()
            if len(owners) != 1:
                return None
            book_id, library_id = owners[0].id, node.library_id
            metadata = self._db.get(
                LibrarySourceNodeMetadata, target_id, populate_existing=True
            )
            if owners[0].source_node_id == node.id:
                linked = book_id
                owner_metadata = self._db.get(
                    LibraryBookMetadata, book_id, populate_existing=True
                )
        else:
            return None
        values: dict[str, MetadataValue] = {}
        for field in METADATA_FIELDS[target_type]:
            value = (
                _cover_reference(metadata.cover_path if metadata else None)
                if field == "cover_ref"
                else getattr(metadata, field, None)
            )
            if isinstance(value, datetime):
                value = value.astimezone(UTC).isoformat(timespec="milliseconds")
            values[field] = value
        if target_type == "book":
            values["tags"] = tuple(
                self._db.scalars(
                    select(LibraryFacet.name)
                    .join(
                        LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id
                    )
                    .where(
                        LibraryBookFacet.book_id == target_id,
                        LibraryFacet.kind == "TAG",
                    )
                    .order_by(LibraryBookFacet.sort_order, LibraryFacet.id)
                )
            )
        if target_type == "source_node" and not values["title"]:
            values["title"] = node_name
        protected = protected_fields(
            metadata.protected_fields if metadata is not None else None
        )
        # The root Node writer synchronizes Book text; its protection and version
        # participate even if the node's own metadata row has never been created.
        related: tuple[object, ...] | None = None
        if owner_metadata is not None:
            protected |= protected_fields(owner_metadata.protected_fields) & {
                "title",
                "description",
                "cover_path",
            }
            related = (
                owner_metadata.title,
                owner_metadata.description,
                _cover_reference(owner_metadata.cover_path),
                owner_metadata.protected_fields,
                to_timestamp_ms(owner_metadata.updated_at),
            )
        protected = frozenset(
            "cover_ref" if field == "cover_path" else field for field in protected
        )
        if target_type == "resource":
            parent = self._db.get(LibraryBookMetadata, book_id, populate_existing=True)
            related = ((parent.title, parent.author, parent.protected_fields,
                        to_timestamp_ms(parent.updated_at)) if parent else None)
        revision = hashlib.sha256(
            json.dumps(
                [
                    target_type,
                    target_id,
                    library_id,
                    book_id,
                    values,
                    sorted(protected),
                    to_timestamp_ms(metadata.updated_at) if metadata else None,
                    related,
                ],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return MetadataSnapshot(
            target_type,
            target_id,
            library_id,
            book_id,
            revision,
            values,
            protected,
            linked,
            {
                "title": owner_metadata.title,
                "description": owner_metadata.description,
                "cover_ref": _cover_reference(owner_metadata.cover_path),
            }
            if owner_metadata is not None
            else None,
            source_node_id,
            tuple(self._cover_candidates(book_id, library_id)),
        )

    def apply(self, patch: PreparedMetadataPatch) -> None:
        before, values = patch.before, patch.values
        current = self.snapshot(
            before.target_type, before.target_id, frozenset({before.library_id})
        )
        if current is None or current.revision != before.revision:
            raise MetadataPatchError("CONFLICT")
        resolved_cover = patch.resolved_cover_path
        if "cover_ref" in values and values["cover_ref"] is not None:
            reference = values["cover_ref"]
            if (
                not isinstance(reference, str)
                or self.resolve_cover(before, reference) != resolved_cover
            ):
                raise MetadataPatchError("CONFLICT")
        if before.target_type == "book":
            changes = {
                key: value
                for key, value in values.items()
                if key not in {"tags", "cover_ref"}
            }
            if "cover_ref" in values:
                changes.update(
                    cover_path=resolved_cover,
                    cover_status="READY" if resolved_cover else "PENDING",
                )
            if changes:
                SqlAlchemyBookMutation(self._db).update_book(
                    book_id=before.target_id, values=changes
                )
            if "tags" in values:
                merged = {**before.values, **values}
                facet = prepare_book_facet(
                    BookFacetProjection(
                        before.target_id,
                        cast(str | None, merged["author"]),
                        json.dumps(merged["tags"], ensure_ascii=False),
                        cast(str | None, merged["series_name"]),
                    )
                )
                prepared = prepare_book_facet_write((facet,), now=db_timestamp())
                execute_book_facet_write(self._db, prepared)
                row = self._db.get(LibraryBookMetadata, before.target_id)
                if row is None:
                    raise MetadataPatchError("RESOURCE_NOT_FOUND")
                row.protected_fields = protect_fields(row.protected_fields, {"tags"})
        elif before.target_type == "resource":
            resource_values: dict[str, object] = {
                key: value for key, value in values.items() if key != "cover_ref"
            }
            if "cover_ref" in values:
                resource_values["cover_path"] = resolved_cover
            if isinstance(resource_values.get("published_at"), str):
                resource_values["published_at"] = datetime.fromisoformat(
                    str(resource_values["published_at"])
                )
            SqlAlchemyResourceMetadata(self._db).update_resource(
                resource_id=before.target_id,
                changes=cast(ResourceMetadataChanges, resource_values),
                now=db_timestamp(),
            )
        else:
            merged = {**before.values, **values}
            changed = SqlAlchemySourceNodeMetadata(self._db).update_metadata(
                book_id=before.book_id,
                source_node_id=before.target_id,
                changes=SourceNodeMetadataChanges(
                    title=str(merged["title"]),
                    description=cast(str | None, merged["description"]),
                    changed_fields=frozenset(
                        key for key in values if key != "cover_ref"
                    ),
                    replace_cover="cover_ref" in values,
                    cover_path=resolved_cover,
                    writeback_policy=MetadataSideEffectPolicy.DATABASE_ONLY,
                ),
            )
            if not changed:
                raise MetadataPatchError("RESOURCE_NOT_FOUND")
        if patch.automatic:
            # Low-level writers protect explicit human edits. Automatic patches
            # retain the prior ownership inside the same transaction.
            owner = (self._db.get(LibraryBookMetadata, before.target_id) if before.target_type == "book"
                     else self._db.get(LibraryReadableResourceMetadata, before.target_id))
            if owner is not None:
                owner.protected_fields = json.dumps(sorted("cover_path" if key == "cover_ref" else key for key in before.protected))
        self._db.flush()

    def apply_uploaded_cover(self, before: MetadataSnapshot, stored_path: str) -> None:
        """A validated upload path is internal; external cover_ref still resolves candidates."""
        current = self.snapshot("book", before.book_id, frozenset({before.library_id}))
        if current is None or current.revision != before.revision:
            raise MetadataPatchError("CONFLICT")
        if before.source_node_id is None:
            raise MetadataPatchError("RESOURCE_NOT_FOUND")
        changed = SqlAlchemySourceNodeMetadata(self._db).update_metadata(
            book_id=before.book_id,
            source_node_id=before.source_node_id,
            changes=SourceNodeMetadataChanges(
                title=str(before.values["title"]),
                description=cast(str | None, before.values.get("description")),
                cover_path=stored_path,
                replace_cover=True,
                changed_fields=frozenset(),
                writeback_policy=MetadataSideEffectPolicy.DATABASE_ONLY,
            ),
        )
        if not changed:
            raise MetadataPatchError("RESOURCE_NOT_FOUND")
        self._db.flush()

    def record(
        self, actor: MetadataPatchActor, patches: tuple[PreparedMetadataPatch, ...]
    ) -> str:
        prepared = prepare_operation_write(
            user_id=actor.user_id,
            action="UPDATE_METADATA",
            target_type="metadata",
            target_id=None,
            summary="已更新系统元数据 / System metadata updated",
            payload={
                "grantId": actor.grant_id,
                "systemTaskId": actor.system_task_id,
                "changes": [
                    {
                        "type": item.before.target_type,
                        "id": item.before.target_id,
                        "before": {
                            field: item.before.values[field] for field in item.values
                        },
                        "after": item.values,
                        "source": item.provenance,
                    }
                    for item in patches
                ],
            },
            inverse={},
            now=db_timestamp(),
            undoable=False,
        )
        write_prepared_operation(self._db, prepared)
        return str(prepared.record["id"])
