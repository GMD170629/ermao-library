"""SQLAlchemy adapter for Resource metadata and media classification."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    book_visibility_predicate,
    resource_visibility_predicate,
)
from app.models import (
    LibraryBook,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
)
from app.modules.library.application.resource_commands import (
    LibraryActor,
    ResourceContext,
    ResourceMetadataChanges,
    ResourceReclassifyOutcome,
    SetResourceMediaKindsOutcome,
)
from app.modules.library.infrastructure import operations as operation_store


def _resource_snapshot(resource: LibraryReadableResource) -> dict[str, object]:
    return {
        "id": resource.id,
        "mediaKind": resource.media_kind,
        "updatedAt": resource.updated_at,
    }


class SqlAlchemyResourceMetadata:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _authorization_context(actor: LibraryActor) -> AuthorizationContext:
        return AuthorizationContext(
            user_id=actor.user_id,
            is_admin=actor.is_admin,
            can_manage_system=actor.can_manage_system,
            can_view_manual_imports=actor.can_view_manual_imports,
            library_ids=actor.library_ids,
            authz_version=1,
        )

    def can_access_book(self, *, actor: LibraryActor, book_id: str) -> bool:
        context = self._authorization_context(actor)
        return (
            self._db.scalar(
                select(LibraryBook.id).where(
                    LibraryBook.id == book_id,
                    book_visibility_predicate(context),
                )
            )
            is not None
        )

    def get_resource_context(
        self, *, actor: LibraryActor, book_id: str, resource_id: str
    ) -> ResourceContext | None:
        contexts = self.get_resource_contexts(
            actor=actor,
            book_id=book_id,
            resource_ids=(resource_id,),
        )
        return contexts[0] if contexts else None

    def get_resource_contexts(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_ids: tuple[str, ...],
    ) -> tuple[ResourceContext, ...]:
        if not resource_ids:
            return ()
        context = self._authorization_context(actor)
        rows = self._db.execute(
            select(
                LibraryReadableResource,
                LibraryReadableResourceMetadata.resource_index,
            )
            .join(
                LibraryBook,
                LibraryBook.id == LibraryReadableResource.book_id,
            )
            .outerjoin(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .where(
                LibraryReadableResource.id.in_(resource_ids),
                LibraryReadableResource.book_id == book_id,
                resource_visibility_predicate(context),
            )
        ).all()
        by_id = {
            resource.id: ResourceContext(
                id=resource.id,
                book_id=resource.book_id,
                media_kind=resource.media_kind,
                sort_order=(
                    int(resource_index) if resource_index is not None else 2**31 - 1
                ),
            )
            for resource, resource_index in rows
        }
        return tuple(
            by_id[resource_id] for resource_id in resource_ids if resource_id in by_id
        )

    def update_resource(
        self,
        *,
        resource_id: str,
        changes: ResourceMetadataChanges,
        now: datetime,
    ) -> None:
        metadata = self._db.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is None:
            metadata = LibraryReadableResourceMetadata(
                resource_id=resource_id,
                title=str(changes.get("title") or ""),
            )
            self._db.add(metadata)
        metadata_fields = {
            "title",
            "description",
            "publisher",
            "published_at",
            "language",
            "identifier",
            "isbn",
            "narrator",
            "abridged",
            "resource_index",
        }
        for field, value in changes.items():
            if field in metadata_fields:
                setattr(metadata, field, value)
        metadata.updated_at = now

    def set_media_kinds(
        self,
        *,
        actor_id: str,
        book_id: str,
        contexts: tuple[ResourceContext, ...],
        target_media_kind: str,
        now: datetime,
    ) -> SetResourceMediaKindsOutcome:
        operation_ids: list[str] = []
        affected_ids: list[str] = []
        for context in contexts:
            resource = self._db.get(LibraryReadableResource, context.id)
            if resource is None or resource.book_id != book_id:
                raise ValueError("Resource does not exist")
            operation = operation_store.prepare_operation_write(
                user_id=actor_id,
                action="RECLASSIFY_RESOURCE",
                target_type="resource",
                target_id=context.id,
                summary=f"Reclassified Resource as {target_media_kind}",
                payload={
                    "bookId": book_id,
                    "resourceId": context.id,
                    "targetMediaKind": target_media_kind,
                    "applyTo": "RESOURCE",
                },
                inverse={"resources": [_resource_snapshot(resource)]},
                now=now,
            )
            resource.media_kind = target_media_kind
            resource.updated_at = now
            operation_store.write_prepared_operation(self._db, operation)
            operation_ids.append(str(operation.record["id"]))
            affected_ids.append(resource.id)
        return SetResourceMediaKindsOutcome(
            affected_resource_ids=tuple(affected_ids),
            operation_ids=tuple(operation_ids),
        )

    def reclassify_resource(
        self,
        *,
        actor_id: str,
        book_id: str,
        resource_id: str,
        target_media_kind: str,
        apply_to: Literal["RESOURCE", "SAME_MEDIA_KIND"],
        now: datetime,
    ) -> ResourceReclassifyOutcome:
        resource = self._db.get(LibraryReadableResource, resource_id)
        if resource is None or resource.book_id != book_id:
            raise ValueError("Resource does not exist")
        current_kind = resource.media_kind
        selected = [resource]
        if apply_to == "SAME_MEDIA_KIND":
            selected = list(
                self._db.scalars(
                    select(LibraryReadableResource)
                    .where(
                        LibraryReadableResource.book_id == book_id,
                        LibraryReadableResource.media_kind == current_kind,
                    )
                    .order_by(
                        LibraryReadableResource.created_at.asc(),
                        LibraryReadableResource.id.asc(),
                    )
                ).all()
            )
        operation = operation_store.prepare_operation_write(
            user_id=actor_id,
            action="RECLASSIFY_RESOURCE",
            target_type="resource",
            target_id=resource_id,
            summary=f"Reclassified {len(selected)} Resource(s) as {target_media_kind}",
            payload={
                "bookId": book_id,
                "resourceId": resource_id,
                "targetMediaKind": target_media_kind,
                "applyTo": apply_to,
            },
            inverse={"resources": [_resource_snapshot(row) for row in selected]},
            now=now,
        )
        for selected_resource in selected:
            selected_resource.media_kind = target_media_kind
            selected_resource.updated_at = now
        operation_store.write_prepared_operation(self._db, operation)
        return ResourceReclassifyOutcome(
            affected_resource_ids=tuple(row.id for row in selected),
            operation=operation_store.operation_summary(operation.record),
        )


__all__ = ["SqlAlchemyResourceMetadata"]
