from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.bootstrap.library import (
    execute_book_facet_write,
    load_book_facet_projections,
    prepare_book_facet_write,
)
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibrarySourceNode,
)
from app.modules.library.public import prepare_book_facet
from tests.support.sqlalchemy import StatementRecorder


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def test_prepared_facet_sync_uses_existing_real_ids_and_preserves_updated_at(
    db_session: Session,
) -> None:
    original_updated_at = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
    book_node = LibrarySourceNode(
        id="prepared-facet-book-node",
        library_id="test-library",
        relative_path="prepared-facet-work/",
        path_key=_path_key("prepared-facet-work/"),
        name="prepared-facet-work",
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=0,
        observed_at=original_updated_at,
    )
    book = LibraryBook(
        library_id="test-library",
        id="prepared-facet-work",
        source_node_id=book_node.id,
        updated_at=original_updated_at,
    )
    metadata = LibraryBookMetadata(
        book_id=book.id,
        title="Prepared facets",
        normalized_title="preparedfacets",
        author="Old author",
        normalized_author="oldauthor",
        updated_at=original_updated_at,
    )
    existing_author = LibraryFacet(
        id="arbitrary-existing-author-id",
        kind="AUTHOR",
        name="Existing display author",
        normalized_name="newauthor",
        aliases='["kept"]',
    )
    existing_tag = LibraryFacet(
        id="existing-tag-id",
        kind="TAG",
        name="Tag A",
        normalized_name="taga",
    )
    db_session.add(book_node)
    db_session.flush()
    db_session.add(book)
    db_session.flush()
    db_session.add_all(
        [
            metadata,
            existing_author,
            existing_tag,
        ]
    )
    db_session.flush()
    db_session.add(LibraryBookFacet(facet_id=existing_tag.id, book_id=book.id))
    db_session.commit()

    projection = load_book_facet_projections(db_session, (book.id,))[0]
    db_session.rollback()
    prepared_book = prepare_book_facet(
        replace(
            projection,
            author="New author",
            tags_source='["Tag A", "Tag A"]',
            series_name="Series A",
        )
    )
    prepared_write = prepare_book_facet_write(
        (prepared_book,), now=datetime(2026, 8, 11, 8, 1, tzinfo=UTC)
    )

    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    with StatementRecorder(engine) as recorder:
        recorder.reset_after_warmup()
        db_session.execute(
            update(LibraryBookMetadata)
            .where(LibraryBookMetadata.book_id == book.id)
            .values(
                author="New author",
                normalized_author="newauthor",
                series_name="Series A",
                updated_at=LibraryBookMetadata.updated_at,
            )
        )
        execute_book_facet_write(db_session, prepared_write)
        db_session.commit()

    links = db_session.execute(
        select(LibraryFacet.kind, LibraryFacet.id)
        .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
        .where(LibraryBookFacet.book_id == book.id)
    ).all()
    assert dict(links)["AUTHOR"] == existing_author.id
    assert {kind for kind, _facet_id in links} == {"AUTHOR", "TAG", "SERIES"}
    refreshed_metadata = db_session.get(LibraryBookMetadata, book.id)
    assert refreshed_metadata is not None
    assert refreshed_metadata.updated_at == original_updated_at
    assert recorder.statement_count <= 6
