"""Bounded, detached recognition evidence for one explicit library target."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.local_metadata_snapshot import decode_observations
from app.infrastructure.local_metadata_policy import SqlAlchemyLocalMetadataPriority
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
from app.models.import_pipeline import Source
from app.models.organize import MetadataLookupTask
from app.modules.metadata.application.local_metadata import (
    LocalMetadataCandidate,
    resolve_local_metadata,
)
from app.modules.metadata.domain.recognition import (
    Contributor,
    IdentityEvidence,
    RecognitionContext,
    normalize_isbn,
    recognition_fingerprint,
)
from app.modules.metadata.infrastructure.sources import METADATA_SOURCE_KIND


def _revision(values: tuple[tuple[str, object], ...]) -> str:
    return hashlib.sha256(
        json.dumps(values, default=lambda value: (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat(timespec="milliseconds") if isinstance(value, datetime) else str(value), sort_keys=True).encode()
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


def _resource_provenance(db: Session, resource_id: str, current: tuple[tuple[str, object], ...]) -> tuple[tuple[str, str], ...]:
    # A single persisted source observation can establish a field's origin.
    # Multi-asset aggregation remains UNKNOWN; never infer PATH from a filename.
    rows = db.scalars(select(LibraryResourceAsset.local_metadata_candidates)
        .where(LibraryResourceAsset.resource_id == resource_id, LibraryResourceAsset.import_state == "READY")
        .order_by(LibraryResourceAsset.id).limit(2)).all()
    origins = dict.fromkeys(dict(current), "UNKNOWN")
    if len(rows) != 1 or not rows[0]:
        return tuple(origins.items())
    observations = decode_observations(rows[0])
    resolved = resolve_local_metadata(tuple(LocalMetadataCandidate(item.source, item.metadata) for item in observations),
                                      SqlAlchemyLocalMetadataPriority(db).load())
    sources = dict(resolved.field_sources)
    for name, value in current:
        original = (resolved.metadata.volume_title or resolved.metadata.title) if name == "title" else getattr(resolved.metadata, name, None)
        source_name = "volumeTitle" if name == "title" and resolved.metadata.volume_title else name
        if value is not None and value == original:
            origins[name] = sources.get(source_name, "UNKNOWN")
    return tuple(origins.items())


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
        (("rules", "recognition-m2"), ("policy", policy.updated_at if policy else None),
         ("sources", tuple(db.execute(select(Source.id, Source.updated_at)
                           .where(Source.kind == METADATA_SOURCE_KIND)
                           .order_by(Source.id).limit(32)).all())))
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
        values = tuple((name, float(value) if name == "resource_index" and value is not None else value)
                       for name in names for value in [getattr(resource_metadata, name, None)])
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
        records = db.scalars(select(MetadataLookupTask.candidate_raw_json)
            .where(MetadataLookupTask.book_id == book.id, MetadataLookupTask.resource_id == resource.id,
                   MetadataLookupTask.status == "COMPLETED")
            .order_by(MetadataLookupTask.created_at.desc()).limit(8)).all()
        for encoded in records:
            saved = json.loads(encoded or "{}")
            evidence = saved.get("recognition", {})
            selected = saved.get("selected", {})
            if (evidence.get("humanConfirmed") and evidence.get("targetType") == "resource"
                and evidence.get("targetId") == resource.id
                and evidence.get("confirmedRevision") == revision
                and evidence.get("confirmedRelatedRevision") == related
                and selected.get("source") and selected.get("id")):
                identity = replace(identity, source_ids=((str(selected["source"]), str(selected["id"])),))
                if (selected.get("isbnScope") == "EDITION" and normalize_isbn(identity.isbn or "")
                    and normalize_isbn(identity.isbn or "") == normalize_isbn(str(selected.get("isbn") or ""))):
                    identity = replace(identity, isbn_scope="EDITION")
                break
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
            provenance=_resource_provenance(db, resource.id, values),
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
        "identity": {
            "isbn": context.identity.isbn,
            "isbnScope": context.identity.isbn_scope,
            "workTitle": context.identity.work_title,
            "aliases": context.identity.aliases,
            "targetType": context.target_type,
            "targetId": context.target_id,
            "libraryId": context.library_id,
            "revision": context.revision,
            "relatedRevision": context.related_revision,
            "configRevision": context.config_revision,
            "execution": context.execution,
        },
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


def recognition_retry_suppressed(db: Session, book_id: str) -> bool:
    raw = db.scalar(select(MetadataLookupTask.candidate_raw_json)
                    .where(MetadataLookupTask.book_id == book_id)
                    .order_by(MetadataLookupTask.created_at.desc()).limit(1))
    if not raw:
        return False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Legacy opaque payloads have no reusable recognition decision.
        return False
    record = payload.get("recognition") if isinstance(payload, dict) else None
    if not isinstance(record, dict) or record.get("schemaVersion") not in {2, 3}:
        return False
    context = load_recognition_context(db, book_id=book_id, resource_id=record.get("targetId") if record.get("targetType") == "resource" else None, execution="AUTOMATIC")
    if context is None or record.get("fingerprint") != recognition_fingerprint(context):
        return False
    if record.get("outcome") == "AMBIGUOUS" or record.get("ignored") is True:
        return True
    return (record.get("outcome") == "NO_MATCH"
            and isinstance(record.get("retryAfter"), (int, float))
            and record["retryAfter"] > datetime.now(UTC).timestamp())
