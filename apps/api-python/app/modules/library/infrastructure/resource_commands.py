"""SQLAlchemy adapter for Resource metadata commands."""

from __future__ import annotations

from datetime import datetime
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
)


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

__all__ = ["SqlAlchemyResourceMetadata"]
