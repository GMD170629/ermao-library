from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.infrastructure.facets import list_categories_page
from app.modules.library.presentation.views import _work_views
from app.services.library_management import duplicate_groups_page


def test_categories_and_duplicates_remain_page_bounded(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        User(
            id="management-scale-admin",
            email="management-scale@example.test",
            name="Management scale admin",
            password_hash="test",
            role="admin",
        )
    )
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

    select_count = 0

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        groups, duplicate_total, duplicate_page = duplicate_groups_page(
            db_session,
            page=1,
            page_size=20,
        )
        works = [work for group in groups for work in group["works"]]
        views = _work_views(db_session, works, "management-scale-admin")
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert duplicate_total == 5_000
    assert duplicate_page == 1
    assert len(groups) == 20
    assert len(views) == 40
    assert select_count <= 10
