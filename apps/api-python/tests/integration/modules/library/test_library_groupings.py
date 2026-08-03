from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models.auth import User
from app.models.library import LibraryWork
from app.modules.library.application.groupings import ListLibraryGroupings
from app.modules.library.infrastructure.groupings import (
    SqlAlchemyLibraryGroupingQueries,
)
from app.services.library_management import sync_work_facets


def _work(
    *,
    work_id: str,
    title: str,
    author: str,
    series: str | None = None,
    hidden: bool = False,
) -> LibraryWork:
    return LibraryWork(
        id=work_id,
        title=title,
        normalized_title=title.casefold(),
        author=author,
        normalized_author=author.casefold(),
        tags="[]",
        series_name=series,
        hidden=hidden,
    )


def test_groupings_split_authors_filter_visibility_search_and_page(
    db_session: Session,
) -> None:
    user = User(
        email="library-groupings@example.com",
        name="书库分组",
        password_hash="unused",
        role="admin",
    )
    db_session.add(user)
    db_session.add_all(
        [
            _work(
                work_id="series-2",
                title="第二卷",
                author="林川、周禾",
                series="星海丛书",
            ),
            _work(
                work_id="series-1",
                title="第一卷",
                author="林川",
                series="星海丛书",
            ),
            _work(
                work_id="single-series",
                title="单卷",
                author="艾青",
                series="单卷系列",
            ),
            _work(
                work_id="unknown-author",
                title="佚名作品",
                author="未知作者",
            ),
            _work(
                work_id="hidden-series",
                title="隐藏卷",
                author="秘密作者",
                series="隐藏系列",
                hidden=True,
            ),
        ]
    )
    db_session.commit()
    for work_id in (
        "series-2",
        "series-1",
        "single-series",
        "unknown-author",
        "hidden-series",
    ):
        sync_work_facets(db_session, work_id)

    context = authorization_context(db_session, user)
    query = ListLibraryGroupings(SqlAlchemyLibraryGroupingQueries(db_session))
    engine = db_session.get_bind()
    executed_statements = 0

    def count_statement(*_args: object) -> None:
        nonlocal executed_statements
        executed_statements += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        authors = query.execute(
            kind="AUTHOR",
            context=context,
            search="",
            page=1,
            page_size=20,
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert executed_statements == 2
    assert [(group.name, group.book_count) for group in authors.groups] == [
        ("周禾", 1),
        ("林川", 2),
        ("艾青", 1),
    ]
    assert all(group.name not in {"未知作者", "秘密作者"} for group in authors.groups)

    series_page_1 = query.execute(
        kind="SERIES",
        context=context,
        search="",
        page=1,
        page_size=1,
    )
    series_page_2 = query.execute(
        kind="SERIES",
        context=context,
        search="星海",
        page=1,
        page_size=20,
    )
    assert series_page_1.total == 2
    assert [group.name for group in series_page_1.groups] == ["单卷系列"]
    assert [(group.name, group.book_count) for group in series_page_2.groups] == [
        ("星海丛书", 2)
    ]

    restricted_user = User(
        email="restricted-library-groupings@example.com",
        name="受限用户",
        password_hash="unused",
        role="member",
        can_view_manual_imports=False,
    )
    db_session.add(restricted_user)
    db_session.commit()
    restricted = query.execute(
        kind="AUTHOR",
        context=authorization_context(db_session, restricted_user),
        search="",
        page=1,
        page_size=20,
    )
    assert restricted.total == 0
    assert restricted.groups == ()
