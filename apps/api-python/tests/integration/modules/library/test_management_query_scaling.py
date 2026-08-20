from __future__ import annotations

from datetime import UTC, datetime

from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.infrastructure.facets import list_categories_page
from sqlalchemy import insert
from sqlalchemy.orm import Session


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
    work_count = 100_000
    duplicate_work_count = 10_000
    for start in range(0, work_count, 1_000):
        stop = min(work_count, start + 1_000)
        db_session.execute(
            insert(LibraryWork),
            [
                {
                    "id": f"management-work-{index:06d}",
                    "library_id": "test-library",
                    "origin": "MANUAL",
                    "title": (
                        f"Duplicate {index // 2:04d}"
                        if index < duplicate_work_count
                        else f"Unique {index:06d}"
                    ),
                    "normalized_title": (
                        f"duplicate{index // 2:04d}"
                        if index < duplicate_work_count
                        else f"unique{index:06d}"
                    ),
                    "author": "Scale author",
                    "normalized_author": "scaleauthor",
                    "tags": "[]",
                    "hidden": False,
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db_session.execute(
            insert(LibraryWorkFacet),
            [
                {
                    "facet_id": f"management-author-{index % facet_count:04d}",
                    "work_id": f"management-work-{index:06d}",
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
