"""Scoped snapshots and reuse of the existing database-only metadata writers."""

import hashlib
import json
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


class SqlAlchemyMetadataPatches:
    def __init__(self, db: Session) -> None:
        self._db = db

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
                select(LibraryBook).where(
                    LibraryBook.id == target_id, LibraryBook.library_id.in_(library_ids)
                )
            )
            if entity is None:
                return None
            metadata = self._db.get(LibraryBookMetadata, target_id)
            book_id, library_id = entity.id, entity.library_id
        elif target_type == "resource":
            resource = self._db.scalar(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.id == target_id,
                    LibraryReadableResource.library_id.in_(library_ids),
                )
            )
            if resource is None:
                return None
            metadata = self._db.get(LibraryReadableResourceMetadata, target_id)
            book_id, library_id = resource.book_id, resource.library_id
        elif target_type == "source_node":
            node = self._db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.id == target_id,
                    LibrarySourceNode.library_id.in_(library_ids),
                    LibrarySourceNode.physical_kind == "DIRECTORY",
                )
            )
            if node is None:
                return None
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
                        func.substr(
                            node.relative_path, 1, func.length(root_path) + 1
                        )
                        == root_path + "/",
                    ),
                )
                .limit(2)
            ).all()
            if len(owners) != 1:
                return None
            book_id, library_id = owners[0].id, node.library_id
            metadata = self._db.get(LibrarySourceNodeMetadata, target_id)
            if owners[0].source_node_id == node.id:
                linked = book_id
                owner_metadata = self._db.get(LibraryBookMetadata, book_id)
        else:
            return None
        values: dict[str, MetadataValue] = {}
        for field in METADATA_FIELDS[target_type]:
            value = getattr(metadata, field, None)
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
        related = None
        if owner_metadata is not None:
            protected |= protected_fields(owner_metadata.protected_fields) & {
                "title",
                "description",
            }
            related = (
                owner_metadata.title,
                owner_metadata.description,
                owner_metadata.protected_fields,
                to_timestamp_ms(owner_metadata.updated_at),
            )
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
            {"title": owner_metadata.title, "description": owner_metadata.description}
            if owner_metadata is not None
            else None,
        )

    def apply(self, patch: PreparedMetadataPatch) -> None:
        before, values = patch.before, patch.values
        current = self.snapshot(
            before.target_type, before.target_id, frozenset({before.library_id})
        )
        if current is None or current.revision != before.revision:
            raise MetadataPatchError("CONFLICT")
        if before.target_type == "book":
            changes = {key: value for key, value in values.items() if key != "tags"}
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
            resource_values: dict[str, object] = dict(values)
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
                    changed_fields=frozenset(values),
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
                "changes": [
                    {
                        "type": item.before.target_type,
                        "id": item.before.target_id,
                        "before": {
                            field: item.before.values[field] for field in item.values
                        },
                        "after": item.values,
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
