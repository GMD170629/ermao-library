from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models.auth import User, UserLibraryAccess
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.models.library import Library
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
            library_id="test-library", 
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

    # One bounded page query plus one batched representative-work query.
    assert executed_statements == 2
    assert [(group.name, group.book_count) for group in authors.groups] == [
        ("周禾", 1),
        ("林川", 2),
        ("艾青", 1),
    ]
    assert all(group.name not in {"未知作者", "秘密作者"} for group in authors.groups)
    lin_chuan = next(group for group in authors.groups if group.name == "林川")
    assert {work.id for work in lin_chuan.representative_works} == {
        "series-1",
        "series-2",
    }
    assert len(lin_chuan.representative_works) <= 3

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


def test_grouping_representative_works_are_limited_to_authorized_scope(
    db_session: Session,
) -> None:
    user = User(
        id="grouping-scope-user",
        email="grouping-scope@example.com",
        name="分组权限",
        password_hash="unused",
        role="member",
    )
    db_session.add_all(
        [
            user,
            Library(
            organization_mode="FLAT", id="allowed-folder", name="可见", root_path="/allowed"),
            Library(
            organization_mode="FLAT", id="denied-folder", name="不可见", root_path="/denied"),
            UserLibraryAccess(
                user_id=user.id,
                library_id="allowed-folder",
            ),
        ]
    )
    for work_id, folder_id in (
        ("allowed-work", "allowed-folder"),
        ("denied-work", "denied-folder"),
    ):
        work = _work(work_id=work_id, title=work_id, author="共同作者")
        media = LibraryMediaVersion(
            id=f"media-{work_id}",
            work_id=work_id,
            media_kind="EBOOK",
        )
        volume = LibraryVolume(
            id=f"volume-{work_id}",
            version_id=media.id,
            title=work_id,
            format="EPUB",
            resource_key=f"resource-{work_id}",
            import_status="COMPLETED",
        )
        db_session.add_all([work, media, volume])
    db_session.commit()
    sync_work_facets(db_session, "allowed-work")
    sync_work_facets(db_session, "denied-work")

    result = ListLibraryGroupings(
        SqlAlchemyLibraryGroupingQueries(db_session)
    ).execute(
        kind="AUTHOR",
        context=authorization_context(db_session, user),
        search="共同作者",
        page=1,
        page_size=20,
    )

    assert len(result.groups) == 1
    assert result.groups[0].book_count == 1
    assert [work.id for work in result.groups[0].representative_works] == [
        "allowed-work"
    ]
