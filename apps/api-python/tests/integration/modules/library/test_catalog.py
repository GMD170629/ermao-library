from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models.auth import User, UserLibraryAccess
from app.models.library import (
    LibraryFacet,
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
    LibraryWorkFacet,
)
from app.models.library import Library
from app.modules.library.application.catalog import (
    CatalogWorkFilter,
    GetCatalogWork,
    ListCatalogFacets,
    ListCatalogWorks,
)
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries


def _work(work_id: str, title: str, *, hidden: bool = False) -> LibraryWork:
    return LibraryWork(
            library_id="test-library", 
        id=work_id,
        title=title,
        normalized_title=title.casefold(),
        author="Catalog Author",
        normalized_author="catalog author",
        tags="[]",
        hidden=hidden,
    )


def _add_volume(
    db: Session,
    *,
    work_id: str,
    volume_id: str,
    media_kind: str = "EBOOK",
    import_status: str = "COMPLETED",
    library_id: str | None = None,
    with_file: bool = True,
    hidden: bool = False,
) -> None:
    media = LibraryMediaVersion(
        id=f"media-{volume_id}",
        work_id=work_id,
        media_kind=media_kind,
    )
    volume = LibraryVolume(
        id=volume_id,
        media_version_id=media.id,
        title=f"Volume {volume_id}",
        format="CBZ" if media_kind == "COMIC" else "EPUB",
        resource_key=f"catalog:{volume_id}",
        import_status=import_status,
        hidden=hidden,
    )
    db.add_all([media, volume])
    if with_file:
        db.add(
            LibraryFile(
                id=f"file-{volume_id}",
                volume_id=volume.id,
                path=f"books/{volume_id}.bin",
                kind="BOOK",
                mime_type=(
                    "application/zip"
                    if media_kind == "COMIC"
                    else "application/epub+zip"
                ),
                size_bytes=123,
            )
        )


def test_catalog_lists_only_authorized_publishable_books_and_facets(
    db_session: Session,
) -> None:
    admin = User(
        id="catalog-admin",
        email="catalog-admin@example.com",
        name="Catalog Admin",
        password_hash="unused",
        role="admin",
    )
    works = [
        _work("ebook", "Alpha"),
        _work("comic", "Beta"),
        _work("legacy", "Gamma"),
        _work("audio", "Audio"),
        _work("pending", "Pending"),
        _work("no-file", "No File"),
        _work("hidden-work", "Hidden", hidden=True),
    ]
    db_session.add(admin)
    db_session.add_all(works)
    db_session.flush()
    _add_volume(db_session, work_id="ebook", volume_id="ebook")
    _add_volume(
        db_session,
        work_id="comic",
        volume_id="comic",
        media_kind="COMIC",
        import_status="READY",
    )
    _add_volume(
        db_session,
        work_id="legacy",
        volume_id="legacy",
        import_status="IMPORTED",
    )
    _add_volume(db_session, work_id="audio", volume_id="audio", media_kind="AUDIOBOOK")
    _add_volume(
        db_session, work_id="pending", volume_id="pending", import_status="PENDING"
    )
    _add_volume(db_session, work_id="no-file", volume_id="no-file", with_file=False)
    _add_volume(db_session, work_id="hidden-work", volume_id="hidden-work")
    facet = LibraryFacet(
        id="tag-catalog",
        kind="TAG",
        name="Catalog",
        normalized_name="catalog",
    )
    db_session.add(facet)
    db_session.add_all(
        [
            LibraryWorkFacet(facet_id=facet.id, work_id="ebook"),
            LibraryWorkFacet(facet_id=facet.id, work_id="audio"),
        ]
    )
    db_session.commit()

    context = authorization_context(db_session, admin)
    queries = SqlAlchemyCatalogQueries(db_session)
    listed = ListCatalogWorks(queries).execute(context=context, page_size=2)

    assert listed.total == 3
    assert [work.id for work in listed.works] == ["ebook", "comic"]
    assert listed.works[0].volumes[0].file.mime_type == "application/epub+zip"
    second_page = ListCatalogWorks(queries).execute(
        context=context, page=2, page_size=2
    )
    assert [work.id for work in second_page.works] == ["legacy"]
    assert GetCatalogWork(queries).execute(context=context, work_id="audio") is None

    tags = ListCatalogFacets(queries).execute(context=context, kind="TAG")
    assert [(tag.id, tag.work_count) for tag in tags.facets] == [("tag-catalog", 1)]
    filtered = ListCatalogWorks(queries).execute(
        context=context,
        filters=CatalogWorkFilter(facet_kind="TAG", facet_id="tag-catalog"),
    )
    assert [work.id for work in filtered.works] == ["ebook"]


def test_catalog_applies_member_volume_scope_inside_queries(
    db_session: Session,
) -> None:
    member = User(
        id="catalog-member",
        email="catalog-member@example.com",
        name="Catalog Member",
        password_hash="unused",
        role="member",
        can_view_manual_imports=False,
    )
    allowed_folder = Library(
            organization_mode="FLAT", 
        id="folder-allowed", name="Allowed", root_path="/allowed"
    )
    denied_folder = Library(
            organization_mode="FLAT", 
        id="folder-denied", name="Denied", root_path="/denied"
    )
    db_session.add_all(
        [
            member,
            allowed_folder,
            denied_folder,
            _work("allowed", "Allowed"),
            _work("denied", "Denied"),
            _work("manual", "Manual"),
        ]
    )
    db_session.flush()
    db_session.add(
        UserLibraryAccess(user_id=member.id, library_id=allowed_folder.id)
    )
    _add_volume(
        db_session,
        work_id="allowed",
        volume_id="allowed",
        library_id=allowed_folder.id,
    )
    _add_volume(
        db_session,
        work_id="denied",
        volume_id="denied",
        library_id=denied_folder.id,
    )
    _add_volume(db_session, work_id="manual", volume_id="manual")
    db_session.commit()

    context = authorization_context(db_session, member)
    listed = ListCatalogWorks(SqlAlchemyCatalogQueries(db_session)).execute(
        context=context
    )

    assert [work.id for work in listed.works] == ["allowed"]


def test_catalog_empty_work_id_filter_does_not_expand_to_all_works(
    db_session: Session,
) -> None:
    admin = User(
        id="empty-filter-admin",
        email="empty-filter@example.com",
        name="Empty Filter",
        password_hash="unused",
        role="admin",
    )
    db_session.add_all([admin, _work("present", "Present")])
    db_session.flush()
    _add_volume(db_session, work_id="present", volume_id="present")
    db_session.commit()

    page = ListCatalogWorks(SqlAlchemyCatalogQueries(db_session)).execute(
        context=authorization_context(db_session, admin),
        filters=CatalogWorkFilter(work_ids=()),
    )

    assert page.total == 0
    assert page.works == ()
