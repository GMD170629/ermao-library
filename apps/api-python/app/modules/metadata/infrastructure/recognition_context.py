"""Bounded, detached recognition evidence for one explicit library target."""

import hashlib
import json
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
    OrganizePolicy,
)
from app.modules.metadata.domain.recognition import (
    Contributor,
    IdentityEvidence,
    RecognitionContext,
)


def _revision(values: tuple[tuple[str, object], ...]) -> str:
    return hashlib.sha256(
        json.dumps(values, default=str, sort_keys=True).encode()
    ).hexdigest()


def _protected(raw: str | None) -> frozenset[str]:
    value = json.loads(raw or "[]")
    return (
        frozenset(
            "cover_ref" if field == "cover_path" else field
            for field in value
            if isinstance(field, str)
        )
        if isinstance(value, list)
        else frozenset()
    )


def load_recognition_context(
    db: Session,
    *,
    book_id: str,
    resource_id: str | None = None,
    source_node_id: str | None = None,
    execution: Literal["MANUAL", "AUTOMATIC"] = "MANUAL",
) -> RecognitionContext | None:
    row = db.execute(
        select(LibraryBook, LibraryBookMetadata)
        .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(LibraryBook.id == book_id)
    ).one_or_none()
    if row is None:
        return None
    book, metadata = row
    root = db.get(LibrarySourceNode, book.source_node_id)
    node = db.get(LibrarySourceNode, source_node_id) if source_node_id else root
    if (
        root is None
        or node is None
        or node.library_id != book.library_id
        or not (
            node.id == root.id
            or node.relative_path.startswith(root.relative_path.rstrip("/") + "/")
        )
    ):
        return None
    policy = db.get(OrganizePolicy, "default")
    config_revision = _revision(
        (("rules", "recognition-m1"), ("policy", policy.updated_at if policy else None))
    )
    related = _revision(
        (
            ("book_id", book.id),
            ("library_id", book.library_id),
            ("title", metadata.title),
            ("author", metadata.author),
            ("updated_at", metadata.updated_at),
            ("protected", metadata.protected_fields),
        )
    )
    authors = (Contributor(metadata.author),) if metadata.author else ()
    if resource_id is not None:
        resource_row = db.execute(
            select(LibraryReadableResource, LibraryReadableResourceMetadata)
            .outerjoin(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .where(
                LibraryReadableResource.id == resource_id,
                LibraryReadableResource.book_id == book.id,
                LibraryReadableResource.library_id == book.library_id,
            )
        ).one_or_none()
        if resource_row is None:
            return None
        resource, resource_metadata = resource_row
        resource_node = db.get(LibrarySourceNode, resource.source_node_id)
        if resource_node is None or not (
            resource_node.id == node.id
            or resource_node.relative_path.startswith(
                node.relative_path.rstrip("/") + "/"
            )
        ):
            return None
        names: tuple[str, ...] = (
            "title",
            "description",
            "publisher",
            "published_at",
            "language",
            "isbn",
            "identifier",
            "narrator",
            "abridged",
            "resource_index",
            "cover_path",
        )
        values = tuple((name, getattr(resource_metadata, name, None)) for name in names)
        protected = _protected(
            resource_metadata.protected_fields if resource_metadata else None
        )
        parent_protected = _protected(metadata.protected_fields)
        identity = IdentityEvidence(
            title=resource_metadata.title if resource_metadata else resource_node.name,
            authors=authors,
            isbn=resource_metadata.isbn if resource_metadata else None,
            # The persisted ISBN has no scope/provenance; protection confirms
            # the value, not whether it identifies a set or an edition.
            isbn_scope="UNKNOWN",
            resource_volume=(
                str(resource_metadata.resource_index)
                if resource_metadata
                and resource_metadata.resource_index is not None
                and "resource_index" in protected
                else None
            ),
            # Book roots may also be ordinary directories. Use the existing
            # manual title/author confirmation, never the directory name alone.
            work_title=(
                metadata.title
                if {"title", "author"} <= parent_protected and metadata.author
                else None
            ),
            publisher=resource_metadata.publisher if resource_metadata else None,
            language=resource_metadata.language if resource_metadata else None,
        )
        revision = _revision(
            (
                *values,
                (
                    "updated_at",
                    resource_metadata.updated_at if resource_metadata else None,
                ),
                ("protected", sorted(protected)),
                ("book_id", book.id),
                ("library_id", book.library_id),
                ("node_id", resource.source_node_id),
            )
        )
        return RecognitionContext(
            "resource",
            resource.id,
            book.id,
            book.library_id,
            identity,
            resource_id=resource.id,
            revision=revision,
            related_revision=related,
            parent_title=metadata.title,
            values=values,
            protected=protected,
            provenance=tuple((name, "UNKNOWN") for name in names),
            allowed_fields=frozenset(
                "resource." + ("cover_ref" if name == "cover_path" else name)
                for name in names
            ),
            execution=execution,
            config_revision=config_revision,
        )
    node_metadata = (
        db.get(LibrarySourceNodeMetadata, node.id) if node.id != root.id else None
    )
    title = (
        (node_metadata.title if node_metadata and node_metadata.title else node.name)
        if node.id != root.id
        else metadata.title
    )
    # Determine aggregation with two IDs only; never borrow the first resource's ISBN.
    resource_ids = db.scalars(
        select(LibraryReadableResource.id)
        .where(LibraryReadableResource.book_id == book.id)
        .limit(2)
    ).all()
    names = (
        "title",
        "author",
        "description",
        "series_name",
        "series_index",
        "cover_path",
    )
    values = tuple((name, getattr(metadata, name, None)) for name in names)
    protected = _protected(metadata.protected_fields)
    return RecognitionContext(
        "book",
        book.id,
        book.id,
        book.library_id,
        IdentityEvidence(title, authors),
        revision=_revision(
            (
                *values,
                ("updated_at", metadata.updated_at),
                ("protected", sorted(protected)),
                ("node_id", node.id),
            )
        ),
        related_revision=related,
        aggregate=len(resource_ids) > 1,
        values=values,
        protected=protected,
        provenance=tuple((name, "UNKNOWN") for name in names),
        allowed_fields=frozenset(
            "book." + ("cover_ref" if name == "cover_path" else name) for name in names
        )
        if node.id == root.id
        else frozenset(),
        execution=execution,
        config_revision=config_revision,
    )


def provider_context(db: Session, context: RecognitionContext) -> dict[str, object]:
    """Compatibility input for providers, limited before materialization."""
    query = select(LibraryReadableResource).where(
        LibraryReadableResource.book_id == context.book_id,
        LibraryReadableResource.library_id == context.library_id,
    )
    if context.resource_id:
        query = query.where(LibraryReadableResource.id == context.resource_id)
    resources = db.scalars(query.order_by(LibraryReadableResource.id).limit(8)).all()
    resource_ids = [resource.id for resource in resources]
    file_names = (
        db.scalars(
            select(LibrarySourceNode.name)
            .join(
                LibraryResourceAsset,
                LibraryResourceAsset.source_node_id == LibrarySourceNode.id,
            )
            .where(
                LibraryResourceAsset.resource_id.in_(resource_ids),
                LibraryResourceAsset.library_id == context.library_id,
            )
            .order_by(LibraryResourceAsset.id)
            .limit(8)
        ).all()
        if resource_ids
        else []
    )
    values = dict(context.values)
    return {
        "book": {
            "id": context.book_id,
            "title": context.identity.title,
            "author": " / ".join(
                author.name
                for author in context.identity.authors
                if author.role == "author"
            ),
            "description": values.get("description"),
            "seriesName": values.get("series_name"),
            "seriesIndex": values.get("series_index"),
        },
        "resources": [
            {"format": item.format, "hidden": item.enablement_state != "ENABLED"}
            for item in resources
        ],
        "files": [{"relativePath": name} for name in file_names],
        "metadata": [],
    }
