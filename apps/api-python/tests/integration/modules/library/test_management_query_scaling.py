from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import LibraryBook, LibraryBookFacet, LibraryFacet, LibrarySourceNode
from app.modules.library.infrastructure.facets import list_categories_page


def test_categories_remain_page_bounded(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    facet_count = 1_000
    db_session.execute(
        insert(LibraryFacet),
        [
            {
                "id": f"management-author-{index:04d}",
                "kind": "AUTHOR",
                "name": f"Scale author {index:04d}",
                "normalized_name": f"scaleauthor{index:04d}",
                "aliases": "[]",
                "created_at": now,
                "updated_at": now,
            }
            for index in range(facet_count)
        ],
    )
    book_count = 100_000
    duplicate_book_count = 10_000
    for start in range(0, book_count, 1_000):
        stop = min(book_count, start + 1_000)
        db_session.execute(
            insert(LibrarySourceNode),
            [
                {
                    "id": f"management-book-node-{index:06d}",
                    "library_id": "test-library",
                    "relative_path": f"management-book-{index:06d}/",
                    "path_key": f"v1:{index:064x}",
                    "name": f"management-book-{index:06d}",
                    "physical_kind": "DIRECTORY",
                    "observed_size_bytes": None,
                    "observed_mtime_ns": 0,
                    "observed_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db_session.execute(
            insert(LibraryBook),
            [
                {
                    "id": f"management-book-{index:06d}",
                    "library_id": "test-library",
                    "source_node_id": f"management-book-node-{index:06d}",
                    "visibility_state": "VISIBLE",
                    "curation_state": "PENDING",
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db_session.execute(
            insert(LibraryBookFacet),
            [
                {
                    "facet_id": f"management-author-{index % facet_count:04d}",
                    "book_id": f"management-book-{index:06d}",
                    "sort_order": 0,
                    "created_at": now,
                }
                for index in range(start, stop)
            ],
        )
    db_session.commit()

    categories, category_total, category_page = list_categories_page(
        db_session,
        "AUTHOR",
        page=1,
        page_size=20,
    )
    assert category_total == facet_count
    assert category_page == 1
    assert len(categories) == 20
    assert all(category["bookCount"] == 100 for category in categories)
